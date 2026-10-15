#!/usr/bin/env sh
# Start FalkorDB on :6379 without Docker, using the redis-server + falkordb.so bundled in the falkordblite wheel.
# With Docker, prefer: docker compose up falkordb   (also gives FalkorDB Browser on :3000)
set -e
BIN=$(python -c "import redislite, pathlib; print(pathlib.Path(redislite.__file__).parent / 'bin')")
mkdir -p .falkordb
exec "$BIN/redis-server" --port "${FALKORDB_PORT:-6379}" --dir .falkordb --loadmodule "$BIN/falkordb.so"
