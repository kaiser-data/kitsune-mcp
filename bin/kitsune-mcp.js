#!/usr/bin/env node
'use strict';

// Thin npm wrapper — delegates to the Python package via uvx (preferred) or pip fallback.
// uvx installs kitsune-mcp in an isolated env on first run and caches it.

const { spawn } = require('child_process');
const args = process.argv.slice(2);

// Set for the fallback child. If `kitsune-mcp` on PATH is this npm wrapper
// again (not the pip-installed server), it would otherwise relaunch itself
// forever.
const SHIM_ENV = 'KITSUNE_MCP_NPM_SHIM';

function fail() {
  process.stderr.write(
    'kitsune-mcp: could not start server.\n' +
    '  Option 1 (recommended): install uv  →  https://docs.astral.sh/uv/\n' +
    '  Option 2: pip install kitsune-mcp\n'
  );
  process.exit(1);
}

// Runs cmd; calls onMissing() if it cannot be spawned (e.g. not installed).
// A failed spawn also emits 'close' (code -2), which used to exit the wrapper
// before the fallback could run — so 'close' is ignored after an 'error'.
function run(cmd, cmdArgs, env, onMissing) {
  let spawnFailed = false;
  const proc = spawn(cmd, cmdArgs, { stdio: 'inherit', env });
  proc.on('error', () => {
    spawnFailed = true;
    onMissing();
  });
  proc.on('close', (code) => {
    if (!spawnFailed) process.exit(code ?? 0);
  });
}

if (process.env[SHIM_ENV]) {
  // We are the fallback target ourselves: no real server on PATH.
  fail();
} else {
  // Try uvx first (uv's tool runner — fastest, isolated, no pip install needed)
  run('uvx', ['kitsune-mcp@latest', ...args], process.env, () => {
    // uvx not available — fall back to kitsune-mcp on PATH (pip-installed)
    run('kitsune-mcp', args, { ...process.env, [SHIM_ENV]: '1' }, fail);
  });
}
