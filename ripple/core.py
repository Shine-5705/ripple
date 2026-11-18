"""Ingest git history into a Relate graph and answer change-context questions."""
from __future__ import annotations
import subprocess, os, time
import relate

SEP = "\x1e"
MAX_FILES_PER_COMMIT = 40  # bulk renames / vendoring commits carry no coupling signal


def git_log(repo: str, limit: int | None = None):
    args = ["git", "-C", repo, "log", "--no-merges", "--numstat",
            f"--pretty=format:{SEP}%H%x1f%an%x1f%at%x1f%s"]
    if limit:
        args.insert(4, f"-n{limit}")
    out = subprocess.run(args, capture_output=True, text=True, check=True).stdout
    for block in out.split(SEP)[1:]:
        lines = block.strip("\n").split("\n")
        sha, author, ts, subject = (lines[0].split("\x1f") + ["", "", "", ""])[:4]
        files = []
        for ln in lines[1:]:
            parts = ln.split("\t")
            if len(parts) != 3 or "=>" in parts[2]:
                continue
            a, d, p = parts
            files.append({"p": p, "a": int(a) if a.isdigit() else 0, "d": int(d) if d.isdigit() else 0})
        yield {"sha": sha, "author": author, "ts": int(ts or 0), "msg": subject[:200], "files": files}


def connect(db: str):
    conn = relate.connect(db)
    for stmt in ("CREATE INDEX IF NOT EXISTS FOR (f:File) ON (f.path)",
                 "CREATE INDEX IF NOT EXISTS FOR (c:Commit) ON (c.sha)",
                 "CREATE INDEX IF NOT EXISTS FOR (a:Author) ON (a.name)"):
        try:
            conn.execute(stmt)
        except Exception:
            pass
    return conn


def ingest(repo: str, db: str, limit: int | None = None, batch: int = 200) -> dict:
    t0 = time.time()
    conn = connect(db)
    name = os.path.basename(os.path.abspath(repo))
    conn.execute("MERGE (r:Repo {name:$n}) SET r.path=$p, r.ingested_at=$t",
                 {"n": name, "p": os.path.abspath(repo), "t": int(time.time())})
    commits = [c for c in git_log(repo, limit) if 0 < len(c["files"]) <= MAX_FILES_PER_COMMIT]
    q = """
    UNWIND $rows AS c
    MERGE (cm:Commit {sha:c.sha}) SET cm.ts=c.ts, cm.msg=c.msg, cm.size=size(c.files)
    MERGE (a:Author {name:c.author})
    MERGE (cm)-[:AUTHORED_BY]->(a)
    WITH cm, c
    UNWIND c.files AS f
    MERGE (fi:File {path:f.p})
    MERGE (cm)-[t:TOUCHED]->(fi) SET t.added=f.a, t.deleted=f.d
    """
    for i in range(0, len(commits), batch):
        conn.execute(q, {"rows": commits[i:i + batch]})
    # file-level change counts and last-touched
    conn.execute("""MATCH (f:File)<-[:TOUCHED]-(c:Commit)
                    WITH f, count(c) AS n, max(c.ts) AS last
                    SET f.changes=n, f.last_ts=last""")
    # mark files that still exist at HEAD (history keeps renamed/deleted paths)
    live = subprocess.run(["git", "-C", repo, "ls-files"], capture_output=True, text=True).stdout.splitlines()
    conn.execute("MATCH (f:File) SET f.live=false")
    conn.execute("UNWIND $ps AS p MATCH (f:File {path:p}) SET f.live=true", {"ps": live})
    # derived co-change edges (materialised so agents can traverse them cheaply)
    conn.execute("MATCH ()-[r:CO_CHANGES]->() DELETE r")
    conn.execute("""
    MATCH (a:File)<-[:TOUCHED]-(c:Commit)-[:TOUCHED]->(b:File)
    WHERE a.path < b.path
    WITH a, b, count(c) AS n WHERE n >= 2
    MERGE (a)-[r:CO_CHANGES]->(b)
    SET r.n=n, r.conf_ab=toFloat(n)/a.changes, r.conf_ba=toFloat(n)/b.changes
    """)
    s = stats(conn)
    s["seconds"] = round(time.time() - t0, 2)
    conn.close()
    return s


