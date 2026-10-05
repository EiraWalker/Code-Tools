# Refresh the cache from the existing index workflow

Extend the workflow that already builds and publishes the original `.db`.
Do not add another indexer, per-query downloader, or independent indexing schedule.
Immediately after the graph is pushed to its destination repository, call
`scripts/sync_graph_cache.py` with that same committed file.

## Publisher configuration

Give only the publisher job `id-token: write` alongside its existing permissions.
Keep its branch guard, concurrency group and check that the source commit has not
been superseded. Mark the publication step with an `id` and emit
`published=true` to `GITHUB_OUTPUT` only after its destination push succeeds.
Run synchronization only when that output is `true`.

The script requires:

| Variable | Value |
| --- | --- |
| `CBM_READER_ORIGIN` | The HTTPS origin of your existing Render service |
| `CBM_SYNC_GRAPH_FILE` | Path to the `.db` just committed to the destination |
| `GITHUB_SHA` | Existing Actions source commit variable |

Use the public script at a reviewed immutable commit, or copy the reviewed script
into your existing workflow support directory and keep that copy in sync.
The script uses Python's standard library. It obtains a short-lived GitHub OIDC
token for audience `<reader-origin>/snapshot-sync`; no new long-lived secret is
required. It masks the token and does not log request credentials or responses.

## Render configuration

Set these values privately via the Render API, preserving existing credentials:

| Variable | Value |
| --- | --- |
| `CBM_SYNC_REPOSITORY` | Repository running the existing index workflow |
| `CBM_SYNC_REPOSITORY_ID` | Its numeric GitHub repository ID |
| `CBM_SYNC_OWNER_ID` | Its numeric GitHub owner ID; required for immutable subjects |
| `CBM_SYNC_REF` | Exact allowed ref, for example `refs/heads/main` |
| `CBM_SYNC_WORKFLOW` | Existing workflow path, for example `.github/workflows/code-index.yml` |

The backend verifies GitHub's RS256 signature, fixed issuer and audience,
expiry, repository name and ID, branch, exact workflow ref, source commit and
event type. Only `push` and `workflow_dispatch` from that workflow are accepted.
The ordinary MCP bearer token cannot authorize cache updates.

GitHub repositories created after July 15, 2026 use an immutable default
subject: `repo:OWNER@OWNER-ID/REPO@REPO-ID:ref:refs/heads/BRANCH`.
Earlier repositories can retain `repo:OWNER/REPO:ref:refs/heads/BRANCH`.
The backend accepts exactly these two subjects for its configured identity;
the immutable form requires `CBM_SYNC_OWNER_ID` and verifies the separate owner
ID claim too. Never relax the signature, repository ID, branch or workflow gates
to work around a subject-format mismatch. See the [official OIDC reference](https://docs.github.com/en/actions/reference/security/oidc).

`POST /snapshot-sync` compares blob SHA and SHA256 using small metadata. An
unchanged version returns `unchanged`; no graph bytes are sent. A changed
version returns `upload_required`, then authenticated `PUT /snapshot-sync`
streams the original binary file. Size, SQLite header, SHA256, Git blob SHA and
native engine project identity must all pass before activation.

Each version has its own dedicated native cache directory. Queries and
activation share a lock, so a query and its provenance always use one version.
The active manifest is replaced atomically. An invalid or interrupted upload
leaves the previous cache active; an older workflow run cannot replace a newer
activated run. At most the active and preceding uploaded versions are retained.
Run a single backend process/instance; cross-process coordination is not provided.

## Persistence and verification

Ordinary queries are entirely local, including after automatic synchronization.
The original build-time download remains a bootstrap mechanism for a fresh
deployment, not the refresh mechanism. A valid runtime manifest survives process
restart on the same filesystem. Render's free ephemeral filesystem is not a
persistent disk: a new deployment can bootstrap an older configured snapshot.
After deploying, run the existing publisher once to seed the current version;
future successful publications update it automatically. To preserve generations
across replacement instances, use a persistent disk on a suitable Render plan.

Verify a publisher run completes with `Graph reader cache: refreshed.` or
`unchanged.`. Then call `list_projects` and compare returned snapshot blob SHA,
SHA256 and source commit with the file and provenance that the workflow published.
Re-running synchronization with the same graph must skip the binary upload.
