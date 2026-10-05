"""Catalog boundaries and native two-cache integration (optional authorized fixture)."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from index_catalog import load_indexes
from server import Catalog, Engine, ProjectSelectionError, create_app
from snapshot_sync import PublisherAuth
from mcp import types
from starlette.testclient import TestClient


def record(project):
    return {'project': project, 'repository': 'owner/graphs', 'path': 'graphs/' + project + '.db',
            'sha256': 'a' * 64, 'blob_sha': 'b' * 40, 'url_env': 'FIXTURE_URL',
            'publisher': {'repository': 'owner/source-' + project, 'repository_id': '42'}}


class CatalogConfigTests(unittest.TestCase):
    def setUp(self):
        self.env = {'CBM_CACHE_DIR': '/tmp/catalog-test', 'FIXTURE_URL': 'https://example.test/private',
                    'CBM_INDEXES_JSON': json.dumps([record('alpha'), record('beta')]),
                    'CBM_SYNC_REPOSITORY': 'ignored/legacy', 'CBM_SYNC_REPOSITORY_ID': '999'}

    def test_separate_cache_and_publisher_without_legacy_policy_leak(self):
        configs = load_indexes(self.env)
        self.assertNotEqual(configs['alpha']['CBM_CACHE_DIR'], configs['beta']['CBM_CACHE_DIR'])
        alpha = PublisherAuth('https://reader.example', configs['alpha'])
        beta = PublisherAuth('https://reader.example', configs['beta'])
        self.assertEqual(alpha.repository, 'owner/source-alpha')
        self.assertEqual(beta.repository, 'owner/source-beta')
        self.assertEqual(alpha.repository_id, '42')
        self.assertEqual(alpha.audience, beta.audience)

    def test_duplicate_path_escape_and_unknown_fields_rejected(self):
        for records in ([record('alpha'), record('alpha')], [record('../escape')],
                        [{**record('alpha'), 'url': 'https://query-client.example'}], [],
                        [{**record('alpha'), 'publisher': {'repository': 'owner/source'}}]):
            with self.subTest(records=records), self.assertRaises(ValueError):
                load_indexes({**self.env, 'CBM_INDEXES_JSON': json.dumps(records)})

    def test_legacy_configuration_preserves_existing_cache_directory(self):
        legacy = {'CBM_PROJECT': 'alpha', 'CBM_CACHE_DIR': '/tmp/existing-cache',
                  'CBM_SOURCE_REPOSITORY': 'owner/graphs', 'CBM_GRAPH_PATH': 'graphs/alpha.db',
                  'CBM_GRAPH_SHA256': 'a' * 64, 'CBM_GRAPH_BLOB_SHA': 'b' * 40}
        self.assertEqual(load_indexes(legacy)['alpha'], legacy)


class CatalogRoutingTests(unittest.TestCase):
    def setUp(self):
        def engine(config):
            result = Mock(project=config['CBM_PROJECT'], config=config, tools=[])
            project = result.project
            snapshot = {'project': project, 'sha256': project + '-hash'}
            result.call.side_effect = lambda name, args: types.CallToolResult(
                content=[types.TextContent(type='text', text='native fixture')],
                structuredContent={'projects': [{'name': project}], 'graph_snapshot': snapshot})
            return result
        self.configs = {name: {'CBM_PROJECT': name} for name in ('alpha', 'beta')}
        self.catalog = Catalog(self.configs, engine)

    def test_selection_never_defaults_to_first_with_multiple_indexes(self):
        for project in (None, '', 'unregistered', ['alpha']):
            with self.assertRaises(ProjectSelectionError): self.catalog.select(project)
        args = {'project': 'beta', 'query': 'MATCH (n) RETURN count(n)'}
        self.catalog.call('query_graph', args)
        self.catalog.engines['alpha'].call.assert_not_called()
        self.catalog.engines['beta'].call.assert_called_once_with('query_graph', args)

    def test_paging_and_provenance_belong_to_selected_project(self):
        result = self.catalog.call('list_projects', {'offset': 1, 'limit': 1, 'detail': 'stats'})
        payload = result.structuredContent
        self.assertEqual((payload['total'], payload['returned'], payload['has_more']), (2, 1, False))
        self.assertEqual(payload['projects'][0]['name'], 'beta')
        self.assertEqual(payload['projects'][0]['graph_snapshot']['sha256'], 'beta-hash')
        self.assertEqual(list(payload['graph_snapshots']), ['beta'])
        self.catalog.engines['alpha'].call.assert_not_called()
        empty = self.catalog.call('list_projects', {'offset': 100}).structuredContent
        self.assertEqual(empty['returned'], 0)
        self.assertFalse(empty['has_more'])

    def test_native_error_is_not_converted_to_successful_catalog(self):
        failure = types.CallToolResult(isError=True, content=[types.TextContent(type='text', text='native error')])
        self.catalog.engines['alpha'].call.side_effect = None
        self.catalog.engines['alpha'].call.return_value = failure
        self.assertEqual(self.catalog.call('list_projects', {}), failure)

    def test_sync_selects_and_authenticates_target_before_touching_cache(self):
        for engine in self.catalog.engines.values():
            engine.config['CBM_SYNC_REPOSITORY'] = 'owner/source'
            engine.snapshots.maximum = 1024
        auths = [Mock(), Mock()]
        claims = {'run_number': '3', 'run_attempt': '1', 'sha': 'c' * 40}
        auths[0].verify.side_effect = ValueError('wrong publisher')
        auths[1].verify.return_value = claims
        self.catalog.engines['beta'].snapshots.check.return_value = 'unchanged'
        env = {'CBM_SERVICE_TOKEN': 'x' * 32, 'CBM_PUBLIC_ORIGIN': 'https://reader.example', 'CBM_CACHE_DIR': '/tmp/fixture'}
        with patch.dict(os.environ, env), patch('server.load_indexes', return_value=self.configs), \
             patch('server.Catalog', return_value=self.catalog), patch('server.PublisherAuth', side_effect=auths), patch('server.GitHubIndexes', return_value=None), \
             TestClient(create_app()) as client:
            identity = {'project': 'beta', 'sha256': 'a' * 64, 'blob_sha': 'b' * 40,
                        'size_bytes': 32, 'source_commit': 'c' * 40}
            self.assertEqual(client.post('/snapshot-sync', json=identity).status_code, 422)
            self.assertEqual(client.post('/snapshot-sync', json=identity, headers={
                'X-Snapshot-Project': 'alpha', 'Authorization': 'Bearer fixture'}).status_code, 401)
            self.assertEqual(client.post('/snapshot-sync', json={**identity, 'project': 'alpha'}, headers={
                'X-Snapshot-Project': 'beta', 'Authorization': 'Bearer fixture'}).status_code, 422)
            response = client.post('/snapshot-sync', json=identity, headers={
                'X-Snapshot-Project': 'beta', 'Authorization': 'Bearer fixture'})
            self.assertEqual(response.json()['status'], 'unchanged')
        self.catalog.engines['alpha'].snapshots.check.assert_not_called()
        self.catalog.engines['beta'].snapshots.check.assert_called_once()


@unittest.skipUnless(os.environ.get('CBM_TEST_BINARY'), 'Requires the native snapshot binary')
class NativeCatalogTests(unittest.TestCase):
    def test_two_synthetic_graphs_use_native_queries_and_keep_original_bytes(self):
        from fixture_graph import make_graph
        with tempfile.TemporaryDirectory() as tmp:
            records = []
            data = {}
            for name in ('fixture-alpha', 'fixture-beta'):
                path = Path(tmp) / (name + '.db')
                make_graph(path, name)
                data[name] = path.read_bytes()
                records.append({**record(name), 'sha256': hashlib.sha256(data[name]).hexdigest(),
                    'blob_sha': hashlib.sha1(b'blob ' + str(len(data[name])).encode() + b'\0' + data[name]).hexdigest()})
            configs = load_indexes({'CBM_CACHE_DIR': tmp, 'FIXTURE_URL': 'https://unused.example',
                                    'CBM_INDEXES_JSON': json.dumps(records)})
            for name, config in configs.items():
                directory = Path(config['CBM_CACHE_DIR']); directory.mkdir(parents=True)
                (directory / (name + '.db')).write_bytes(data[name])
            with patch.dict(os.environ, {'CBM_BINARY': os.environ['CBM_TEST_BINARY']}):
                catalog = Catalog(configs)
                projects = catalog.call('list_projects', {'detail': 'stats', 'format': 'json'}).structuredContent
                self.assertEqual([p['name'] for p in projects['projects']], ['fixture-alpha', 'fixture-beta'])
                for project in configs:
                    result = catalog.call('query_graph', {'project': project, 'query': 'MATCH (n) RETURN count(n) AS nodes', 'format': 'json'})
                    self.assertFalse(result.isError)
                    self.assertEqual(result.structuredContent['graph_snapshot']['project'], project)
                    self.assertEqual(int(result.structuredContent['rows'][0][0]), 3)
                for project, config in configs.items():
                    self.assertEqual((Path(config['CBM_CACHE_DIR']) / (project + '.db')).read_bytes(), data[project])


if __name__ == '__main__': unittest.main()
