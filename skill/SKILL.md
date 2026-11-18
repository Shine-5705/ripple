---
name: ripple
description: Before editing or committing in a git repo, ask Ripple (a Relate graph of the repo's history) which files usually change together, who knows a file, and which coupled files are missing from the current change.
---
# Ripple — change context

1. If `.ripple.rl` is missing or older than the last pull, run `ripple ingest .` (takes ~1–2 s for a few thousand commits).
2. Before editing a file, run `ripple --json context <path> -k 8`. Treat `co_changes` with confidence ≥ 0.5 as files you probably need to read or update too (tests, docs, changelog, sibling modules).
3. Before committing, run `ripple --json check --staged`. For each item in `possibly_missing`, either update that file or state in the commit/PR why it does not need to change.
4. For anything else, query the store directly with Cypher: `relate -d .ripple.rl "MATCH (f:File {path:'x'})-[r:CO_CHANGES]-(o) RETURN o.path, r.n"`.

Graph: `(:Commit {sha,ts,msg})-[:TOUCHED {added,deleted}]->(:File {path,changes,last_ts,live})`, `(:Commit)-[:AUTHORED_BY]->(:Author {name})`, `(:File)-[:CO_CHANGES {n,conf_ab,conf_ba}]->(:File)`.
