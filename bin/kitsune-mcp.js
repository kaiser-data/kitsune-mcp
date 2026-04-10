#!/usr/bin/env node
'use strict';

// Thin npm wrapper — delegates to the Python package via uvx (preferred) or pip fallback.
// uvx installs kitsune-mcp in an isolated env on first run and caches it.

const { spawn } = require('child_process');
const args = process.argv.slice(2);

function run(cmd, cmdArgs) {
  const proc = spawn(cmd, cmdArgs, { stdio: 'inherit', env: process.env });
  proc.on('close', (code) => process.exit(code ?? 0));
  return proc;
}

// Try uvx first (uv's tool runner — fastest, isolated, no pip install needed)
const proc = run('uvx', ['kitsune-mcp@latest', ...args]);

proc.on('error', () => {
  // uvx not available — fall back to kitsune-mcp on PATH (pip-installed)
  const fallback = run('kitsune-mcp', args);

  fallback.on('error', () => {
    process.stderr.write(
      'kitsune-mcp: could not start server.\n' +
      '  Option 1 (recommended): install uv  →  https://docs.astral.sh/uv/\n' +
      '  Option 2: pip install kitsune-mcp\n'
    );
    process.exit(1);
  });
});
