# Tools reference

Every Kitsune tool, its parameters and an example. Signatures match the code
in `kitsune_mcp/tools/`.

## Tool profiles

Kitsune registers a **lean profile** by default, so its own footprint stays
around 1,774 tokens per turn:

`status` · `search` · `auth` · `shapeshift` · `call` · `auto` · `connect` · `release` · `reload`

Every other tool on this page is in the **full profile**. Turn it on with an
environment variable in your client config:

```json
{
  "mcpServers": {
    "kitsune": {
      "command": "uvx",
      "args": ["kitsune-mcp"],
      "env": { "KITSUNE_TOOLS": "all" }
    }
  }
}
```

`KITSUNE_TOOLS` also takes a comma-separated list, for example
`KITSUNE_TOOLS=shapeshift,call,reload`.

Tools from the full profile are marked *full profile* below.

---

## The MCP REPL

The developer loop: run your own server, call its tools, edit, reload. See the
[hot-reload tutorial](hot-reload.md).

### `connect`

```python
connect(command, name="", timeout=60, inherit_stderr=True)
```

Start a persistent server and keep its process alive between calls.
`command` is a shell command or a server id; `name` is the alias you use with
`reload()` and `release()`.

```python
connect("uv run python my_server.py", name="dev")
shapeshift("dev")  # mount its tools as native tools
```

`inherit_stderr=True` lets the server's own log output through to Kitsune's
stderr, which is where you'll see tracebacks.

### `reload`

```python
reload(name)
```

Restart a persistent connection on fresh code and remount its tools, in one
call. Replaces the manual `release()` + `connect()` + `shapeshift()` cycle.

```python
reload("dev")
call("get_weather", arguments={"city": "Berlin"})  # runs the new code
```

### `release`

```python
release(name)
```

Stop a persistent connection and remove it from the pool.

```python
release("dev")
```

### `prewarm` *full profile*

```python
prewarm(server_id, confirm=False, server_args=None, sandbox=None)
```

Start a server's process in the pool **without** mounting its tools. The
next `shapeshift(server_id)` reuses the warm process and skips the
npx/uvx install delay.

```python
prewarm("mcp-server-time")
shapeshift("mcp-server-time")  # no install delay
```

Community sources need `confirm=True` and cage by default, like
`shapeshift()`. Discard an unused warm process with `release(server_id)`.
HTTP-hosted servers have no local process to prewarm.

---

## Discover

### `search`

```python
search(query, compare=False, registry="all", limit=5)
```

Find MCP servers across registries. Returns ranked server ids with name,
description, source and whether their credentials are ready.

```python
search("web search")
search("postgres", compare=True)  # side-by-side token-cost table
search("vector db", registry="smithery")
```

`registry`: `all`, `official`, `mcpregistry`, `glama`, `npm`, `smithery`,
`pypi`. A failing registry is reported inline; the others still return.

### `inspect` *full profile*

```python
inspect(server_id, probe=False)
```

Show a server's tools, schemas and required credentials. High- and
medium-trust sources are probed live; community sources (npm, GitHub,
Glama-via-GitHub) only with `probe=True` or `KITSUNE_TRUST=community`.

```python
inspect("mcp-server-time")
```

### `compare` *full profile*

```python
compare(query, limit=6, probe=False)
```

Token cost and credential needs for the top candidates of a search, probed in
parallel. Use it to choose before you `shapeshift()`.

```python
compare("github", limit=4)
```

---

## Mount and call

### `shapeshift`

```python
shapeshift(server_id="", tools=None, keep=False, confirm=False, source="auto", server_args=None, sandbox=None)
```

Mount a server's tools as native tools in your client. The client receives
`notifications/tools/list_changed` and sees the server's real schemas.

```python
shapeshift("mcp-server-time")  # mount
shapeshift("github", tools=["search_repositories"])  # mount one tool
shapeshift()  # unmount and stop the process
```

| Parameter | Meaning |
|---|---|
| `tools` | Mount only these tools |
| `confirm` | Required for community sources (npm, PyPI, GitHub) |
| `sandbox` | `None`: cage community sources in Docker when available. `True`: force the cage. `False`: opt out |
| `source` | `auto`, `local`, `smithery` or `official` |
| `server_args` | Extra arguments for the server process |
| `keep` | With no `server_id` (unmount): keep the process warm in the pool instead of stopping and uninstalling it |

