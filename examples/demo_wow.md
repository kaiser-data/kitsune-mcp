# Kitsune MCP — 5-Minute Demo

The canonical "wow demo": one session that proves all three pillars of the agent
harness — **reach** (run a server you never configured), the **MCP REPL** (edit →
reload → test, no restart), and **try-before-you-trust** (community code runs
gated). Every step below runs on the **default install** — no `KITSUNE_TOOLS=all`,
no config edits, no restarts.

> *Tool Search defers what you've configured; Kitsune runs what you haven't.*

---

## Prerequisites

```bash
pip install kitsune-mcp
```

Add once to your MCP config and restart your client:

```json
{
  "mcpServers": {
    "kitsune": { "command": "kitsune-mcp" }
  }
}
```

Copy each line into your AI client and run it.

---

## Step 1 — Check baseline

```
status()
```

Lean profile: the gateway tools only (`status`, `search`, `auth`, `shapeshift`,
`call`, `auto`, `connect`, `release`, `reload`), 0 mounted server tools. This is
the fixed token floor you pay — it never drops to zero, and it's *additive* on a
Tool Search client. Kitsune earns it back by reaching the servers deferral can't.

---

## Step 2 — Discover servers

```
search("web search")
```

Results come from the official registry first, then Smithery (if you have a key),
then npm/PyPI/Glama. Each row ends with a **works-now signal** — `ready: high | mid
| low` — a no-probe heuristic (creds resolved + trusted source + local transport)
so you can see at a glance which hits are likely to run without setup.

Scope to one registry when you want to:

```
search("web search", registry="pypi")
```

---

## Step 3 — Reach: mount a server you never configured

`duckduckgo-websearch` is free and needs no key. Community source, so Kitsune
asks for one explicit confirm before it runs any code (that's pillar three):

```
shapeshift("duckduckgo-websearch", confirm=True)
```

Its tools register **live** onto the session — the client gets a
`tools/list_changed` notification, no restart. The mount output lists the exact
tool names; call one by name with `call("<tool>", arguments={...})`.

---

## Step 4 — Swap without a restart

```
shapeshift("mcp-server-time")
```

`shapeshift` sheds the current form before mounting the next — one server at a
time. Now the time tools are live, callable by name:

```
call("get_current_time", arguments={"timezone": "UTC"})
```

Drop back to the lean floor when you're done:

```
shapeshift()
```

---

## Step 5 — One-shot magic with auto()

For an everyday user who doesn't want to think about mounting, `auto()` discovers,
mounts, calls, and cleans up in a single turn:

```
auto(task="what time is it in Tokyo")
```

It ranks candidates by the same works-now signal, runs the best one, returns the
answer, and sheds the form.

---

## Step 6 — The MCP REPL: edit → reload → test

The developer loop. Point `connect()` at a work-in-progress server the registry
has never heard of (use an **absolute path**), mount it, and call a tool:

```
connect("python /abs/path/to/server.py", name="dev")
shapeshift("dev")
call("greet", arguments={"name": "world"})
```

Edit the tool's code, save — then reload in **one call**. `reload()` kills the
stale process, starts fresh code, and remounts live, so the client sees the new
schema without a restart (and never hands you back the old process):

```
reload("dev")
call("greet", arguments={"name": "world"})
```

The changed behaviour is live in the same session. When you're finished:

```
shapeshift()      # unmount tools → back to the lean floor
release("dev")    # ensure the child process is gone
```

---

## Step 7 — Final status

```
status()
```

Back at the lean floor, with a summary of what you explored and the pool health.
Nothing you mounted is still in your config — it was summoned, used, and released.

---

## Full session transcript

```
status()
search("web search")
shapeshift("duckduckgo-websearch", confirm=True)
shapeshift("mcp-server-time")
call("get_current_time", arguments={"timezone": "UTC"})
shapeshift()
auto(task="what time is it in Tokyo")
connect("python /abs/path/to/server.py", name="dev")
shapeshift("dev")
call("greet", arguments={"name": "world"})
reload("dev")
call("greet", arguments={"name": "world"})
shapeshift()
release("dev")
status()
```

---

## What just happened

| Step | Pillar | What it shows |
|------|--------|--------------|
| `status()` baseline | — | The honest lean floor — fixed, additive, never zero |
| `search()` | reach | Discovery across registries with a `ready:` works-now signal |
| `shapeshift(confirm=True)` | try-before-trust | Community code runs only after one explicit consent |
| `call()` | reach | The mounted tool is callable by name — no wrapper, no restart |
| `shapeshift("...")` / `shapeshift()` | reach | Hot-swap one form for another, then back to base |
| `auto()` | reach | Discover → mount → call → shed in a single turn |
| `connect` → `shapeshift` → `reload` | MCP REPL | Edit → reload → test in place, zero restarts |
| `status()` final | — | Summoned, used, released — nothing left in your config |
