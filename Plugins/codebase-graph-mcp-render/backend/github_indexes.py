"""Authenticated owner-controlled GitHub snapshot registration and cached refresh.

Only original .db bytes are consumed. No source checkout, indexing, or SQL queries.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
from urllib.parse import quote, unquote, urlsplit

import httpx
from index_catalog import validate_config
from snapshot_cache import validate_graph


class GitHubIndexError(ValueError):
    """Safe, actionable text; never include HTTP exceptions or credential URLs."""


def parse_link(url, graph_path=None, ref=None):
    if not isinstance(url, str):
        raise GitHubIndexError('github_url must be an HTTPS GitHub link.')
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc != 'github.com' or parsed.query or parsed.fragment:
        raise GitHubIndexError('Provide an HTTPS github.com repository or blob/tree link without credentials or query parameters.')
    parts = unquote(parsed.path).strip('/').split('/')
    if len(parts) < 2 or not all(re.fullmatch(r'[A-Za-z0-9_.-]+', p) and p not in {'.', '..'} for p in parts[:2]):
        raise GitHubIndexError('Invalid GitHub repository link.')
    repository = '/'.join(parts[:2]).removesuffix('.git')
    suffix = parts[2:]
    if suffix and (suffix[0] not in {'blob', 'tree'} or len(suffix) < 2):
        raise GitHubIndexError('Use a repository root, blob link, or tree link.')
    if graph_path is not None and (not isinstance(graph_path, str) or graph_path.startswith('/') or any(p in {'', '.', '..'} for p in graph_path.split('/'))):
        raise GitHubIndexError('graph_path must be a relative repository path.')
    if ref is not None and (not isinstance(ref, str) or not ref or len(ref) > 256 or any(c in ref for c in '\0\r\n')):
        raise GitHubIndexError('Invalid Git reference.')
    return repository, suffix, graph_path, ref


class GitHubSource:
    def __init__(self, client=None):
        self.client = client or httpx.Client(timeout=httpx.Timeout(60, connect=15), follow_redirects=False)
        self.headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
        if os.environ.get('CBM_GITHUB_TOKEN'):
            self.headers['Authorization'] = 'Bearer ' + os.environ['CBM_GITHUB_TOKEN']

    def api(self, repository, path, params=None):
        url = 'https://api.github.com/repos/' + repository + '/' + path
        try:
            with self.client.stream('GET', url.rstrip('/'), params=params, headers=self.headers) as response:
                if response.status_code != 200:
                    raise GitHubIndexError('GitHub metadata is unavailable (HTTP ' + str(response.status_code) + '). For a private repository, configure backend CBM_GITHUB_TOKEN with Contents read permission.')
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 8 * 1024 * 1024:
                        raise GitHubIndexError('Repository metadata is too large; provide graph_path explicitly.')
                return json.loads(body)
        except (httpx.HTTPError, json.JSONDecodeError):
            raise GitHubIndexError('GitHub metadata request failed; retry without sharing credentials in chat.') from None

    def locate(self, arguments):
        repo, suffix, path, ref = parse_link(arguments.get('github_url', ''), arguments.get('graph_path'), arguments.get('ref'))
        default = self.api(repo, '')['default_branch']
        prefix = None
        if suffix:
            remainder = '/'.join(suffix[1:])
            if ref:
                if not (remainder == ref or remainder.startswith(ref + '/')):
                    raise GitHubIndexError('The explicit ref must match the blob/tree link.')
                linked_path = remainder[len(ref):].lstrip('/')
            else:
                # Default branches containing slashes are unambiguous; other slash refs require ref.
                ref = default if remainder == default or remainder.startswith(default + '/') else suffix[1]
                linked_path = remainder[len(ref):].lstrip('/')
            if suffix[0] == 'blob':
                path = path or linked_path
            else:
                prefix = linked_path
        ref = ref or default
        commit = self.api(repo, 'commits/' + quote(ref, safe=''))['sha']
        if not path:
            tree = self.api(repo, 'git/trees/' + commit, {'recursive': '1'})
            paths = sorted(item['path'] for item in tree.get('tree', []) if item['type'] == 'blob' and item['path'].endswith('.db') and (not prefix or item['path'].startswith(prefix.rstrip('/') + '/')))
            if tree.get('truncated') or len(paths) != 1:
                return {'status': 'choose_graph' if paths or tree.get('truncated') else 'index_required', 'repository': repo,
                        'ref': ref, 'candidates': paths[:50], 'truncated': bool(tree.get('truncated')) or len(paths) > 50,
                        'message': 'Supply graph_path for one original codebase-memory-mcp .db snapshot.' if paths or tree.get('truncated') else 'No .db snapshot found. Generate/publish an index with the existing repository workflow first; this reader does not index source code.'}
            path = paths[0]
        if not path.endswith('.db'):
            raise GitHubIndexError('Choose an original uncompressed .db graph snapshot.')
        # Revalidate paths obtained from links too.
        parse_link('https://github.com/' + repo, path, ref)
        metadata = self.api(repo, 'contents/' + quote(path, safe='/'), {'ref': commit})
        if metadata.get('type') != 'file' or not re.fullmatch('[a-f0-9]{40}', metadata.get('sha', '')):
            raise GitHubIndexError('The selected path is not a GitHub graph file.')
        return {'repository': repo, 'ref': ref, 'path': path, 'commit': commit, 'metadata': metadata}

    def download(self, source, directory, maximum):
        metadata = source['metadata']
        size = metadata.get('size')
        if type(size) is not int or not 16 <= size <= maximum:
            raise GitHubIndexError('Snapshot size is outside the configured limit; Git LFS pointers are not graph snapshots.')
        url = metadata.get('download_url') or ''
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.netloc != 'raw.githubusercontent.com' or not parsed.path.startswith('/' + source['repository'] + '/'):
            raise GitHubIndexError('GitHub did not return an allowed raw snapshot download URL.')
        # Signed GitHub raw URLs authorize downloads; never forward the API token to another origin.
        incoming = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, prefix='.github-', delete=False) as output:
                incoming = Path(output.name)
                digest = hashlib.sha256()
                received = 0
                with self.client.stream('GET', url, headers={'Accept': 'application/octet-stream'}) as response:
                    if response.status_code != 200:
                        raise GitHubIndexError('GitHub snapshot download failed (HTTP ' + str(response.status_code) + '). Retry to obtain fresh metadata.')
                    for chunk in response.iter_bytes(1024 * 1024):
                        received += len(chunk)
                        if received > size or received > maximum:
                            raise GitHubIndexError('Snapshot download exceeded its declared size.')
                        digest.update(chunk); output.write(chunk)
                output.flush(); os.fsync(output.fileno())
            identity = {'sha256': digest.hexdigest(), 'blob_sha': metadata['sha'], 'size_bytes': size,
                        'source_commit': source['commit']}
            if received != size:
                raise GitHubIndexError('Snapshot download was incomplete.')
            validate_graph(incoming, identity['sha256'], identity['blob_sha'], maximum)
            return incoming, identity
        except (httpx.HTTPError, ValueError, OSError) as error:
            if incoming:
                incoming.unlink(missing_ok=True)
            if isinstance(error, GitHubIndexError):
                raise
            raise GitHubIndexError('Snapshot failed download or integrity validation; previous cache retained.') from None


class GitHubIndexes:
    def __init__(self, catalog, cache_root, engine_factory, source=None):
        self.catalog = catalog
        self.root = Path(cache_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.pointer = self.root / 'registered-indexes.json'
        self.factory = engine_factory
        self.source = source or GitHubSource()
        self.lock = threading.RLock()
        self.checked = {}
        self.errors = {}
        self.records = {}
        self.interval = max(30, int(os.environ.get('CBM_GITHUB_CHECK_SECONDS', '300')))
        if self.pointer.exists():
            records = json.loads(self.pointer.read_text())
            if not isinstance(records, dict) or len(records) > 32:
                raise ValueError('Invalid registered index catalog')
            for project, record in records.items():
                if project in catalog.engines:
                    raise ValueError('Configured and registered project names collide')
                config = self.config(record)
                validate_config(config)
                engine = engine_factory(config)
                engine.validate_candidate(engine.snapshots.active)
                catalog.engines[project] = engine
                self.records[project] = record
            if len(catalog.engines) > 32:
                raise ValueError('Index catalog exceeds configured limit')

    def config(self, record):
        project = record['project']
        if not isinstance(project, str):
            raise GitHubIndexError('project must be the original graph project name.')
        return {'CBM_PROJECT': project, 'CBM_SOURCE_REPOSITORY': record['repository'],
                'CBM_GRAPH_PATH': record['path'], 'CBM_GRAPH_SHA256': record['sha256'],
                'CBM_GRAPH_BLOB_SHA': record['blob_sha'], 'CBM_GRAPH_MAX_BYTES': str(record['maximum']),
                'CBM_CACHE_DIR': str(self.root / 'registered' / hashlib.sha256(project.encode()).hexdigest())}

    def persist(self, records):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, prefix='.catalog-', mode='w', delete=False) as output:
                temporary = Path(output.name)
                json.dump(records, output); output.flush(); os.fsync(output.fileno())
            temporary.chmod(0o600)
            temporary.replace(self.pointer)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

    def add(self, arguments):
        with self.lock:
            source = self.source.locate(arguments)
            if 'status' in source:
                return source
            project = arguments.get('project') or Path(source['path']).stem
            record = {'project': project, 'repository': source['repository'], 'path': source['path'],
                      'ref': source['ref'], 'sha256': 'a' * 64, 'blob_sha': source['metadata']['sha'],
                      'maximum': int(os.environ.get('CBM_GRAPH_MAX_BYTES', '268435456'))}
            config = self.config(record)
            validate_config(config)
            if project in self.catalog.engines:
                engine = self.catalog.engines[project]
                if engine.config['CBM_SOURCE_REPOSITORY'].lower() != source['repository'].lower() or engine.config['CBM_GRAPH_PATH'] != source['path']:
                    raise GitHubIndexError('That original project name is already registered for another source; graph aliases are not supported.')
                if project in self.records and self.records[project]['ref'] != source['ref']:
                    raise GitHubIndexError('This original project is already registered for a different ref; choose the registered ref.')
                self.refresh(project, force=True)
                return {'status': 'already_registered', 'project': project, 'graph_snapshot': engine.call('list_projects', {'format': 'json'}).structuredContent['graph_snapshot'], **({'refresh_warning': self.errors[project]} if project in self.errors else {})}
            if len(self.catalog.engines) >= 32:
                raise GitHubIndexError('The index catalog is full (32 projects).')
            directory = Path(config['CBM_CACHE_DIR']); directory.mkdir(parents=True, exist_ok=True)
            incoming, identity = self.source.download(source, directory, record['maximum'])
            graph = directory / (project + '.db')
            try:
                # Keep the downloaded original bytes; never rewrite the graph's internal project identity.
                if graph.exists():
                    graph.unlink()
                incoming.replace(graph); graph.chmod(0o600)
                record.update(sha256=identity['sha256'], blob_sha=identity['blob_sha'])
                engine = self.factory(self.config(record))
                engine.validate_candidate(engine.snapshots.active)
                engine.snapshots.check(identity, 0, 0)
                provenance = engine.call('list_projects', {'format': 'json'}).structuredContent['graph_snapshot']
                records = {**self.records, project: record}
                self.persist(records)
                self.records = records
                self.catalog.engines[project] = engine
                self.checked[project] = time.monotonic()
                return {'status': 'registered', 'project': project,
                        'graph_snapshot': provenance}
            except (ValueError, OSError, subprocess.SubprocessError) as error:
                graph.unlink(missing_ok=True)
                (directory / 'active-snapshot.json').unlink(missing_ok=True)
                if isinstance(error, GitHubIndexError):
                    raise
                raise GitHubIndexError('Native validation rejected the graph. Use a compatible snapshot and its original project name (project may override the file stem).') from None
            finally:
                incoming.unlink(missing_ok=True)

    def refresh(self, project, force=False):
        if project not in self.records:
            return
        with self.lock:
            if not force and time.monotonic() - self.checked.get(project, 0) < self.interval:
                return
            self.checked[project] = time.monotonic()
            engine = self.catalog.engines[project]
            record = self.records[project]
            incoming = None
            try:
                source = self.source.locate({'github_url': 'https://github.com/' + record['repository'],
                                             'graph_path': record['path'], 'ref': record['ref']})
                if source['metadata']['sha'] != engine.snapshots.active.blob_sha:
                    incoming, identity = self.source.download(source, engine.cache, record['maximum'])
                    engine.snapshots.install(incoming, identity, engine.snapshots.active.run_number + 1, 1,
                                             engine.validate_candidate)
                self.errors.pop(project, None)
            except (ValueError, KeyError, OSError, httpx.HTTPError, subprocess.SubprocessError):
                self.errors[project] = 'Remote refresh failed; serving the last verified cached snapshot.'
                print('GitHub index refresh failed; verified cache retained', flush=True)
            finally:
                if incoming:
                    incoming.unlink(missing_ok=True)

    def result(self, arguments):
        try:
            payload = self.add(arguments)
            return False, payload
        except (GitHubIndexError, ValueError, KeyError, TypeError, OSError, httpx.HTTPError, subprocess.SubprocessError) as error:
            message = str(error) if isinstance(error, GitHubIndexError) else 'Index registration failed; inspect private configuration and retry.'
            return True, {'error': message}
