import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from snapshot_cache import SnapshotCache
from snapshot_sync import PublisherAuth


def identity(data):
    return {"sha256": hashlib.sha256(data).hexdigest(),
            "blob_sha": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
            "size_bytes": len(data), "source_commit": "a" * 40}


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old = b"SQLite format 3\0original-fixture"
        self.new = b"SQLite format 3\0changed-fixture"
        (self.root / "fixture.db").write_bytes(self.old)
        initial = identity(self.old)
        self.cache = SnapshotCache(self.root, "fixture", initial["sha256"], initial["blob_sha"])
        self.incoming = self.root / ".test-upload"
        self.incoming.write_bytes(self.new)

    def tearDown(self):
        self.temp.cleanup()

    def install(self, number=2, validator=lambda snapshot: None):
        return self.cache.install(self.incoming, identity(self.new), number, 1, validator)

    def test_unchanged_version_never_reads_upload_or_calls_native(self):
        self.assertEqual(self.cache.check(identity(self.old), 1, 1), "unchanged")
        self.assertEqual(self.cache.check(identity(self.old), 1, 2), "unchanged")
        self.assertEqual((self.cache.active.directory / "fixture.db").read_bytes(), self.old)

    def test_refresh_survives_restart_and_older_run_is_rejected(self):
        self.assertEqual(self.install(), "refreshed")
        active = self.cache.active
        initial = identity(self.old)
        restarted = SnapshotCache(self.root, "fixture", initial["sha256"], initial["blob_sha"])
        self.assertEqual(restarted.active, active)
        self.assertEqual(restarted.check(initial, 1, 1), "superseded")
        self.assertEqual((active.directory / "fixture.db").read_bytes(), self.new)
        self.assertEqual((self.root / "fixture.db").read_bytes(), self.old)

    def test_corrupt_upload_and_native_failure_leave_active_manifest_unchanged(self):
        self.cache.check(identity(self.old), 1, 1)
        before = self.cache.pointer.read_bytes()
        self.incoming.write_bytes(self.new + b"corruption")
        with self.assertRaises(ValueError):
            self.install()
        self.incoming.write_bytes(self.new)
        def reject(snapshot):
            raise ValueError("Native validation failed")
        with self.assertRaises(ValueError):
            self.install(validator=reject)
        self.assertEqual(self.cache.pointer.read_bytes(), before)
        self.assertEqual(self.cache.active.sha256, identity(self.old)["sha256"])
        self.assertFalse(list(self.cache.versions.glob(".incoming-*")))

    def test_activation_waits_for_query_generation_lock(self):
        validated = threading.Event()
        done = threading.Event()
        result = []
        def update():
            result.append(self.install(validator=lambda snapshot: validated.set()))
            done.set()
        with self.cache.lock:
            thread = threading.Thread(target=update)
            thread.start()
            self.assertTrue(validated.wait(5))
            self.assertFalse(done.is_set())
            self.assertEqual(self.cache.active.sha256, identity(self.old)["sha256"])
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, ["refreshed"])


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = int(time.time())
        self.claims = {"iss": "https://token.actions.githubusercontent.com",
            "aud": "https://reader.example/snapshot-sync", "iat": now, "nbf": now, "exp": now + 300,
            "sub": "repo:owner/source:ref:refs/heads/main", "repository": "owner/source",
            "repository_id": "42", "ref": "refs/heads/main",
            "workflow_ref": "owner/source/.github/workflows/code-index.yml@refs/heads/main",
            "event_name": "push", "sha": "a" * 40, "run_number": "2", "run_attempt": "1"}
        with patch.dict(os.environ, {"CBM_SYNC_REPOSITORY": "owner/source", "CBM_SYNC_REPOSITORY_ID": "42"}):
            self.auth = PublisherAuth("https://reader.example")
        self.auth.keys = Mock()
        self.auth.keys.get_signing_key_from_jwt.return_value.key = self.key.public_key()

    def signed(self, claims=None):
        return "Bearer " + jwt.encode(claims or self.claims, self.key, algorithm="RS256")

    def test_expected_publisher_signature_and_scope(self):
        self.assertEqual(self.auth.verify(self.signed())["run_number"], "2")

    def test_wrong_repository_workflow_branch_audience_and_expired_token_rejected(self):
        cases = {"repository_id": "43", "workflow_ref": "owner/source/.github/workflows/other.yml@refs/heads/main",
                 "ref": "refs/heads/other", "aud": "https://other.example/snapshot-sync",
                 "exp": int(time.time()) - 1, "event_name": "pull_request", "iss": "https://other.example"}
        for field, value in cases.items():
            with self.subTest(field=field), self.assertRaises((ValueError, jwt.PyJWTError)):
                self.auth.verify(self.signed({**self.claims, field: value}))

    def test_ordinary_service_secret_and_unsigned_token_rejected(self):
        with self.assertRaises(jwt.PyJWTError):
            self.auth.verify("Bearer ordinary-service-secret")
        token = jwt.encode(self.claims, key="", algorithm="none")
        with self.assertRaises(jwt.PyJWTError):
            self.auth.verify("Bearer " + token)


class SenderTests(unittest.TestCase):
    def test_unchanged_response_skips_binary_upload(self):
        spec = importlib.util.spec_from_file_location("sync_sender", ROOT / "scripts/sync_graph_cache.py")
        sender = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sender)
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"status":"unchanged"}'
        with patch.object(sender, "exchange", return_value="test-token"), patch.object(sender, "urlopen", return_value=response) as send:
            self.assertEqual(sender.sync_once("https://reader.example", b"unused-upload", identity(b"unused-upload")), "unchanged")
            self.assertEqual(send.call_count, 1)
            self.assertEqual(send.call_args.args[0].method, "POST")


if __name__ == "__main__":
    unittest.main()
