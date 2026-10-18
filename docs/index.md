---
template: home.html
title: Kitsune MCP
hide:
  - navigation
  - toc
---

## The loop your agent couldn't run

When an agent writes an MCP server, the client keeps running the old process.
Someone has to restart the client before the agent can see whether its fix
worked. Kitsune turns that restart into a tool call, so the agent closes the
loop itself:

<ol class="ks-loop" markdown>
<li markdown>**Call the tool** and read the result. `call("get_weather", {"city": "Berlin"})` says 59°C.</li>
<li markdown>**Fix the code.** The agent sees Fahrenheit labelled as Celsius and edits the conversion.</li>
<li markdown>**Reload.** `reload("dev")` restarts the server on the new code and remounts its tools.</li>
<li markdown>**Call it again.** 15°C, same session. Nobody restarted anything.</li>
</ol>

[Walk through it yourself](hot-reload.md){ .md-button }

## Three things it does

<div class="ks-uses" markdown>

<div markdown>
### Iterate on your own server

`connect` your server under development, `shapeshift` into it, and its tools
show up as native tools. After every edit, `reload` and call again.

[Hot-reload tutorial](hot-reload.md)
</div>

<div markdown>
### Borrow a server for one task

`search` 7 registries with 130,000+ servers, mount one server or a single tool,
use it, and drop it again. Your config stays small.

[Quickstart](quickstart.md)
</div>

<div markdown>
### Try community code, caged

npm and PyPI packages need `confirm=True` and run in a hardened Docker
container when Docker is available: no host files, all capabilities dropped,
read-only root.

[Safety model](safety.md)
</div>

</div>

## When to use it, and when not

| Use Kitsune when… | Skip it when… |
|---|---|
| You're building an MCP server and want an edit/reload loop | You only use 1–3 trusted servers. Configure them natively. |
| A task needs a server that isn't in your config | Every turn hits the same server. Keep it always-on. |
| You want to evaluate community MCP code without installing it for good | You want lower token use. The base cost is ~1,774 tokens per turn. |
| Your MCP config is crowded | You need a sub-second first call. A cold mount takes ~1–15 s. |

Works in Claude Code, Claude Desktop, Cursor, Windsurf, Cline, Zed and any
client that supports `notifications/tools/list_changed`.
[Check your client](compatibility.md).
