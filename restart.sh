#!/bin/bash
# Restart the smithery-lattice MCP server

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVER="$SCRIPT_DIR/server.py"

# Kill existing instance
if pgrep -f "$SERVER" > /dev/null; then
    echo "Stopping existing server..."
    pkill -f "$SERVER"
    sleep 1
fi

echo "Starting smithery-lattice..."
python3 "$SERVER" &
echo "Server PID: $!"
