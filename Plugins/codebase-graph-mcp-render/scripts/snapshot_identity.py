"""Print only checksums and size. Input: python scripts/snapshot_identity.py PATH."""
import hashlib
from pathlib import Path
import json
import sys
p = Path(sys.argv[1])
sha = hashlib.sha256()
blob = hashlib.sha1(b'blob ' + str(p.stat().st_size).encode() + b'\0')
with p.open('rb') as f:
    for chunk in iter(lambda: f.read(1024 * 1024), b''):
        sha.update(chunk); blob.update(chunk)
print(json.dumps({'size_bytes': p.stat().st_size, 'sha256': sha.hexdigest(), 'blob_sha': blob.hexdigest()}))
