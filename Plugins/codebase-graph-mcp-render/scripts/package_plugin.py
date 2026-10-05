"""Build a skills-only archive. It does not create or connect a remote MCP server."""
from pathlib import Path
import json
import sys
import zipfile
root = Path(__file__).resolve().parents[1]
source = root / 'plugin-template'
manifest = json.loads((source / 'plugin.json').read_text())
output = Path(sys.argv[1]).resolve()
if source == output or source in output.parents:
    raise SystemExit('Write the archive outside plugin-template')
with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
    for p in sorted(source.rglob('*')):
        if p.is_file():
            archive.write(p, str(Path(manifest['name']) / p.relative_to(source)))
print('Skills-only plugin archive prepared; separately connect the engine')
