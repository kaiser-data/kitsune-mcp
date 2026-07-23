# Kitsune MCP — Test Session

Paste the prompt below into a Claude Code session that has Kitsune MCP configured
(default lean profile — no `KITSUNE_TOOLS=all` needed). Run tests in order — each
one builds on the previous.

---

## Prompt to paste

```
You are running a structured test of Kitsune MCP v0.21.0 (lean profile).

Work through each test case below in order. For every test:
1. Call the tool(s) listed
2. Check the expected output
3. Report PASS or FAIL with what you actually observed

Do not skip tests. If a test fails, note why and continue to the next one.

---

TEST 1 — Verify Kitsune is running
Call: status()
Expect:
- Output starts with "KITSUNE MCP STATUS" (or equivalent status header)
- Shows current form is base / no mount active
- Shows PERFORMANCE STATS (or resting token floor)

---

TEST 2 — Search works + works-now signal
Call: search("filesystem")
Expect:
- At least one result returned
- Each result shows source/transport (e.g. "official/stdio")
- Each row ends with " | ready: high|mid|low"
- Result includes @modelcontextprotocol/server-filesystem (or mcp-server-filesystem)

---

TEST 3 — Inspect fetches live schemas (forge-only; skip if lean)
If inspect() is not available in this session, SKIP and note "lean profile".
Otherwise call: inspect("@modelcontextprotocol/server-filesystem")
Expect:
- Shows Source / Transport
- TOOLS section lists read_file, write_file, list_directory (and others)
- Shows a measured token cost
- CREDENTIALS: none required

---

TEST 4 — Full mount injects tools
Call: shapeshift("@modelcontextprotocol/server-filesystem")
Expect:
- Output says shapeshifted / registered tools for that server
- Lists registered tools (read_file, write_file, list_directory, …)
- Shows a Source: official (high-trust) note
- Filesystem tools are now visible in your tool list

---

TEST 5 — Mounted tool actually executes
Call via call(): call("list_directory", arguments={"path": "/tmp"})
  (or the exact registered proxy name if prefixed)
Expect:
- Returns a real directory listing (not an error)

---

TEST 6 — Unmount removes mounted tools
Call: shapeshift()
Expect:
- Form is cleared / tools unmounted
- Filesystem tools are gone from your tool list

---

TEST 7 — Lean mount filters to specific tools
Call: shapeshift("@modelcontextprotocol/server-filesystem", tools=["read_file", "list_directory"])
Expect:
- Output mentions lean / only the listed tools
- Only 2 tools registered — NOT write_file, create_directory, etc.
Then call: shapeshift()

---

TEST 8 — Community trust gate + default cage
Call: shapeshift("mcp-server-brave-search")   # no confirm
Expect:
- Warning that the source is community / npm
- Instructs confirm=True to proceed
- Mentions Docker cage by default (or sandbox=False to opt out)
- Tools are NOT registered yet (gate blocked)
Then (optional, if Brave key present):
  shapeshift("mcp-server-brave-search", confirm=True)
  Expect caged-in-Docker note when Docker is available, or uncaged nudge if not
  shapeshift()

---

TEST 9 — MCP REPL reload is on lean
Call: connect("npx -y @modelcontextprotocol/server-everything", name="dev")
  (or any quick local stdio server you have)
Expect: Connected with a PID and tool list
Then call: reload("dev")
Expect:
- Reloaded message (old PID killed, restarted, remounted)
- Does NOT say "Already connected … predates your edit"
Then: shapeshift(); release("dev")

---

TEST 10 — status() full picture
Call: status()
Expect:
- Reflects explored / mounted activity from earlier tests
- Resting floor still quoted around ~1,774 tokens for lean

---

SUMMARY
Report:
- How many tests passed / failed / skipped
- Whether reload() worked in one call (TEST 9)
- Whether the community gate mentioned default cage (TEST 8)
- Any unexpected behaviour
```

---

## Expected token numbers (reference)

| Surface | Expected tokens |
|---|---|
| Kitsune lean (9 tools) | ~1,774 |
| Kitsune forge (22 tools) | ~3,561 |
| filesystem server (14 tools) | ~3,000+ |
| memory server (varies) | ~2,000+ |

Run `python examples/benchmark.py` for exact lean/forge schema costs.

---

## Checklist — what each test validates

| Test | What it proves |
|---|---|
| 1 | Kitsune is connected and responding |
| 2 | Registry fan-out + works-now signal |
| 3 | inspect() (forge) fetches schemas without mounting |
| 4 | shapeshift() registers tools natively |
| 5 | Proxy execution works via call() |
| 6 | shapeshift() empty arg unmounts cleanly |
| 7 | Lean mount (`tools=[…]`) filters correctly |
| 8 | Community trust gate + default Docker cage messaging |
| 9 | Lean MCP REPL: connect + one-call reload |
| 10 | Session state accumulates across operations |

---

## Troubleshooting

**"Server not found"** — run `search("filesystem")` first to confirm registry reachability.

**Mount takes a long time** — first run downloads the npm package via npx. Subsequent calls use the process pool and are instant.

**No trust warning on TEST 8** — check that the id resolves from npm (source should be "npm", not "official").

**reload says Already connected** — that means the old 3-step footgun; `reload` should always release first. File a bug if it doesn't.
