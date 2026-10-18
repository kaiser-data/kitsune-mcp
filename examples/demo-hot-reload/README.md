# Demo: your agent debugs its own MCP tool

A 30-second recording for the top of the main README. One prompt from you;
Claude calls the tool, sees a wrong answer, fixes the code, runs `reload("dev")`,
and calls it again. Nobody restarts anything.

`weather_server.py` has one planted bug: it returns Fahrenheit labelled as
Celsius, so Berlin comes back at **59°C**. Fixed, it says **15°C**.

## Before you record

1. Kitsune is in your Claude Code config:
   `claude mcp add -s user kitsune -- uvx kitsune-mcp`
2. Reset the bug (needed before every take):
   `git checkout -- examples/demo-hot-reload/weather_server.py`
3. Warm the uv cache so the first connect isn't slow on camera:
   `uv run --with mcp~=1.27 python -c "import mcp.server.fastmcp"`
4. Start Claude Code from the repo root in a clean session (`claude`), with a
   large font, a dark theme, and nothing else on screen.

## Shot list

| # | On screen | Time |
|---|---|---|
| 1 | Editor: `weather_server.py`, the `_to_celsius` line visible | 3 s |
| 2 | You type the prompt below | 4 s |
| 3 | Claude: `connect` → `shapeshift("dev")` → `call` → **`Berlin: 59°C`** | 6 s |
| 4 | Claude: "59°C is not plausible for Berlin, the value looks like Fahrenheit", edits `_to_celsius` | 6 s |
| 5 | Claude: `reload("dev")` → `call` → **`Berlin: 15°C`** | 6 s |
| 6 | End card: *Your agent just debugged its own tool. No restart.* + install line | 4 s |

The prompt, in one go:

```text
Connect my MCP server with kitsune: connect("uv run --with mcp~=1.27 python examples/demo-hot-reload/weather_server.py", name="dev").
Shapeshift into it and get the weather for Berlin. If the result looks wrong, fix the server code,
reload("dev"), and check again.
```

Keep the scrollback on screen at step 5, so the viewer sees it is the same session.

## Recording

```bash
asciinema rec demo.cast          # record the Claude Code session
agg --speed 1.5 demo.cast demo.gif   # trim idle time, aim for < 5 MB
```

Or use a screen recording and export MP4; GitHub plays an MP4 dragged into
the README editor. Cut the model's thinking pauses and the cold start; keep
the two tool results (59°C and 15°C) on screen for at least a second each.

## If a take goes wrong

- **Claude fixes the number by hand instead of the code:** say "fix it in the server code".
- **`Already connected: dev`:** a previous take is still running; `release("dev")` first.
- **Berlin already shows 15°C:** you forgot step 2 of the setup.

## Re-recording with vhs

`demo.tape` is the script behind `docs/demo-hot-reload.gif`. It expects a copy of
`weather_server.py` in `~/my-weather-mcp/` (outside any repo, so no CLAUDE.md
leaks in) and `~/.kitsune-demo-mcp.json` with
`{"mcpServers": {"kitsune": {"command": "uvx", "args": ["kitsune-mcp@0.22.3"]}}}`.
Trust the folder once by hand, then run `vhs demo.tape` and convert:

```bash
ffmpeg -i demo.mp4 -vf "fps=10,scale=1000:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" -loop 0 docs/demo-hot-reload.gif
```
