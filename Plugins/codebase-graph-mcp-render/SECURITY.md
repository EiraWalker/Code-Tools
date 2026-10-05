# Privacy and security boundaries

Public template code is separate from private snapshots and deployment state.
Never publish database files, local cache, signed URLs, source access tokens,
Render API keys, backend service tokens, user email/passwords, private symbols,
private repository identifiers, or production service/project/plugin IDs.

Use separate credentials for deployment management, snapshot download and backend
queries. Store them in platform secret fields. Normal agent queries do not need
management credentials. An `.env` example must contain placeholders only.

The snapshot downloader requires HTTPS, rejects URL-embedded credentials,
refuses redirects, validates size/header/SHA256/Git blob SHA, and atomically
installs verified bytes. The graph engine checks scope and integrity before/after
queries. The adapter exposes exactly five read tools and bounds native processes.
This is not a multi-tenant service or a substitute for rate limits and production
resource controls.

Sites identity headers are trusted only behind Sites authenticated dispatch with
the proper private audience. On a generic public Worker, clients can forge those
headers. Do not deploy this proxy there without independent identity validation.

Health checks disclose readiness only. Native diagnostics are deliberately
redacted. Snapshot provenance is visible only in authorized query results; it
can itself reveal private repository names and must not be copied into public posts.

Before publication, run the publication checker. Review every reported path;
it prints locations only, not matched secret values. It is a defense against
accidental copying, not a guarantee that arbitrary secrets can be detected.
Also inspect the exact Git tree and the committed history before making it public.

To report a vulnerability, avoid publishing exploit data or credentials. Use
GitHub's private vulnerability reporting if the repository owner enables it.
