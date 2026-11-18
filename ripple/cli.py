"""ripple — git co-change context for coding agents, backed by Relate."""
import argparse, json, subprocess, sys, datetime
from . import core, __version__


def _ago(ts):
    if not ts:
        return "-"
    d = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
    return d.strftime("%Y-%m-%d")


def _changed(repo, staged):
    args = ["git", "-C", repo, "diff", "--name-only"] + (["--cached"] if staged else ["HEAD"])
    return [l for l in subprocess.run(args, capture_output=True, text=True).stdout.splitlines() if l]


def main(argv=None):
    p = argparse.ArgumentParser(prog="ripple", description=__doc__)
    p.add_argument("--db", default=".ripple.rl", help="Relate store (single file). Default .ripple.rl")
    p.add_argument("--json", action="store_true", help="machine-readable output for agents")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("ingest", help="load git history into the graph"); i.add_argument("repo", nargs="?", default="."); i.add_argument("-n", "--limit", type=int)
    c = sub.add_parser("context", help="what changes with this file, who knows it, recent history"); c.add_argument("path"); c.add_argument("-k", type=int, default=8)
    k = sub.add_parser("check", help="files historically coupled to your change set but missing from it")
    k.add_argument("paths", nargs="*", help="changed files (default: git diff)"); k.add_argument("--repo", default="."); k.add_argument("--staged", action="store_true")
    k.add_argument("--min-confidence", type=float, default=0.5); k.add_argument("--min-together", type=int, default=3); k.add_argument("--strict", action="store_true", help="exit 1 when files are missing (for hooks/CI)")
    h = sub.add_parser("hotspots", help="most-changed files and how coupled they are"); h.add_argument("-k", type=int, default=10)
    s = sub.add_parser("stats", help="graph size")
    e = sub.add_parser("export", help="export a JSON snapshot for the web explorer"); e.add_argument("out"); e.add_argument("--top", type=int, default=150)
    a = p.parse_args(argv)

    if a.cmd == "ingest":
        r = core.ingest(a.repo, a.db, a.limit)
        print(json.dumps(r) if a.json else f"ingested {r['commits']} commits, {r['files']} files, {r['authors']} authors, {r['co_change_edges']} co-change edges into {a.db} in {r['seconds']}s")
        return 0
    conn = core.connect(a.db)
    if a.cmd == "context":
        r = core.context(conn, a.path, a.k)
        if a.json: print(json.dumps(r, default=str)); return 0
        if "error" in r: print(r["error"]); return 2
        print(f"{r['path']}  ·  {r['changes']} commits  ·  last {_ago(r['last_ts'])}\n")
        print("Usually changes with:")
        for x in r["co_changes"]:
            print(f"  {x['confidence']*100:5.1f}%  {x['together']:>4}×  {x['path']}")
        print("\nPeople who know it:")
        for x in r["experts"]:
            print(f"  {x['commits']:>4} commits  {x['author']}  (last {_ago(x['last_ts'])})")
        print("\nRecent commits:")
        for x in r["recent_commits"]:
            print(f"  {x['sha'][:8]}  {_ago(x['ts'])}  {x['msg']}")
    elif a.cmd == "check":
        paths = a.paths or _changed(a.repo, a.staged)
        r = core.check(conn, paths, a.min_confidence, a.min_together)
        if a.json: print(json.dumps(r))
        else:
            if not r["possibly_missing"]:
                print(f"ok — nothing historically coupled is missing from {len(paths)} changed file(s)")
            for x in r["possibly_missing"]:
                print(f"  ? {x['missing']}  — changed with {x['because_of']} in {x['confidence']*100:.0f}% of its commits ({x['together']}×)")
        return 1 if (a.strict and r["possibly_missing"]) else 0
    elif a.cmd == "hotspots":
        r = core.hotspots(conn, a.k)
        if a.json: print(json.dumps(r))
        else:
            for x in r: print(f"  {x['changes']:>5} commits  {x['coupled']:>4} coupled  {x['path']}")
    elif a.cmd == "stats":
        print(json.dumps(core.stats(conn)))
    elif a.cmd == "export":
        from .export import export
        r = export(conn, a.out, a.top); print(json.dumps(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
