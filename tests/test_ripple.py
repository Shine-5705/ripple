import os, subprocess, tempfile, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from ripple import core


def _repo():
    d = tempfile.mkdtemp()
    run = lambda *a: subprocess.run(["git", "-C", d, *a], check=True, capture_output=True)
    run("init", "-q"); run("config", "user.email", "t@e.st"); run("config", "user.name", "Tester")
    def commit(files, msg):
        for f in files:
            p = os.path.join(d, f); os.makedirs(os.path.dirname(p) or d, exist_ok=True)
            open(p, "a").write(msg + "\n")
        run("add", "-A"); run("commit", "-qm", msg)
    for i in range(4):
        commit(["api.py", "tests/test_api.py"], f"api change {i}")
    commit(["api.py", "README.md"], "docs")
    commit(["util.py"], "util")
    return d


def test_ingest_and_context():
    repo = _repo(); db = os.path.join(tempfile.mkdtemp(), "g.rl")
    s = core.ingest(repo, db)
    assert s["commits"] == 6 and s["files"] == 4 and s["authors"] == 1
    conn = core.connect(db)
    c = core.context(conn, "api.py")
    assert c["changes"] == 5
    top = c["co_changes"][0]
    assert top["path"] == "tests/test_api.py" and top["together"] == 4 and abs(top["confidence"] - 0.8) < 1e-9
    assert c["experts"][0]["author"] == "Tester"


def test_check_flags_missing_test():
    repo = _repo(); db = os.path.join(tempfile.mkdtemp(), "g.rl")
    core.ingest(repo, db); conn = core.connect(db)
    r = core.check(conn, ["api.py"])
    assert [x["missing"] for x in r["possibly_missing"]] == ["tests/test_api.py"]
    assert core.check(conn, ["api.py", "tests/test_api.py"])["possibly_missing"] == []


def test_unknown_file():
    repo = _repo(); db = os.path.join(tempfile.mkdtemp(), "g.rl")
    core.ingest(repo, db); conn = core.connect(db)
    assert "error" in core.context(conn, "nope.py")
