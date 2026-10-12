# Realtime MCP Test Report

Date: 2026-05-06

## Scope

Live runtime validation of `kitsune-mcp` as an MCP server using:

- one-shot stdio transport (`StdioTransport`)
- persistent stdio transport (`PersistentStdioTransport`)
- real tool calls (`status`, `search`, `shapeshift`, `list_directory`, `shiftback`)

## Results

| Test | Result | Latency | Notes |
|---|---|---:|---|
| cold stdio `status` | PASS | 793 ms | Returned full status payload and provider checks |
| cold stdio `search("filesystem")` | PASS | 1281 ms | Returned official filesystem server |
| persistent `status` x5 | PASS | avg 113 ms | First call 554 ms, then ~2-3 ms warm calls |
| `shapeshift("@modelcontextprotocol/server-filesystem")` | PASS | 8577 ms | Successfully registered `list_directory` |
| `list_directory("/Users/marty")` after shapeshift | PASS* | 8 ms | Correctly blocked by target server root restrictions |
| `shiftback(kill=True)` | PASS | 5007 ms | Returned to base form and released process |
| cold stdio `compare` | FAIL | 649 ms | `Unknown tool: compare` in current profile |

\* PASS for protocol/transport correctness; blocked behavior is expected until allowed roots are provided.

## What Works

- MCP runtime handshake and tool execution are functioning in real usage.
- Registry-backed discovery works (`search` found expected server).
- Shapeshift + shiftback lifecycle works in persistent sessions.
- Warm persistent calls are very fast (low milliseconds).
- Safety behavior works: filesystem access is denied outside configured roots.

## What Could Be Better

- **Tool profile consistency:** `compare` is unavailable in this runtime profile; if intended, expose it or document profile split more clearly.
- **Cold-start latency:** shapeshift to external servers can take several seconds due to registry lookups and install/startup path.
- **Noise in stdout/stderr:** high-volume HTTP logs can obscure user-facing outputs during realtime runs.
- **Process cleanup warning:** Python prints `RuntimeError: Event loop is closed` from subprocess cleanup on shutdown; behavior succeeds but logs look unhealthy.
- **Filesystem onboarding UX:** when target server requires allowed roots, provide an immediate actionable hint/command to set roots.

## Suggested Follow-ups

1. Add a small integration test that asserts profile-expected tool presence (lean vs forge).
2. Add optional reduced-log mode for realtime runs.
3. Harden subprocess shutdown path to avoid event-loop-closed warning.
4. Add a guided message after filesystem shapeshift explaining root requirements with concrete examples.
