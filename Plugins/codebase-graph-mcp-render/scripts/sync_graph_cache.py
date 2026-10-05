"""Append to an existing index publisher, after its successful repository push.

Uses stdlib only. OIDC credentials and response bodies never enter logs.
"""
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
    return token


def sync_once(origin, data, identity):
    token = exchange(origin)
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
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
                "size_bytes": len(data), "source_commit": os.environ["GITHUB_SHA"]}
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
            # A 422 is a rejected snapshot, not a transient service wakeup.
            if error.code == 422 or attempt == 5:
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
