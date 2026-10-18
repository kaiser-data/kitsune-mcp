# Hot-reload tutorial

When an agent writes an MCP server, it can't test its own change: the client
still runs the old process. This tutorial shows the loop that fixes that,
using a demo server with one planted bug.

![Claude Code connects the demo weather server through Kitsune, gets 59°C for Berlin, fixes the conversion, reloads and gets 15°C](https://raw.githubusercontent.com/kaiser-data/kitsune-mcp/main/docs/demo-hot-reload.gif)

## What you need

- Kitsune in your client. See [installation](installation.md).
- [uv](https://docs.astral.sh/uv/).
- The demo server. Clone the repo, or save
  [`weather_server.py`](https://github.com/kaiser-data/kitsune-mcp/blob/main/examples/demo-hot-reload/weather_server.py)
  into an empty folder.

The bug: the server stores readings in Fahrenheit and labels them as Celsius,
so Berlin comes back at **59°C**. Fixed, it says **15°C**.

## Let the agent do it

Open your client in the folder with `weather_server.py` and give it one
prompt:

```text
Use kitsune: connect("uv run weather_server.py", name="dev"),
then call get_weather for Berlin. If it looks wrong, fix the code,
reload("dev") and check again. Answer in one short line.
```

The agent works through the loop on its own.

## The loop, step by step

These are the calls the agent makes. You can type them yourself, too.

**1. Start your server and mount its tools.**

```python
connect("uv run weather_server.py", name="dev")
shapeshift("dev")
```

`connect()` keeps the process alive between calls. `shapeshift("dev")` puts
its tools into the client as native tools.

**2. Call the tool.**

```python
call("get_weather", arguments={"city": "Berlin"})
# Berlin: 59°C
```

**3. Fix the code.** In `weather_server.py`:

```python
def _to_celsius(fahrenheit: float) -> float:
    return (fahrenheit - 32) * 5 / 9
```

**4. Reload.**

```python
reload("dev")
```

Kitsune stops the old process, starts the new code and remounts the tools.
The session keeps going.

**5. Call it again.**

```python
call("get_weather", arguments={"city": "Berlin"})
# Berlin: 15°C
```

When you're done, `release("dev")` stops the server.

## Your own server

Replace the command with whatever starts your server:

```python
connect("uvx --from . my-mcp-server", name="dev")  # a package in this folder
connect("node build/index.js", name="dev")  # a Node server
connect("python -m my_server", name="dev")  # a module
```

Then the loop is always the same: edit, `reload("dev")`, call.

## Troubleshooting

`Already connected: dev`
:   A previous run is still alive. Call `release("dev")`, or just
    `reload("dev")`.

The tool list in the client doesn't change
:   Your client may not handle `notifications/tools/list_changed`. `call()`
    still works. See [client compatibility](compatibility.md).

The server crashes on start
:   `connect()` passes the server's stderr through, so the traceback is in
    Kitsune's log. Fix it and `reload("dev")`.

`ModuleNotFoundError: mcp.server.fastmcp`
:   mcp 2.x renamed FastMCP. The demo pins the 1.x SDK in its inline script
    metadata, so start it with `uv run weather_server.py`, not plain `python`.
