# Kitsune MCP — Real-Time Demo Script

Three acts, each showing something native Tool Search **cannot** do, because each
needs code executed at runtime, not just tool schemas deferred:

1. [**Developing an MCP server live**](#act-1) — edit → reload → test, no restart
2. [**Executing a long-tail server**](#act-2) — Glama / Smithery, nothing pre-installed
3. [**The sandbox holding**](#act-3) — running unknown code, contained

Every block is a real tool call. Outputs are representative — abbreviated for the
screen, and the exact trust/error strings match Kitsune's real messages. Times
are for a screen recording; trim to taste.

> **Setup for the whole demo.** Acts 1 and 3 use the dev tools (`connect`,
> `release`), which are **not** in the default lean profile. Enable the full
> surface once:
>
> ```json
> { "mcpServers": { "kitsune": { "command": "kitsune-mcp",
>   "env": { "KITSUNE_TOOLS": "all" } } } }
> ```

---

## Act 1

### Real-time MCP development — the MCP REPL (≈ 45 s)

**The pain we're killing:** every edit to a work-in-progress MCP server normally
needs a client restart to take effect. Restart → lose session → re-establish
context → test one line → repeat.

**[SCREEN — split: editor left, agent session right]**

You're building `my-mcp-server`. It has a `summarize` tool that's returning junk.

```python
# Start the work-in-progress server as a pooled process
connect("uvx --from . my-mcp-server", name="dev")
```
```
Connected: dev (PID 40213)
Tools (3): search, fetch, summarize
Release with: release('dev')
⚠️  Source: local (verify command before connecting)
```

```python
call("summarize", arguments={"url": "https://example.com"})
```
```
"Example Domain Example Domain Example Domain …"   ← bug: it's repeating
```

**[CUT to editor]** — fix the bug in `summarize()`, save.

**[BACK to session]** — the naïve move is to just call `connect()` again. Watch
Kitsune stop you:

```python
connect("uvx --from . my-mcp-server", name="dev")
```
```
Already connected: dev (PID 40213) | uptime: 38s | calls: 1
Changed the code? release('dev') first — this process
predates your edit and is running the old code.
```

**CAPTION:** *It knows the pooled process is stale. No silent old-code trap.*

Reload properly — drop the old process, start the edit:

```python
release("dev")
connect("uvx --from . my-mcp-server", name="dev")
```
```
Released: dev (PID 40213) | uptime: 51s | calls: 1
Connected: dev (PID 40271)          ← new PID = new code
Tools (3): search, fetch, summarize
```

```python
call("summarize", arguments={"url": "https://example.com"})
```
```
"This domain is for use in illustrative examples in documents."   ← fixed
```

**TITLE CARD:** *Edit → reload → test. Same session. Zero restarts.*
*That's an MCP REPL.*

---

## Act 2

### Executing a long-tail server — Glama & Smithery (≈ 40 s)

**The pain we're killing:** you need a capability that lives in one of 130,000+
servers you were never going to add to your config. Native deferral can't help —
the server isn't configured. Kitsune discovers and runs it on demand.

**[SCREEN — agent session]**

```python
# Search a specific registry
search("pdf extraction", registry="glama")
```
```
1. mcp-pdf-tools        ⚠ glama (community)   ~7 tools   npx
2. pdf-reader-mcp       ⚠ npm (community)     ~4 tools   npx
   (2 community sources gated — pass confirm=True to run)
```

Community source, so Kitsune asks for one explicit confirm before it executes
anything (see [Act 3](#act-3) for why):

```python
shapeshift("mcp-pdf-tools", confirm=True)
```
```
Registered 7 tools: extract_text, extract_tables, get_metadata, …
⚠️  Source: glama via local npx/uvx (community — not verified by official MCP registry) (2.1s  — warm calls will be instant)
```

```python
call("extract_text", arguments={"path": "q3-report.pdf"})
shapeshift()        # done — process released, tools dropped
```

**[CUT]** — now a **hosted** server via Smithery (HTTP, no local install; needs a
free `SMITHERY_API_KEY`):

```python
search("web search", registry="smithery")
shapeshift("exa")                     # medium trust — no confirm needed
call("web_search_exa", arguments={"query": "MCP registry growth 2026"})
shapeshift()
```

**CAPTION:** *Local npx server and a remote hosted server — same three calls.
Neither was in your config. Neither needed a restart.*

**TITLE CARD:** *130,000+ servers. Summoned, used, released.*

---

## Act 3

### The sandbox holding — running unknown code, contained (≈ 40 s)

**The point:** "run anything on demand" is only safe because running an *unknown*
thing is contained. This act shows the guardrails refusing the unsafe path.

**[SCREEN — agent session]**

**Guard 1 — trust gate.** A community server won't run on a bare mount:

```python
shapeshift("some-random-npm-server")
```
```
⚠️  'some-random-npm-server' is from npm (community — not verified by the
    official MCP registry).
To proceed: shapeshift('some-random-npm-server', confirm=True)
To always trust community: auth("KITSUNE_TRUST", "community")
```
**CAPTION:** *No arbitrary code runs without an explicit, logged consent.*

**Guard 2 — command injection blocked.** A malicious server id can't smuggle a
shell command into the spawn:

```python
connect("uvx legit-server ; rm -rf ~", name="evil")
```
```
Error: Shell metacharacter in command: 'uvx legit-server ; rm -rf ~'
```
**CAPTION:** *Install commands are validated before a subprocess is ever spawned.*

**Guard 3 — SSRF blocked.** A server (or a redirect it follows) can't pivot to
your internal network. Requests are HTTPS-only, and any host that resolves to a
private, loopback, or otherwise non-public address is refused — including on
redirect hops, which are each re-validated:

```python
call("fetch", arguments={"url": "https://10.0.0.5/admin"})
```
```
Blocked: 'https://10.0.0.5/admin' resolves to a private/loopback address.
Set KITSUNE_ALLOW_LOCAL_FETCH=1 to allow.
```
**CAPTION:** *No cloud-metadata theft, no localhost pivots — even via redirect.*

**Guard 4 — isolation + caps.** When a server *does* run, it's contained:

```
• stdio servers  → isolated OS subprocess, separate memory
• docker servers → docker run --rm -i --memory 512m  (ephemeral, RAM-capped)
• pool           → max 10 processes, idle ones evicted after 1h
• credentials    → ~/.kitsune/.env at mode 0600, warned-on before use
```

**TITLE CARD:** *Reach the whole ecosystem — without trusting it blindly.*

---

## Closing (≈ 10 s)

```
pip install kitsune-mcp
```

**VOICEOVER:** *"Tool Search made your configured servers cheap. Kitsune makes
every server you *didn't* configure reachable — built live, run on demand, and
sandboxed. One config entry. No restarts."*

---

*Companion to the launch script in [`demo-script.md`](demo-script.md). Commands
reflect the real tool surface; see [`../README.md`](../README.md) for the
authoritative reference.*
