import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from github_indexes import GitHubSource, GitHubIndexes, GitHubIndexError, parse_link
from server import Catalog, Engine
from fixture_graph import make_graph


def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


class GitHubSourceTests(unittest.TestCase):
    def test_rejects_credentials_other_hosts_and_path_traversal(self):
        for url in ('http://github.com/owner/repo', 'https://github.com.evil.test/owner/repo',
                    'https://token@github.com/owner/repo', 'https://github.com/owner/repo?token=secret'):
            with self.assertRaises(GitHubIndexError): parse_link(url)
        for path in ('../graph.db', '/graph.db', 'graphs/../graph.db'):
            with self.assertRaises(GitHubIndexError): parse_link('https://github.com/owner/repo', path)

    def test_multiple_graphs_returns_candidates_without_downloading(self):
        seen = []
        def handler(request):
            seen.append(request)
            if request.url.path == '/repos/owner/repo': return httpx.Response(200, json={'default_branch': 'main'})
            if '/commits/' in request.url.path: return httpx.Response(200, json={'sha': 'c' * 40})
            return httpx.Response(200, json={'tree': [{'type': 'blob', 'path': p} for p in ('one.db', 'two.db')], 'truncated': False})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            result = GitHubSource(client).locate({'github_url': 'https://github.com/owner/repo'})
        self.assertEqual(result['status'], 'choose_graph')
        self.assertEqual(result['candidates'], ['one.db', 'two.db'])
        self.assertTrue(all(r.url.host == 'api.github.com' for r in seen))

    def test_default_ref_with_slash_and_pinned_metadata_commit(self):
        seen = []
        def handler(request):
            seen.append(request)
            if request.url.path == '/repos/owner/repo': return httpx.Response(200, json={'default_branch': 'codex/main'})
            if '/commits/' in request.url.path: return httpx.Response(200, json={'sha': 'c' * 40})
            return httpx.Response(200, json={'type': 'file', 'sha': 'a' * 40})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            source = GitHubSource(client).locate({'github_url': 'https://github.com/owner/repo/blob/codex/main/graphs/fixture.db'})
        self.assertEqual((source['ref'], source['path']), ('codex/main', 'graphs/fixture.db'))
        self.assertEqual(seen[-1].url.params['ref'], 'c' * 40)

    def test_api_token_never_follows_raw_download_or_redirect(self):
        data = b'SQLite format 3\0synthetic-transfer-fixture'
        requests = []
        def handler(request):
            requests.append(request)
            if request.url.host == 'api.github.com': return httpx.Response(200, json={})
            return httpx.Response(302, headers={'Location': 'https://evil.example/graph'})
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'CBM_GITHUB_TOKEN': 'fixture-api-token'}), httpx.Client(transport=httpx.MockTransport(handler)) as client:
            source = GitHubSource(client)
            source.api('owner/repo', '')
            with self.assertRaises(GitHubIndexError):
                source.download({'repository': 'owner/repo', 'commit': 'c' * 40, 'metadata': {
                    'size': len(data), 'sha': blob(data), 'download_url': 'https://raw.githubusercontent.com/owner/repo/main/fixture.db'}}, tmp, 1024)
            self.assertFalse(list(Path(tmp).iterdir()))
        self.assertEqual(requests[0].headers['Authorization'], 'Bearer fixture-api-token')
        self.assertNotIn('Authorization', requests[1].headers)
        self.assertEqual(len(requests), 2)


