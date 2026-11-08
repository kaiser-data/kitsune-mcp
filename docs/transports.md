# Transports Guide

Kitsune MCP supports several transport types. Here's when to use each.

## Decision Tree

```
Does the server need to stay alive between calls?
├── Yes → PersistentStdioTransport  (use connect() / release())
└── No → Is it hosted on smithery.ai?
          ├── Yes → HTTPSSETransport  (automatic for remote servers)
          └── No → StdioTransport    (automatic for stdio servers)
```

## HTTPSSETransport

**When:** remote servers: Smithery-hosted (`remote: true` in the registry) or a
direct `https://` URL.

**How it works:**

1. Sends `initialize` over HTTPS and keeps the session the server returns
   (`mcp-session-id`, negotiated protocol version). Later calls reuse it;
   concurrent calls share one handshake.
2. Reads each reply as the server sends it: plain JSON, or an SSE stream read
   event by event. The reply is matched to the request by its JSON-RPC id, so
   progress and log notifications on the stream are skipped. Requests the
   server sends back (such as `ping`) are answered.
3. If the server rejects the `initialize` POST with 400, 404 or 405, it is
   treated as an old **HTTP+SSE** server (spec 2024-11-05): Kitsune opens its
   GET event stream and posts to the endpoint the stream names, which must be
   on the same origin.
4. Sessions expire after 30 minutes and are closed with `DELETE`.

A `tools/call` whose reply is lost is never sent again: Kitsune reports
"outcome unknown", because the call may already have run.

**Config:** Smithery needs `SMITHERY_API_KEY`; config is passed as base64 in URL
params. Direct URLs use OAuth 2.1 when the server asks for it.

**Example:**
```python
call("exa/exa", "web_search_exa", {"query": "AI news"})
# or
shapeshift("exa/exa")  # auto-selects HTTPSSETransport
```

**Timeout:** 30s per call. Server may be cold-starting — retry once if timeout.

## WebSocketTransport

**When:** `ws://` or `wss://` server URLs. Install the extra first:
`pip install "kitsune-mcp[ws]"`.

WebSocket is **not** one of the MCP specification's standard transports. It is
a custom transport some servers offer: one JSON-RPC message per text frame.
Kitsune opens a connection per operation, checks the `initialize` reply (it
must carry a `protocolVersion`), and matches replies by request id, answering
server requests and skipping notifications. `tools/list` follows pagination
cursors, so `shapeshift()` can discover the server's tools.

## StdioTransport

**When:** Local npm/pip packages, stdio-mode Smithery servers.

**How it works:**
1. Spawns subprocess: `npx -y package-name` or `uvx package-name`
2. Sends MCP initialize + notifications/initialized
3. Calls tool via JSON-RPC
4. Kills process when done

**Latency:** 3-30s startup (first run downloads package). Subsequent calls reuse cache.

**Example:**
```python
call("@modelcontextprotocol/server-filesystem", "read_file", {"path": "/tmp/test.txt"})
run("mcp-server-fetch", "fetch", {"url": "https://example.com"})
```

**Limitation:** Each call spawns a new process. Not suitable for hardware/audio servers.

## PersistentStdioTransport

**When:** Hardware servers (audio, camera, etc.) that must stay alive between calls.

**How it works:**
1. First call: spawns process, runs MCP handshake, stores in `_process_pool`
2. Subsequent calls: reuses existing process (serialized with asyncio.Lock)
3. Auto-reconnects once if process dies
4. `stderr=None` — inherits parent stderr so audio errors surface

**Example:**
```python
connect("uvx voice-mode", name="voice")
# Now use shapeshift() or call voice-mode tools directly
release("voice")  # kills process, removes from pool
```

**Key difference from StdioTransport:** Process stays alive. Use `release()` when done.

## Choosing the Right Transport

| Scenario | Transport | Command |
|----------|-----------|---------|
| Smithery hosted API | HTTPSSETransport | `call()` / `shapeshift()` automatic |
| One-shot npm tool | StdioTransport | `call()` / `run()` / `shapeshift()` automatic |
| Audio/hardware tool | PersistentStdioTransport | `connect()` then `release()` |
| Unknown server | Auto-detected | `call()` detects from registry |
