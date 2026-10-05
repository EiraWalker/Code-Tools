#!/usr/bin/env bash
set -euo pipefail

service_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source_dir="${service_dir}/.cbm-upstream"
upstream_commit=8972ea69c6ad94b1ef1d4ffbf0a92d78d2db1798

python -m pip install --no-cache-dir -r "${service_dir}/requirements.lock"

if [[ ! -d "${source_dir}/.git" ]]; then
  git clone --depth 1 --branch v0.11.0 \
    https://github.com/DeusData/codebase-memory-mcp.git "${source_dir}"
fi
test "$(git -C "${source_dir}" rev-parse HEAD)" = "${upstream_commit}"
git -C "${source_dir}" diff --exit-code --quiet
make -C "${source_dir}" -f Makefile.cbm -j1 cbm \
  "MAIN_SRC=${service_dir}/native/standalone_main.c"
strip "${source_dir}/build/c/codebase-memory-mcp"
"${source_dir}/build/c/codebase-memory-mcp" --version

python "${service_dir}/prepare_snapshot.py"
