"""Versioned original snapshots; queries and activation share one lock."""
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading


@dataclass(frozen=True)
class Snapshot:
    directory: Path
    sha256: str
    blob_sha: str
    run_number: int = 0
    run_attempt: int = 0
    source_commit: str = ""


def validate_graph(path, sha256, blob_sha, maximum):
    if not re.fullmatch(r"[a-f0-9]{64}", sha256) or not re.fullmatch(r"[a-f0-9]{40}", blob_sha):
        raise ValueError("Invalid snapshot identity")
    size = path.stat().st_size
    if size > maximum:
        raise ValueError("Snapshot exceeds configured size limit")
    digest = hashlib.sha256()
    blob = hashlib.sha1(b"blob " + str(size).encode() + b"\0")
    with path.open("rb") as source:
        if source.read(16) != b"SQLite format 3\0":
            raise ValueError("Expected original SQLite snapshot")
        source.seek(0)
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
            blob.update(chunk)
    if digest.hexdigest() != sha256 or blob.hexdigest() != blob_sha:
        raise ValueError("Snapshot checksum mismatch")
    return size


class SnapshotCache:
    def __init__(self, directory, project, sha256, blob_sha, maximum=268435456):
        self.directory = Path(directory).resolve()
        self.project = project
        self.maximum = maximum
        self.lock = threading.RLock()
        self.pointer = self.directory / "active-snapshot.json"
        self.versions = self.directory / ".versions"
        if self.pointer.exists():
            identity = json.loads(self.pointer.read_text())
            relative = identity.pop("directory")
            if relative != "." and relative != ".versions/" + identity["sha256"]:
                raise ValueError("Invalid cache manifest directory")
            self.active = Snapshot(directory=self.directory / relative, **identity)
        else:
            self.active = Snapshot(self.directory, sha256, blob_sha)
        self.validate(self.active)

    def validate(self, snapshot):
        if {p.name for p in snapshot.directory.glob("*.db")} != {self.project + ".db"}:
            raise ValueError("Cache must contain only the configured project")
        return validate_graph(snapshot.directory / (self.project + ".db"),
                              snapshot.sha256, snapshot.blob_sha, self.maximum)

    def _persist(self, snapshot):
        identity = {"directory": str(snapshot.directory.relative_to(self.directory)) or ".",
                    "sha256": snapshot.sha256, "blob_sha": snapshot.blob_sha,
                    "run_number": snapshot.run_number, "run_attempt": snapshot.run_attempt,
                    "source_commit": snapshot.source_commit}
        with tempfile.NamedTemporaryFile(mode="w", dir=self.directory, prefix=".manifest-", delete=False) as f:
            path = Path(f.name)
            try:
                json.dump(identity, f)
                f.flush()
                os.fsync(f.fileno())
                path.chmod(0o600)
                path.replace(self.pointer)
            finally:
                path.unlink(missing_ok=True)

    def check(self, identity, run_number, run_attempt):
        with self.lock:
            if (run_number, run_attempt) < (self.active.run_number, self.active.run_attempt):
                return "superseded"
            if identity["sha256"] == self.active.sha256 and identity["blob_sha"] == self.active.blob_sha:
                updated = replace(self.active, run_number=run_number, run_attempt=run_attempt)
                self._persist(updated)
                self.active = updated
                return "unchanged"
            return "upload_required"

    def install(self, incoming, identity, run_number, run_attempt, native_validate):
        size = validate_graph(incoming, identity["sha256"], identity["blob_sha"], self.maximum)
        if size != identity["size_bytes"]:
            raise ValueError("Snapshot size mismatch")
        self.versions.mkdir(mode=0o700, exist_ok=True)
        staging = Path(tempfile.mkdtemp(dir=self.versions, prefix=".incoming-"))
        try:
            graph = staging / (self.project + ".db")
            shutil.copyfile(incoming, graph)
            graph.chmod(0o600)
            candidate = Snapshot(staging, identity["sha256"], identity["blob_sha"],
                                 run_number, run_attempt, identity.get("source_commit", ""))
            native_validate(candidate)
            self.validate(candidate)
            with self.lock:
                status = self.check(identity, run_number, run_attempt)
                if status != "upload_required":
                    return status
                previous = self.active.directory
                destination = self.versions / candidate.sha256
                if destination.exists():
                    self.validate(replace(candidate, directory=destination))
                else:
                    staging.replace(destination)
                candidate = replace(candidate, directory=destination)
                self._persist(candidate)
                self.active = candidate
                # No query can use a generation during activation/cleanup.
                for version in self.versions.iterdir():
                    if re.fullmatch(r"[a-f0-9]{64}", version.name) and version not in {destination, previous}:
                        shutil.rmtree(version, ignore_errors=True)
                return "refreshed"
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