The Docker cage has no host filesystem, drops all capabilities, uses a
read-only root and caps RAM and PIDs. Credentials are forwarded by name only.
Details in [safety](safety.md).

### `call`

```python
call(tool_name, server_id=None, arguments=None, config=None)
```

Call a tool. After `shapeshift()` it routes through the warm process;
otherwise it starts a transient one for `server_id`. Long responses are
truncated with a note.

```python
call("get_current_time", arguments={"timezone": "UTC"})  # after shapeshift
call("list_directory", "@mcp/server-fs", {"path": "/tmp"})  # one-shot
```

### `auto`

```python
auto(task, tool_name="", arguments=None, server_hint="", keys=None)
```

Search, pick a server, infer arguments and call, in one step. Use it when you
don't know which server to use.

```python
auto("what time is it in Tokyo")
auto("list issues on acme/api", server_hint="github")
```

### `shiftback` *full profile*

```python
shiftback(kill=True, uninstall=False)
```

Unmount the current server. `kill=False` keeps its process pooled;
`uninstall=True` also removes a locally installed package. In the lean
profile, `shapeshift()` with no argument does the same. Persistent
connections from `connect()` stay up; stop them with `release()`.

### `run` *full profile*

```python
run(package, tool_name, arguments=None)
```

Run one tool from an npm or PyPI package without mounting it. `package` is
`"pkg-name"` (npx) or `"uvx:pkg-name"` (Python).

```python
run("uvx:mcp-server-time", "get_current_time", {"timezone": "UTC"})
```

### `fetch` *full profile*

```python
fetch(url, intent="")
```

Fetch a URL and return compressed content, about 500 tokens instead of ~25K of
raw HTML.

```python
fetch("https://example.com/changelog", intent="latest release date")
```

### `craft` *full profile*

```python
craft(name, description, params, url, method="POST", headers=None)
```

Register a tool backed by your own HTTP endpoint. It is live immediately.
`POST` sends a JSON body, `GET` sends query parameters. `shiftback()` removes
it.

---

## Credentials

### `auth`

```python
auth(server_id_or_var, value="")
```

Check or set credentials. An ALL_CAPS argument is an environment variable;
anything else is a server id.

```python
auth("GITHUB_TOKEN", "ghp_...")  # save to ~/.kitsune/.env, no restart
auth("GITHUB_TOKEN")  # is it set?
auth("server-id")  # which credentials does it need? Runs OAuth if needed
auth("server-id", "logout")  # revoke OAuth tokens
```

### `key` *full profile*

```python
key(env_var, value)
```

Save an API key to `~/.kitsune/.env` (or `$KITSUNE_HOME/.env`) for later
sessions.

```python
key("EXA_API_KEY", "sk-...")
```

---

## Quality

### `test` *full profile*

```python
test(server_id, level="basic")
```

Score a server from 0 to 100. `basic` checks schemas; `full` makes live calls.

### `bench` *full profile*

```python
bench(server_id, tool_name, args=None, iterations=5)
```

Measure a tool's latency: p50, p95, min and max in ms. `iterations` is 1 to 20.

```python
bench("mcp-server-time", "get_current_time", {"timezone": "UTC"}, iterations=3)
```

---

## Session and setup

### `status`

```python
status()
```

Show providers, the current form, persistent connections and token stats.

### `onboard` *full profile*

```python
onboard()
```

First-run check: provider auth state and a short list of zero-config servers
you can mount right away.

### `setup` *full profile*

```python
setup(name="", action="", keep=None, project=False, confirm=False)
```

Gateway wizard. Moves the servers from your other MCP configs behind Kitsune.

| Call | Effect |
|---|---|
| `setup()` | Detect other servers and preview what would be harvested |
| `setup(action="harvest")` | Copy API keys from other configs to `~/.kitsune/.env` |
| `setup(action="absorb")` | Harvest, and register those servers for `shapeshift()` |
| `setup(action="exclusive")` | Absorb, and rewrite the config so only Kitsune is left (backup first) |
| `setup(action="restore")` | Restore the config from the backup |
| `setup(project=True)` | Write `.claude/mcp.json` with only Kitsune, for this project |

See [configuration](configuration.md#gateway-consolidate-always-on-servers).

### `skill` *full profile*

```python
skill(qualified_name, forget=False)
```

Load a Smithery skill into context. `forget=True` removes it.

---

## Response size

Tool responses are capped at about 1,500 tokens (~6,000 characters); longer
ones are truncated with a note. Use `fetch()` for web pages.
