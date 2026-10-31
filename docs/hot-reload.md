# Hot-reload tutorial

Let your agent fix and re-test its own MCP tool, without restarting the
client.

![Claude Code connects the demo weather server through Kitsune, gets 59°C for Berlin, fixes the conversion, reloads and gets 15°C](https://raw.githubusercontent.com/kaiser-data/kitsune-mcp/main/docs/demo-hot-reload.gif)

## Setup

1. [Install Kitsune](installation.md).
2. Save [`weather_server.py`](https://github.com/kaiser-data/kitsune-mcp/blob/main/examples/demo-hot-reload/weather_server.py)
   in an empty folder. It has one bug: it reports Fahrenheit as Celsius.

## Run it

Open your client in that folder and send:

```text
Use kitsune: connect("uv run weather_server.py", name="dev"),
then call get_weather for Berlin. If it looks wrong, fix the code,
reload("dev") and check again.
```

The agent calls the tool (59°C), fixes the code, reloads, and calls again
(15°C).

## What happens

```python
connect("uv run weather_server.py", name="dev")  # start your server
shapeshift("dev")  # its tools appear in the client
call("get_weather", arguments={"city": "Berlin"})  # Berlin: 59°C

# the agent fixes _to_celsius()

reload("dev")  # restart on the new code
call("get_weather", arguments={"city": "Berlin"})  # Berlin: 15°C
release("dev")  # stop when done
```

## Your own server

Swap the command. The loop stays the same.

```python
connect("uv run my-mcp-server", name="dev")  # Python package
connect("node build/index.js", name="dev")  # Node
```

Use `uv run`, not `uvx --from .`, for a Python package you're editing.
`uv run` installs the project in editable mode, so every `reload()` runs your
latest code. `uvx --from .` builds the project once and keeps serving that
cached build, so `reload()` would restart the old code; Kitsune warns when it
sees that command. If Kitsune runs from another directory, point uv at the
project: `uv run --directory /path/to/project my-mcp-server`.

## Troubleshooting

`Already connected: dev`
:   Use `reload("dev")`, or `release("dev")` first.

Tools don't appear in the client
:   Your client may ignore `tools/list_changed`. `call()` still works.
    [Check your client](compatibility.md).

Server crashes on start
:   The traceback is in Kitsune's stderr. Fix it, then `reload("dev")`.

`reload()` still runs the old code
:   You probably launched with `uvx --from .`, which serves a cached build.
    `release("dev")`, then `connect("uv run my-mcp-server", name="dev")`.
