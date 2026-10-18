# Agent patterns

Recipes that combine Kitsune's tools. Tools marked *full profile* in the
[tools reference](tools.md) need `KITSUNE_TOOLS=all`.

## Test the server you're building

The MCP REPL. Your agent runs, fixes and re-runs its own tool without anyone
restarting the client:

```python
connect("uv run python my_server.py", name="dev")
shapeshift("dev")
call("summarize", arguments={"url": "https://example.com"})  # wrong result

# … the agent edits the tool …

reload("dev")  # fresh code, tools remounted
call("summarize", arguments={"url": "https://example.com"})  # check the fix
release("dev")  # when done
```

Full walkthrough with a planted bug: [hot-reload tutorial](hot-reload.md).

## Check a server before you rely on it

*Uses `inspect` and `test` from the full profile.*

```python
search("web scraping", limit=5)
inspect("firecrawl")  # tools, schemas, required credentials
test("firecrawl")  # quality score 0–100
shapeshift("firecrawl", tools=["scrape_url"])
```

## Chain servers for a multi-step task

Mount one server at a time and drop it before the next:

```python
shapeshift("brave", tools=["brave_web_search"])
brave_web_search(query="MCP server list")
shapeshift()

shapeshift("mcp-server-fetch")
fetch(url="https://example.com/mcp-servers")
shapeshift()
```

`shapeshift("next-server")` also replaces the current form on its own; the
explicit `shapeshift()` keeps the transcript easier to follow.

## Keep a stateful server alive

Servers that hold a device or a session (audio, browsers, databases) should
run as a persistent connection, so every call reaches the same process:

```python
connect("uvx voice-mode", name="voice", timeout=30)
call("speak", "voice", {"text": "Hello"})
call("speak", "voice", {"text": "World"})  # same process, device stays open
release("voice")
```

`shapeshift()` with no argument unmounts tools but does not stop a
`connect()`ed process. Always `release()` it.

## Let Kitsune pick the server

```python
auto("current time in Tokyo")
auto("list issues on acme/api", server_hint="github")
```

`auto()` searches, picks a server, infers arguments and calls. Give a
`server_hint` when you already know the server; it skips the search.

## Benchmark before a batch

*Uses `bench` from the full profile.*

```python
bench("mcp-server-time", "get_current_time", {"timezone": "UTC"}, iterations=3)
# p50 / p95 / min / max in ms

shapeshift("mcp-server-time")
for tz in ["UTC", "Asia/Tokyo", "Europe/Berlin"]:
    get_current_time(timezone=tz)
shapeshift()
```

## Compare candidates

```python
search("postgres", compare=True)  # token cost and credentials side by side
```

With the full profile, `compare("postgres", limit=4)` probes the candidates in
parallel.
