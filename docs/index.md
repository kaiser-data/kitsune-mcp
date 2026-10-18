---
template: home.html
title: Kitsune MCP
hide:
  - navigation
  - toc
---

## The loop

Your agent edits an MCP tool, but the client still runs the old code.
Kitsune makes the restart a tool call, so the agent tests its own fix.

<ol class="ks-loop" markdown>
<li markdown>**Call.** Berlin: 59°C. Wrong.</li>
<li markdown>**Fix.** The agent edits the code.</li>
<li markdown>**Reload.** `reload("dev")`</li>
<li markdown>**Call again.** Berlin: 15°C. Same session.</li>
</ol>

[Try it](hot-reload.md){ .md-button }

## What it does

<div class="ks-uses" markdown>

<div markdown>
### Hot-reload your server

`connect`, edit, `reload`, call. No restarts.

[Tutorial](hot-reload.md)
</div>

<div markdown>
### Borrow any server

130,000+ servers from 7 registries. Mount one tool, use it, drop it.

[Quickstart](quickstart.md)
</div>

<div markdown>
### Run community code safely

npm and PyPI packages run in a locked-down Docker container.

[Safety](safety.md)
</div>

</div>

## Skip it if…

- you only use 1–3 trusted servers. Configure them directly.
- you want to save tokens. Kitsune itself costs ~1,774 per turn.
- you need sub-second first calls. A cold mount takes 1–15 s.

Works with Claude Code, Claude Desktop, Cursor, Windsurf, Cline, Zed and
[other clients](compatibility.md).
