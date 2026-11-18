# Ripple

**Know what else changes before your agent opens the PR.**

Ripple turns a repository's git history into a [Relate](https://github.com/relatedb/relate) graph of commits, files and people. Coding agents (and people) ask it three questions, locally, with no server:

- **`ripple context <file>`** — which files usually change with this one, who knows it, and its recent history.
- **`ripple check`** — which files are historically coupled to your change set but missing from it (works on `git diff`, `--staged`, or a list; `--strict` exits 1 for hooks and CI).
- **`ripple hotspots`** — the most-changed live files and how coupled they are.

Live explorer on real data (full pallets/flask history): **https://shine-5705.github.io/ripple/**

## Why a graph
"Tests, changelog and the sibling module usually change with this file" is a relationship question. Ripple stores it as one: a Cypher pass in Relate materialises `CO_CHANGES` edges with *directional* confidence (how often B changed when A did), so an agent gets an answer in one in-process traversal, and the whole thing is a single file it can carry around.

```
(:Commit {sha, ts, msg})-[:TOUCHED {added, deleted}]->(:File {path, changes, last_ts, live})
(:Commit)-[:AUTHORED_BY]->(:Author {name})
(:File)-[:CO_CHANGES {n, conf_ab, conf_ba}]->(:File)
(:Repo {name, path, ingested_at})
```

## Quick start
```bash
python -m venv .venv && . .venv/bin/activate
pip install git+https://github.com/Shine-5705/ripple      # pulls relate-db
cd your-repo
ripple ingest .                                  # writes .ripple.rl (single Relate store)
ripple context src/app.py
ripple check                                     # against your working-tree diff
ripple --json check --staged                     # for agents
```

Try it without a repo of your own — a persistent store built from pallets/flask is checked in:
```bash
ripple --db examples/flask.ripple.rl context src/flask/sessions.py
ripple --db examples/flask.ripple.rl check src/flask/json/provider.py src/flask/app.py
```

Example output (pallets/flask @ 49943b5):
```
src/flask/sessions.py  ·  33 commits  ·  last 2026-10-07

Usually changes with:
   57.6%    19×  CHANGES.rst
   48.5%    16×  src/flask/app.py
   45.5%    15×  tests/test_basic.py
   45.5%    15×  src/flask/helpers.py
```

## For coding agents
- `skill/SKILL.md` is a drop-in skill for Claude Code / Cursor / Codex: run `context` before editing and `check --staged` before committing.
- Every command takes `--json`.
- Pre-commit hook:
  ```sh
  #!/bin/sh
  ripple check --staged --strict || { echo "Ripple: coupled files missing"; exit 1; }
  ```
- The store is plain Relate, so anything else is one Cypher query away: `relate -d .ripple.rl "MATCH (f:File)-[r:CO_CHANGES]-(o) WHERE f.path='x' RETURN o.path, r.n"`.

## How it works
1. `git log --no-merges --numstat` → batched `UNWIND … MERGE` into Relate (≈1.3 s for Flask's 3,817 commits on a laptop-class box).
2. Commits touching more than 40 files (bulk renames, formatting sweeps) are skipped — they carry no coupling signal.
3. Files present at `HEAD` are marked `live`; renamed/deleted paths stay in history but are hidden from answers.
4. `CO_CHANGES` edges are materialised for pairs that changed together ≥2 times; `check` defaults to confidence ≥0.5 and ≥3 co-changes.
5. `ripple export` writes the JSON the static explorer (`docs/`) reads — every number on the site is produced by Cypher against the store.

## Limitations (honest list)
- Renames are not followed yet (`flask/app.py` and `src/flask/app.py` are separate nodes).
- Co-change is correlation, not causation; treat `check` output as a review prompt, not a rule.
- Author identity is the git author name (no mailmap yet).

## Development
```bash
pip install -e . pytest && pytest -q        # 3 tests, builds throwaway git repos
```

## Credits & license
- Built on [Relate](https://github.com/relatedb/relate) by Neo4j (Apache-2.0) via `relate-db`.
- Example data: public git history of [pallets/flask](https://github.com/pallets/flask) (BSD-3-Clause). No synthetic numbers anywhere.
- Ripple is Apache-2.0. Built by Shine Gupta for the Relate by Neo4j Hackathon (Nov 2026).
