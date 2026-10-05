"""Append to an existing index publisher, after its successful repository push.

Uses stdlib only. OIDC credentials and response bodies never enter logs.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


def exchange(origin):
    issuer_url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"]
    separator = "&" if "?" in issuer_url else "?"
    request = Request(issuer_url + separator + "audience=" + quote(origin + "/snapshot-sync", safe=""),
        headers={"Authorization": "Bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]})
    with urlopen(request, timeout=30) as response:
        token = json.load(response)["value"]
    print("::add-mask::" + token, flush=True)
    print("GitHub OIDC publisher identity obtained.", flush=True)
    # Diagnostic booleans only; the backend alone verifies JWT signatures.
    claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    now = int(time.time())
    hints = {"issuer_matches": claims.get("iss") == "https://token.actions.githubusercontent.com",
             "audience_matches": claims.get("aud") == origin + "/snapshot-sync",
             "repository_matches": claims.get("repository") == os.environ.get("GITHUB_REPOSITORY"),
             "ref_matches": claims.get("ref") == os.environ.get("GITHUB_REF"),
             "workflow_matches": claims.get("workflow_ref") == os.environ.get("GITHUB_WORKFLOW_REF"),
             "event_matches": claims.get("event_name") == os.environ.get("GITHUB_EVENT_NAME"),
             "source_commit_matches": claims.get("sha") == os.environ.get("GITHUB_SHA"),
             "not_expired": int(claims.get("exp", 0)) > now,
             "not_before_valid": int(claims.get("nbf", now + 1)) <= now,
             "run_number_present": "run_number" in claims,
             "run_attempt_present": "run_attempt" in claims}
    print("OIDC diagnostic checks: " + json.dumps(hints, sort_keys=True), flush=True)
    return token


def sync_once(origin, data, identity):
    token = exchange(origin)
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    if identity.get("project"):
        headers["X-Snapshot-Project"] = identity["project"]
    with urlopen(Request(origin + "/snapshot-sync", data=json.dumps(identity).encode(),
                         headers=headers, method="POST"), timeout=90) as response:
        status = json.load(response)["status"]
    if status == "upload_required":
        headers.update({"Content-Type": "application/octet-stream", "Content-Length": str(len(data)),
                        "X-Snapshot-Sha256": identity["sha256"],
                        "X-Snapshot-Blob-Sha": identity["blob_sha"],
                        "X-Source-Commit": identity["source_commit"]})
        with urlopen(Request(origin + "/snapshot-sync", data=data, headers=headers, method="PUT"),
                     timeout=180) as response:
            status = json.load(response)["status"]
    if status not in {"refreshed", "unchanged", "superseded"}:
        raise ValueError("Unexpected sync response")
    return status


def main():
    origin = os.environ["CBM_READER_ORIGIN"].rstrip("/")
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
        raise ValueError("Reader origin must be one HTTPS origin")
    path = Path(os.environ["CBM_SYNC_GRAPH_FILE"])
    maximum = int(os.environ.get("CBM_GRAPH_MAX_BYTES", "268435456"))
    if not 16 <= path.stat().st_size <= maximum:
        raise ValueError("Invalid snapshot size")
    data = path.read_bytes()
    if not data.startswith(b"SQLite format 3\0"):
        raise ValueError("Expected an original SQLite graph")
    identity = {"sha256": hashlib.sha256(data).hexdigest(),
                "blob_sha": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
                "size_bytes": len(data), "source_commit": os.environ["GITHUB_SHA"],
                "project": os.environ.get("CBM_SYNC_PROJECT", path.stem)}
    for attempt in range(6):
        try:
            status = sync_once(origin, data, identity)
            message = "Graph reader cache: " + status + "."
            print(message)
            if os.environ.get("GITHUB_STEP_SUMMARY"):
                with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
                    summary.write(message + "\n")
            return
        except HTTPError as error:
            # Log only status, never credential-bearing URLs or response bodies.
            print("Cache sync HTTP status " + str(error.code), flush=True)
            if error.code not in {429, 500, 502, 503, 504} or attempt == 5:
                raise ValueError("Cache sync HTTP status " + str(error.code)) from None
        except (URLError, TimeoutError, OSError):
            if attempt == 5:
                raise ValueError("Cache sync network request failed") from None
        time.sleep(10 * (attempt + 1))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("::error::Graph cache sync failed (" + type(error).__name__ + "); inspect the private service and rerun the existing publisher.")
        sys.exit(1)