def stats(conn) -> dict:
    r = {}
    for k, q in {"commits": "MATCH (c:Commit) RETURN count(c) AS n",
                 "files": "MATCH (f:File) RETURN count(f) AS n",
                 "authors": "MATCH (a:Author) RETURN count(a) AS n",
                 "co_change_edges": "MATCH ()-[r:CO_CHANGES]->() RETURN count(r) AS n"}.items():
        r[k] = conn.execute(q).fetchone()["n"]
    return r


def context(conn, path: str, k: int = 8) -> dict:
    f = conn.execute("MATCH (f:File {path:$p}) RETURN f.changes AS changes, f.last_ts AS last", {"p": path}).fetchone()
    if not f:
        return {"path": path, "error": "file not in graph; run `ripple ingest` or check the path is relative to the repo root"}
    co = conn.execute("""
      MATCH (f:File {path:$p})-[r:CO_CHANGES]-(o:File) WHERE o.live
      RETURN o.path AS path, r.n AS together,
             CASE WHEN startNode(r) = f THEN r.conf_ab ELSE r.conf_ba END AS confidence
      ORDER BY confidence DESC, together DESC LIMIT $k""", {"p": path, "k": k}).fetchall()
    experts = conn.execute("""
      MATCH (f:File {path:$p})<-[:TOUCHED]-(c:Commit)-[:AUTHORED_BY]->(a:Author)
      RETURN a.name AS author, count(c) AS commits, max(c.ts) AS last_ts
      ORDER BY commits DESC LIMIT 5""", {"p": path}).fetchall()
    recent = conn.execute("""
      MATCH (f:File {path:$p})<-[:TOUCHED]-(c:Commit)
      RETURN c.sha AS sha, c.msg AS msg, c.ts AS ts ORDER BY c.ts DESC LIMIT 5""", {"p": path}).fetchall()
    return {"path": path, "changes": f["changes"], "last_ts": f["last"],
            "co_changes": [dict(r) for r in co], "experts": [dict(r) for r in experts],
            "recent_commits": [dict(r) for r in recent]}


def check(conn, changed: list[str], min_conf: float = 0.5, min_together: int = 3) -> dict:
    """Given a change set, list historically coupled files that are missing from it."""
    rows = conn.execute("""
      UNWIND $changed AS p
      MATCH (f:File {path:p})-[r:CO_CHANGES]-(o:File)
      WHERE o.live AND NOT o.path IN $changed
      WITH p, o, r, CASE WHEN startNode(r) = f THEN r.conf_ab ELSE r.conf_ba END AS conf
      WHERE conf >= $mc AND r.n >= $mt
      RETURN o.path AS missing, p AS because_of, r.n AS together, conf AS confidence
      ORDER BY confidence DESC, together DESC""",
      {"changed": changed, "mc": min_conf, "mt": min_together}).fetchall()
    seen, out = set(), []
    for r in rows:
        if r["missing"] in seen:
            continue
        seen.add(r["missing"]); out.append(dict(r))
    return {"changed": changed, "possibly_missing": out}


def hotspots(conn, k: int = 10) -> list[dict]:
    return [dict(r) for r in conn.execute("""
      MATCH (f:File) WHERE f.live OPTIONAL MATCH (f)-[r:CO_CHANGES]-(o:File) WHERE o.live
      WITH f, count(r) AS coupled
      RETURN f.path AS path, f.changes AS changes, coupled
      ORDER BY changes DESC LIMIT $k""", {"k": k}).fetchall()]
