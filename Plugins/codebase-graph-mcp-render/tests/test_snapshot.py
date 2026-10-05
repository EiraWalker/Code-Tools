import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import httpx
spec = importlib.util.spec_from_file_location('snapshot', Path(__file__).resolve().parents[1] / 'backend/prepare_snapshot.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = b'SQLite format 3\0' + b'synthetic-download-test-only'
        self.config = {'CBM_PROJECT': 'fixture', 'CBM_CACHE_DIR': self.temp.name,
          'CBM_GRAPH_SHA256': hashlib.sha256(self.data).hexdigest(),
          'CBM_GRAPH_BLOB_SHA': hashlib.sha1(b'blob ' + str(len(self.data)).encode() + b'\0' + self.data).hexdigest(),
          'CBM_GRAPH_URL': 'https://source.example/snapshot', 'CBM_GRAPH_BEARER_TOKEN': 'test-only-secret'}
    def tearDown(self): self.temp.cleanup()
    def run_prepare(self, response):
        with patch.dict(os.environ, self.config), httpx.Client(transport=httpx.MockTransport(lambda req: response)) as client:
            return m.prepare(client)
    def test_original_bytes_and_checksums(self):
        graph = self.run_prepare(httpx.Response(200, content=self.data))
        self.assertEqual(graph.read_bytes(), self.data)
    def test_redirect_does_not_forward_secret(self):
        seen = []
        def handler(req):
            seen.append(req)
            return httpx.Response(302, headers={'Location': 'https://other.example/snapshot'})
        with patch.dict(os.environ, self.config), httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(ValueError): m.prepare(client)
        self.assertEqual(len(seen), 1)
        self.assertFalse(list(Path(self.temp.name).iterdir()))
    def test_invalid_download_never_installs(self):
        with self.assertRaises(ValueError): self.run_prepare(httpx.Response(200, content=self.data+b'changed'))
        self.assertFalse(list(Path(self.temp.name).iterdir()))
    def test_cached_mismatch_does_not_replace(self):
        graph = Path(self.temp.name)/'fixture.db'; graph.write_bytes(self.data+b'changed')
        with self.assertRaises(ValueError): self.run_prepare(httpx.Response(200, content=self.data))
        self.assertEqual(graph.read_bytes(), self.data+b'changed')
    def test_size_limit(self):
        self.config['CBM_GRAPH_MAX_BYTES'] = '10'
        with self.assertRaises(ValueError): self.run_prepare(httpx.Response(200, content=self.data))
    def test_project_path_rejected(self):
        self.config['CBM_PROJECT'] = '../outside'
        with self.assertRaises(ValueError): self.run_prepare(httpx.Response(200, content=self.data))

if __name__ == '__main__': unittest.main()
