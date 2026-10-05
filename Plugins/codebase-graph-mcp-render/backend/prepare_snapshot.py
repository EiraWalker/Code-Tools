"""Fetch an unchanged snapshot from one HTTPS source; never log its URL or token."""
import hashlib
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlsplit
import httpx


def prepare(client=None, config=None):
    config = os.environ if config is None else config
    project = config['CBM_PROJECT']
    if not project or project in {'.', '..'} or any(c in project for c in '/\\\0'):
        raise ValueError('Invalid project filename stem')
    sha256 = config['CBM_GRAPH_SHA256']
    blob_sha = config['CBM_GRAPH_BLOB_SHA']
    if not re.fullmatch('[a-f0-9]{64}', sha256) or not re.fullmatch('[a-f0-9]{40}', blob_sha):
        raise ValueError('Expected hexadecimal snapshot checksums')
    cache = Path(config['CBM_CACHE_DIR'])
    cache.mkdir(parents=True, exist_ok=True)
    graph = cache / (project + '.db')
    if any(p != graph for p in cache.glob('*.db')):
        raise ValueError('Cache must contain only the configured project')
    maximum = int(config.get('CBM_GRAPH_MAX_BYTES', '268435456'))
    def validate(path):
        size = path.stat().st_size
        if size > maximum:
            raise ValueError('Snapshot exceeds configured size limit')
        digest = hashlib.sha256()
        blob = hashlib.sha1(b'blob ' + str(size).encode() + b'\0')
        with path.open('rb') as f:
            if f.read(16) != b'SQLite format 3\0':
                raise ValueError('Expected original SQLite snapshot')
            f.seek(0)
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                digest.update(chunk); blob.update(chunk)
        if digest.hexdigest() != sha256 or blob.hexdigest() != blob_sha:
            raise ValueError('Snapshot checksum mismatch')
    if graph.exists():
        validate(graph)
        return graph
    url = config['CBM_GRAPH_URL']
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Use an HTTPS source without embedded credentials')
    headers = {'Accept': 'application/vnd.github.raw+json'}
    token = config.get('CBM_GRAPH_BEARER_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    own_client = client is None
    client = client or httpx.Client(timeout=120, follow_redirects=False)
    path = None
    try:
        with tempfile.NamedTemporaryFile(dir=cache, prefix='.incoming-', delete=False) as f:
            path = Path(f.name)
            with client.stream('GET', url, headers=headers, follow_redirects=False) as response:
                if response.status_code != 200:
                    raise ValueError('Snapshot source did not return HTTP 200; redirects are refused')
                size = 0
                for chunk in response.iter_bytes(1024 * 1024):
                    size += len(chunk)
                    if size > maximum:
                        raise ValueError('Snapshot exceeds configured size limit')
                    f.write(chunk)
        validate(path)
        path.replace(graph)
        graph.chmod(0o600)
        return graph
    finally:
        if path is not None:
            path.unlink(missing_ok=True)
        if own_client:
            client.close()


if __name__ == '__main__':
    try:
        from index_catalog import load_indexes
        for config in load_indexes().values():
            prepare(config=config)
        print('Original graph snapshot integrity verified')
    except Exception as error:
        # HTTP exceptions can contain credential-bearing URLs. Do not print them.
        print('Snapshot preparation failed (' + type(error).__name__ + '); check private configuration', file=sys.stderr)
        sys.exit(1)
