#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
VENV_DIR="$SCRIPT_DIR/.venv"

if [ ! -f "$ENV_FILE" ]; then
  echo "Error: .env file not found at $ENV_FILE"
  exit 1
fi

SMITHERY_API_KEY=$(grep -E "^SMITHERY_API_KEY=" "$ENV_FILE" | cut -d= -f2-)

if [ -z "$SMITHERY_API_KEY" ]; then
  echo "Error: SMITHERY_API_KEY not found in .env"
  exit 1
fi

# Create venv if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment..."
  python3 -m venv "$VENV_DIR"
fi

# Install/update dependencies
echo "Installing dependencies..."
"$VENV_DIR/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt"

# Remove existing registration if present
claude mcp remove smithery-lattice 2>/dev/null

# Register using venv python
claude mcp add --scope user --transport stdio smithery-lattice \
  --env SMITHERY_API_KEY="$SMITHERY_API_KEY" \
  -- "$VENV_DIR/bin/python" "$SCRIPT_DIR/server.py"

echo "Done. Run 'claude mcp list' to verify."
