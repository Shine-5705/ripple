"""Export a JSON snapshot (produced by Cypher queries against the Relate store) for the static explorer."""
import json, time
from . import core


def export(conn, out, top=150):
    files = [dict(r) for r in conn.execute("""
      MATCH (f:File) WHERE f.live AND f.changes >= 3
      RETURN f.path AS path, f.changes AS changes, f.last_ts AS last_ts
      ORDER BY changes DESC LIMIT $k""", {"k": top}).fetchall()]
    keep = [f["path"] for f in files]
    edges = [dict(r) for r in conn.execute("""
      MATCH (a:File)-[r:CO_CHANGES]->(b:File)
      WHERE a.path IN $keep AND b.path IN $keep AND r.n >= 3
      RETURN a.path AS a, b.path AS b, r.n AS n, r.conf_ab AS ab, r.conf_ba AS ba""", {"keep": keep}).fetchall()]
    detail = {}
    for f in keep:
        c = core.context(conn, f, 10)
        detail[f] = {"experts": c["experts"], "recent": [{"sha": x["sha"][:10], "msg": x["msg"], "ts": x["ts"]} for x in c["recent_commits"]]}
    repo = conn.execute("MATCH (r:Repo) RETURN r.name AS name").fetchone()
    snap = {"repo": repo["name"] if repo else None, "generated_at": int(time.time()), "stats": core.stats(conn),
            "files": files, "edges": edges, "detail": detail}
    with open(out, "w") as fh:
        json.dump(snap, fh, separators=(",", ":"), default=str)
    return {"files": len(files), "edges": len(edges), "out": out}