@unittest.skipUnless(os.environ.get('CBM_TEST_BINARY'), 'Requires native snapshot binary')
class NativeRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = 'fixture-added'
        self.graph = self.root / 'source.db'
        make_graph(self.graph, self.project)
        self.data = self.graph.read_bytes()
        self.gets = []
        self.fail_download = False
        def handler(request):
            self.gets.append(request)
            if request.url.host == 'raw.githubusercontent.com':
                return httpx.Response(200, content=self.data + (b'bad' if self.fail_download else b''))
            if request.url.path == '/repos/owner/graphs': return httpx.Response(200, json={'default_branch': 'main'})
            if '/commits/' in request.url.path: return httpx.Response(200, json={'sha': 'c' * 40})
            return httpx.Response(200, json={'type': 'file', 'sha': blob(self.data), 'size': len(self.data),
                'download_url': 'https://raw.githubusercontent.com/owner/graphs/main/fixture-added.db'})
        self.client = httpx.Client(transport=httpx.MockTransport(handler))
        # Catalog initially contains an independently generated native fixture.
        cache = self.root / 'base'; cache.mkdir()
        make_graph(cache / 'fixture-base.db', 'fixture-base')
        base = (cache / 'fixture-base.db').read_bytes()
        config = {'CBM_PROJECT': 'fixture-base', 'CBM_CACHE_DIR': str(cache), 'CBM_SOURCE_REPOSITORY': 'owner/base',
            'CBM_GRAPH_PATH': 'fixture-base.db', 'CBM_GRAPH_SHA256': hashlib.sha256(base).hexdigest(), 'CBM_GRAPH_BLOB_SHA': blob(base)}
        self.env = patch.dict(os.environ, {'CBM_BINARY': os.environ['CBM_TEST_BINARY']}); self.env.start()
        self.configs = {'fixture-base': config}
        self.catalog = Catalog(self.configs)
        self.manager = GitHubIndexes(self.catalog, self.root / 'cache', Engine, GitHubSource(self.client))
        self.catalog.github = self.manager
        self.args = {'github_url': 'https://github.com/owner/graphs', 'graph_path': 'fixture-added.db'}

    def tearDown(self):
        self.env.stop(); self.client.close(); self.temp.cleanup()

    def downloads(self):
        return sum(r.url.host == 'raw.githubusercontent.com' for r in self.gets)

    def test_register_query_unchanged_refresh_and_restore_without_network(self):
        result = self.catalog.call('add_index', self.args)
        self.assertFalse(result.isError)
        self.assertEqual(result.structuredContent['status'], 'registered')
        self.assertEqual(self.downloads(), 1)
        for _ in range(2):
            self.manager.refresh(self.project, force=True)
            query = self.catalog.call('query_graph', {'project': self.project, 'query': 'MATCH (n) RETURN count(n) AS nodes', 'format': 'json'})
            self.assertFalse(query.isError)
            self.assertEqual(int(query.structuredContent['rows'][0][0]), 3)
        self.assertEqual(self.downloads(), 1)
        before = len(self.gets)
        restarted = Catalog(self.configs)
        GitHubIndexes(restarted, self.root / 'cache', Engine, GitHubSource(self.client))
        self.assertIn(self.project, restarted.engines)
        self.assertEqual(len(self.gets), before)
        self.assertEqual(self.manager.add(self.args)['status'], 'already_registered')
        self.assertEqual(self.downloads(), 1)

    def test_changed_blob_refreshes_and_corrupt_remote_keeps_previous_snapshot(self):
        self.manager.add(self.args)
        self.graph.unlink(); make_graph(self.graph, self.project, helper='changed')
        self.data = self.graph.read_bytes()
        self.manager.refresh(self.project, force=True)
        self.assertEqual(self.downloads(), 2)
        active = self.catalog.engines[self.project].snapshots.active
        self.assertEqual(active.blob_sha, blob(self.data))
        self.graph.unlink(); make_graph(self.graph, self.project, helper='corrupt')
        self.data = self.graph.read_bytes(); self.fail_download = True
        self.manager.refresh(self.project, force=True)
        self.assertEqual(self.catalog.engines[self.project].snapshots.active, active)
        query = self.catalog.call('search_graph', {'project': self.project, 'name_pattern': 'changed', 'format': 'json'})
        self.assertFalse(query.isError)
        self.assertIn('refresh_warning', query.structuredContent)
        self.assertIn('changed', query.content[0].text)

    def test_wrong_project_native_rejection_never_enters_catalog(self):
        result = self.catalog.call('add_index', {**self.args, 'project': 'wrong-name'})
        self.assertTrue(result.isError)
        self.assertNotIn('wrong-name', self.catalog.engines)
        self.assertFalse(self.manager.pointer.exists())


if __name__ == '__main__': unittest.main()
