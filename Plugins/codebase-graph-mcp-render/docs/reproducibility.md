# Reproducibility and validation record

This template adapts a previously deployed native MCP pipeline. It pins the
upstream query engine to v0.11.0, commit
`8972ea69c6ad94b1ef1d4ffbf0a92d78d2db1798`, and locks Python dependencies.

Template checks:

- Six snapshot transfer/integrity tests, using synthetic bytes only.
- Worker access, credential isolation, redirect and visible-provenance tests.
- Bash syntax checks and Python compilation.
- Integration script using a disposable COPY of an authorized snapshot and the
  pinned native engine. Its output excludes private graph identity and symbols.
- Publication file inventory and privacy pattern scan before publishing.

Build this upstream version on Linux x86_64. The template intentionally does not
redistribute its large executable. Rebuild it from the pinned source and retain
licenses when distributing your own build. A new architecture or upstream
version requires its own compatibility test.

Local native transport tests do not prove a new user's Render deployment or
ChatGPT connection. Run the host acceptance steps in `verification.md` for
every new deployment. No reference service credentials or private fixture are
provided in this repository.
