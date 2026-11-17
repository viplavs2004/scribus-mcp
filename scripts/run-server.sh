#!/usr/bin/env bash
# run-server.sh
# Start the local scribus-mcp server from this checkout.
#
# Default is Streamable HTTP on 127.0.0.1:8765 (endpoint /mcp).
# With no arguments the script uses that default. Any other arguments
# are passed straight through to scribus-mcp.
#
# Usage:
#   ./scripts/run-server.sh
#   ./scripts/run-server.sh --http :9000
#   ./scripts/run-server.sh --stdio
#   SCRIBUS_BIN=/usr/bin/scribus ./scripts/run-server.sh
#
# --stdio drops the HTTP default so the process speaks MCP on stdin/stdout
# (the transport an MCP client spawns). Further flags still pass through:
#   ./scripts/run-server.sh --stdio --scribus-bin /usr/bin/scribus

set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)

if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required to run scribus-mcp. Install it from https://docs.astral.sh/uv/" >&2
    exit 1
fi

args=("$@")
if [[ ${#args[@]} -eq 0 ]]; then
    args=(--http 127.0.0.1:8765)
elif [[ "${args[0]}" == "-h" || "${args[0]}" == "--help" ]]; then
    sed -n '2,18p' "$0"
    exit 0
elif [[ "${args[0]}" == "--stdio" ]]; then
    args=("${args[@]:1}")
fi

cd "$root"
exec uv run scribus-mcp "${args[@]}"
