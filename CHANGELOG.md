# Changelog

All notable changes to this project are documented here.

---

## [0.25.5] — 2026-11-22

Follow-ups from the live check of 0.25.4. Behaviour changes: a blocked or failed `fetch()` comes back as a tool error (`isError: true`); stdio servers that ask Kitsune something mid-call get an answer (`ping` succeeds, anything else is refused), as HTTP servers already did.

### Fixed
- **A blocked or failed `fetch()` is reported as an error.** `Blocked: …` and `Failed to fetch …` came back as ordinary content (`isError: false`), so a client could not tell a refused URL from page text. Both now come back as tool errors (`isError: true`) with the same message. Successful fetches are unchanged.
- **Stdio servers get an answer when they ask Kitsune something.** A server may send a request mid-call (`ping`, sampling, roots). HTTP servers already got a reply; stdio servers did not, so one that waited for it hung until the call timed out. `ping` now succeeds and anything else is refused with "method not found", the same as over HTTP.
- **`shapeshift()` keeps your current server when none of the new tools can be registered.** A `tools=` filter that matched nothing (or names that were all taken) unmounted the current server first and then mounted nothing. This is now checked before anything is unmounted, and the error lists the tools the server does have.

### Tests
- **The test suite runs offline.** Two tests reached real registries through unmocked fallbacks. They are mocked now, and a conftest guard fails any test that resolves a real hostname unless it is marked `@pytest.mark.network`.

---

## [0.25.4] — 2026-11-22

The last findings from both external reviews: DNS rebinding is closed for guarded requests, leftover servers of exited launchers are stopped, OAuth follows RFC 8414 / RFC 9207 best practice, and crafted tools, `.env` values and guard argument checks are fixed. Behaviour changes: OAuth registration and revocation endpoints must use HTTPS; `auth()` writes `.env` values single-quoted and refuses values containing `${`; `shiftback()` (or mounting another server) deletes crafted tools for good. Kitsune now depends on `httpcore` directly (already installed with httpx).

### Fixed
- **A server whose launcher already exited is stopped too.** `npx`/`uvx` wrappers can exit while the real server keeps running in their process group. Cleanup skipped any process whose wrapper had exited, so that server survived `release()`, eviction and shutdown. It is now killed when the group is provably Kitsune's: the leader's pid is free and the group still exists, which POSIX only allows for the original group.
- **DNS rebinding is closed for guarded requests.** The private-address check resolved a hostname, then the connection resolved it again, so a resolver could answer public to the check and private to the connection (cloud metadata, internal services). `fetch()`, crafted tools and public OAuth metadata now connect to an address taken from the same lookup that was checked; every answer must be public. TLS still verifies the hostname. Requests through a configured proxy, and `KITSUNE_ALLOW_LOCAL_FETCH=1`, are not pinned.
- **Crafted tools keep their headers after a restart.** `craft(..., headers=…)` worked until Kitsune restarted; the saved definition had no headers, so the restored tool called its endpoint without `Authorization` and got 401. Headers are now saved with the tool (`state.json` is written `0600`, like `.env`).
- **A removed crafted tool stays removed.** `shiftback()` unregistered a crafted tool but kept its definition, so it came back on the next start, untracked (a second `shiftback()` said "Already in base form"). Shedding now forgets crafted tools, and restored ones are tracked again.
- **Saved keys come back exactly as written.** `auth()` wrote `.env` values unquoted, so `abc #def` reloaded as `abc`, surrounding quotes and spaces were stripped. Values are now single-quoted. A value containing `${` is refused, because dotenv would expand it as a variable.
- **The guard finds more paths and hosts.** A path after a shell separator (`cat /tmp/x;/etc/shadow`), a `uri` argument (including `file://`), and bare hosts in `host`/`hostname`/`server`/`address`/`domain`/`endpoint` arguments were not checked against the path rules and `network.allow`. They are now.
- **OAuth logins reject a response from another authorization server.** When the login callback carries an `iss` parameter (RFC 9207), it must match the expected issuer; if the server's metadata promises `iss`, a response without it is refused. This closes the mix-up attack where a second authorization server's code is accepted. The token endpoint may still be on another host than the issuer (as with Google).
- **OAuth registration and revocation endpoints must use HTTPS.** Revocation sends your tokens and registration returns a client secret; a plaintext endpoint was used as is. Such endpoints are now treated as absent (loopback excepted), also for logins saved before this change.

---

## [0.25.3] — 2026-11-22

The rest of the first external review (stdio pool lifecycle, honest timeout messages, discovery) and the fixes from a second round of reviews (Codex and Grok), including a regression in 0.25.2: `docker:` env values could steer the host Docker client. Behaviour changes: cross-origin redirects carry only a short list of safe headers and never resend a request body; MCP HTTP servers may redirect only within their own origin; a hostname that does not resolve is refused; `connect(inherit_stderr=False)` discards server output; GitHub-installed or package-less Glama launches need `confirm=True`.

### Fixed
- **`bench()` stops when a call may have run.** After an outcome-unknown reply, or a timeout that cancelled a call in flight, it sent the next iteration anyway, which repeats the call on a server that is already failing. It now stops there and says so.
- **A search with a failed registry is not cached.** A timeout in one registry left the other registries' results cached for a minute, so `auto()` kept ranking from that partial list.
- **Trust follows what a local launch fetches.** A Glama entry that is remote-capable kept Glama's trust even when it was run locally from `npx github:…` by `prewarm()` or `shapeshift(source="local")`, so it skipped `confirm=True` and the default cage. Any launch that installs from GitHub (`github:`, `git+…`) is now treated as community code, whichever registry listed it. A Glama stdio listing that names no package (launched as `npx -y <id>`) now counts as npm. The hosted endpoint keeps the listing's trust.
- **`prewarm(sandbox=True)` refuses launchers it cannot cage.** For anything but `npx`/`uvx` it started the command on the host and reported success. It now fails before launching, like `shapeshift()`.
- **`release()` removes only the process it released.** If a call started a replacement under the same key while `release()` waited for the old process to exit, the replacement was dropped from the pool and kept running untracked.
- **`connect(inherit_stderr=False)` discards server output.** It captured stderr in a pipe nobody read; a chatty server filled it and blocked mid-write, then stopped answering.
- **API-key headers and query parameters no longer follow redirects.** Only `Authorization`, `Cookie` and `Proxy-Authorization` were dropped on a redirect to another origin, so headers like `X-API-Key` went along. Only a short list of safe headers (`Accept`, `Content-Type`, `User-Agent`, …) crosses origins now. The first request's `params` were also re-sent to every redirect target, replacing the target's own query; they now go to the first URL only.
- **OAuth secrets are never POSTed to a redirect target.** Token exchange, refresh, client registration and revocation followed redirects, so a 307/308 could forward the refresh token, client secret or authorization code to another host. They no longer follow redirects.
- **A crafted tool's redirect is checked against the guard.** The guard judged only the crafted endpoint's URL; a redirect to a host outside `network.allow` was followed with the request body. Every redirect target now goes through the guard first.
- **A request body is never replayed to another origin.** A 307/308 redirect keeps the method and body, so tool arguments posted to one host could be resent to another. Such redirects are refused, both in Kitsune's request helper and for MCP HTTP servers, which now follow only same-origin 307/308 redirects (`/mcp` → `/mcp/`). The legacy SSE transport and session cleanup no longer follow redirects.
- **A hostname that does not resolve is not treated as public.** The private-address check skipped names whose lookup failed, and the connection then resolved them again. They are refused now, which removes the easiest DNS-rebinding path. A resolver that answers the two lookups differently is still possible.
- **OAuth discovery checks what metadata hostnames resolve to.** A public-looking `https` name (from `WWW-Authenticate` or a redirect) that pointed at a private address was fetched.
- **Multicast addresses are blocked.** `224.0.0.0/4` and `ff00::/8` counted as public.
- **`auto()` never repeats a call that succeeded.** The auth-failure check read the text of any result, so a successful one whose first line said "Unauthorized" or "Forbidden" (an issue title, a report) made `auto()` run the same request on another server. Only a call that failed (a Kitsune error, or a result the server marked `isError`) can trigger the fallback now.
- **`auto()` no longer re-runs the first server when the fallback lacks credentials.** Skipping a candidate without its credentials went back to the top of the loop and called the server that had just failed again. It now moves to the next usable candidate, or stops.
- **A stdio call is not resent when the pipe breaks while sending.** A failure in `drain()` can come after the server has read the request, but it triggered the reconnect-and-retry path. It now returns the outcome-unknown warning. A failure before anything was written still retries.
- **`docker:` env can no longer steer the host Docker client.** Since 0.25.2, `config.env` values are passed to `docker run` by name, so they land in the environment of the `docker` process on the host. A tool call could set `PATH` (which binary runs as `docker`), `DOCKER_HOST` (which daemon), `HOME` (its credential helpers) or `LD_PRELOAD`. Protected names (the same list `.env` writes use) and names that are not plain identifiers are now refused before anything starts.
- **Concurrent first calls to a stdio server start one process.** Two calls arriving together each spawned the server; the pool kept the last one and the other ran on with nothing tracking or stopping it. Starts are now serialised per server.
- **A server that fails during startup is stopped.** If the MCP handshake was cut short (a `connect()` timeout, a broken pipe), the child process kept running. It is now killed on every failed or cancelled start.
- **Pool eviction never kills a call in flight.** A call counted as idle from its *previous* use, so a long call could be killed by another call's idle sweep, and the process cap could pick a busy process. Busy processes are now skipped by both, and a `.env` change respawns the process on its next idle call instead of mid-call.
- **A timeout after a call was sent no longer says "try again".** An HTTP tool call that timed out was reported as "Timeout connecting… try again" even when the request had reached the server, and a stdio server that never answered got "No response". Either way the tool may have run, so a blind retry could repeat a mutation. Both now return the outcome-unknown warning. A timeout during the handshake, before anything was sent, still suggests a retry.
- **Only a reply answers a stdio request.** The reader took any message with the request's id, so a request *from* the server (sampling, roots, elicitation) that reused the id was returned as the tool's result. It now requires `result` or `error` and no `method`.
- **Tool lists are read in full.** HTTP and stdio servers that page their `tools/list` reply showed only the first page (WebSocket already followed `nextCursor`). All three now follow the cursor, up to 50 pages, and stop if a server repeats a cursor.
- **A server with no tools no longer unmounts your current one.** `shapeshift()` removed the current server's tools before fetching the new one's, so a "no tools found" failure left nothing mounted. The current server is now removed only once the new tools are known (registry and `connect()`ed servers alike).
- **PyPI servers resolve.** `search(registry="pypi")` could list a package that `shapeshift()`, `call()` and `auto()` then could not find, because the combined registry left PyPI out. PyPI is now part of it. PyPI's HTML search page serves a bot challenge to most automated clients, so search also looks up likely exact names (`mcp-server-<q>`, `<q>-mcp`, `mcp-<q>`) through the JSON API.
- **Uncurated directories in the official repo are not "official".** Every directory under `modelcontextprotocol/servers/src` was listed as an official server with a guessed package name, so it skipped the community confirm gate and the default cage. Directories outside Kitsune's curated list are now labelled `npm` or `pypi`.

---

## [0.25.2] — 2026-11-22

Security and correctness fixes from two external code reviews. Three behaviour changes: deleting `~/.kitsune/policy.json` turns the guard off only after a Kitsune restart (until then, calls wait for approval); Glama servers that install from GitHub need `confirm=True` and run in the Docker cage by default; loosening the Docker cage from a tool call needs `KITSUNE_DOCKER_ALLOW_OVERRIDES=1`.

### Fixed
- **`auto()` no longer discards a good answer that mentions 401 or 403.** Any result containing those digits (an issue title, a result count) counted as an auth failure, and `auto()` silently retried on another server and returned *its* answer. Only an error-shaped first line counts now.
- **A registry outage is no longer cached as "server not found".** If a registry timed out, the miss was cached for five minutes even though that registry might have had the server. Misses are cached only when every registry answered.
- **Your absorbed config wins over an official listing with the same id.** Both had the same rank, so the official entry (without your args and env) was used.
- **`state.json` is written atomically, mode 0600.** A crash mid-write left a truncated file, which the next start treated as empty and dropped all crafted tools and saved connections.
- **`setup(name=…)` uses the command `connect()` actually ran.** It re-split the command string, which broke quoted paths.
- **Glama listings that install from GitHub count as community code.** They run `npx github:owner/repo` locally, yet were treated as vetted (no `confirm=True`, no default Docker cage). They are now labelled `github`, so the community confirm gate and default cage apply. Remote Glama entries are unchanged.
- **`bench()` and `test(level="full")` respect the Docker cage.** Both started servers on the host even when `call()` would have caged them.
- **`docker:` calls can no longer loosen the cage from a tool call.** `call(config=…)` is agent input; it could add capabilities, make the rootfs writable or pick another network. Only `network: "none"` (tightening) is honoured now; the loosening overrides need `KITSUNE_DOCKER_ALLOW_OVERRIDES=1`.
- **Docker secrets stay off the command line.** `env` values for `docker:` servers were passed as `-e KEY=value`, visible in `ps` and in `status`. They are now passed by name and read from the process environment; the pool key holds only a digest.
- **`run()` rejects option-shaped package names.** A package like `--call=…` was handed to `npx` as an option, which runs a shell command.
- **`connect()` goes through the guard.** Launching local commands is still what it is for, but a policy can now restrict it (server `connect`).
- **Guard: both ends of a move are checked.** Keys like `source`, `src`, `target`, `from`, `to` count as paths when their value looks like one, so a move *out of* a protected location (including `~/.kitsune/policy.json`) is now caught, not just the destination.
- **Guard fails closed if its policy disappears.** A policy file that was loaded and then removed used to switch the guard off. Calls are now held for approval until Kitsune restarts; deleting the policy on purpose still turns the guard off after a restart.
- **Guard reads URL hosts with a URL parser.** A `@` in a query or fragment (`https://evil.example?x=@allowed.example`) could make `network.allow` see the wrong host, and hosts ending in a file extension (`files.zip`) were skipped. Explicit URLs are now parsed properly and always checked.
- **Crafted tools go through the guard.** Tools from `craft()` (and ones restored at startup) never consulted the policy. They are now checked as server `craft`, with the endpoint URL included so `network.allow` applies. Both code paths share one implementation.
- **Credentials no longer follow a redirect to another site.** When a request with an `Authorization` header (or cookies) was redirected to a different origin, the header went along. It is now dropped on any cross-origin hop.
- **Internal hostnames are blocked like private IPs.** The private-address check only judged literal IPs (and the request helper skipped it for the first URL, which restored crafted tools relied on), so internal DNS names, `localhost.`, `*.localhost` and shorthand loopback forms (`127.1`, `2130706433`, `0x7f.0.0.1`) passed. Hostnames are now resolved before each request (including `fetch()`'s external fetcher path) and refused if they point at a non-public address. `KITSUNE_ALLOW_LOCAL_FETCH=1` still opts out.
- **OAuth discovery follows redirects only to places it may fetch.** Each redirect hop of a metadata request must pass the same check as the first URL.
- **Legacy OAuth discovery rejects plaintext endpoints.** Servers without protected-resource metadata could advertise an `http://` token endpoint; that path now requires HTTPS (or loopback), like the modern one.
- **`release()` can remove connections saved from an earlier session.** After a restart, `connect()`ed servers come back from `state.json` as launch records with no process. `release()` searched only running processes, so it answered "No connection named …" and the record stayed in `state.json` for good. It now removes the record and saves the state.
- **`status` lists those saved connections.** They were invisible before. A new "SAVED CONNECTIONS — not running" section shows each one with `reload('name')` to start it and `release('name')` to forget it.

### Docs
- **One-click install.** "Add to Cursor", "Install in VS Code" and "VS Code Insiders" buttons in the README and the installation guide. Each opens the client with `uvx kitsune-mcp` preconfigured.

---

## [0.25.1] — 2026-11-22

### Fixed
- **`auto()` answered "what time is it in Tokyo" with local time.** `mcp-server-time` now declares `timezone` optional, with the server's own zone as the default, so Kitsune sent `{}` and returned Europe/Berlin time without any error. An optional `timezone`/`time_zone`/`tz` param is now filled when the task names a recognizable place or zone, and otherwise left to the server default.
- **`time` and `date` params no longer receive the whole question.** `convert_time(time=…)` used to get `"what time is it in Tokyo"` as its `HH:MM` value. They are now treated as structured params, like `timezone`.

### CI
- **Installs are pinned to `uv.lock`.** The test and docker-e2e jobs install with `uv sync --locked` (exact versions and hashes) instead of unpinned `pip install`, and the release build uses `uv build` instead of `pip install build`. `--locked` also fails a PR whose `uv.lock` is stale, which is what Dependabot pip bumps caused in #133/#135. The weekly canary still resolves the newest upstream releases (`--upgrade`). `pytest-cov` is now part of the `dev` extra.
- **Signed releases.** Each GitHub Release now carries the wheel, the sdist and a Sigstore bundle (`*.sigstore.json`) for each. Both release workflows build reproducibly (`SOURCE_DATE_EPOCH` = tag commit time), so the signed files are byte-identical to the ones on PyPI. Verify with `sigstore verify github --repository kaiser-data/kitsune-mcp <file>`.
- **Release-workflow hardening (zizmor).** The uv cache is off in the release paths (cache poisoning), and checkouts there no longer keep git credentials.

---

## [0.25.0] — 2026-11-21

Kitsune now runs on the mcp Python SDK 2.x (#79, #131 — thanks [@Steeve-Crypto](https://github.com/Steeve-Crypto)). mcp 2.x renamed the bundled `FastMCP` server to `MCPServer` and removed `mcp.server.fastmcp`, so a fresh install used to need the `mcp<2` pin. Breaking for anyone who pins mcp 1.x next to Kitsune: 1.x is no longer supported.

### Changed
- **mcp 2.x.** Requires `mcp>=2,<3` and `pydantic>=2.12,<2.15` (was `mcp>=1.0.0,<2` and `pydantic>=2.10,<2.15`). The server, the shapeshift registrations and the crafted tools use `MCPServer`, and prompts are unregistered through its public `remove_prompt`.
- **Hot-reload demo.** `examples/demo-hot-reload/weather_server.py` now pins mcp 2.x.

---

## [0.24.0] — 2026-11-18

Smithery is gone. Smithery, now part of Arcade.dev, shut down its API, hosted servers and API keys on 2026-10-31, so Kitsune drops its Smithery integration (#127). Search and hosted servers keep working through the official registry, MCP Registry, Glama, npm, PyPI, GitHub and direct `https://` URLs. Breaking: the `skill()` tool and the `SMITHERY_API_KEY` setting are removed.

### Removed
- **Smithery support.** Smithery, now part of Arcade.dev, shut down its API, Connect proxy, API keys and hosted `server.smithery.ai` / `*.run.tools` URLs on 2026-10-31 ([notice](https://smithery.ai/future)). Kitsune no longer searches the Smithery registry, routes calls through Smithery Connect, or reads `SMITHERY_API_KEY` (it is ignored if still set). `status()` and `onboard()` no longer list Smithery or ping it. `smithery.yaml` and the `SMITHERY_API_KEY` entries in `server.json` are gone.
- **The `skill()` tool** (full profile only). It loaded skills from Smithery's API and cannot work without it. Skills already cached in `~/.kitsune/skills.json` still show in `status()`.

**Behaviour changes to know about:**
- `search(registry="smithery")` and `shapeshift(..., source="smithery")` return a message pointing to the other registries instead of results.
- Hosted HTTP servers from any registry are reached at their own URL; a 401 starts the OAuth login as for any direct URL.
- Registry entries whose hosted URL is on Smithery (`server.smithery.ai`, `*.run.tools`) are left out of `search()` and lookups. The MCP Registry still lists hundreds of them (`ai.smithery/*`), and they all return 404 now.
- A server id that no registry knows and that is not a URL now fails with "not found in any registry". Before, Kitsune guessed it was hosted on Smithery.

---

## [0.23.0] — 2026-11-08

Wire-correct: the first milestone on the road to 1.0. The HTTP, legacy SSE and WebSocket transports now follow the protocol (#107, #109, #110). Public HTTP servers connect without a login, and logins follow the current MCP authorization spec (#112). Mounted tools keep their exact schemas, arguments and results (#113). MCP Registry entries parse again and search covers the whole registry (#111). Also: CodeQL fixes (#114) and an animated README logo (#108).

**Behaviour changes to know about:**
- Tools mounted with `shapeshift()` return the downstream result as sent (structured content, `isError`, images) instead of cleaned, truncated text. The hub's own `call()` tool still returns text.
- A downstream tool call that may already have run is never sent again; Kitsune reports "outcome unknown" instead. This now also applies to HTTP, legacy SSE and WebSocket servers.
- Direct HTTP servers get no token until they ask for one with a 401. Logins stored by older versions move to the new per-URL storage on first use; no new login is needed.

### Fixed
- **Two CodeQL findings.** HTML-to-text extraction now uses the standard library's HTML parser. Before, a regex missed end tags like `</script >` and `</SCRIPT>`, so script contents could show up in fetched page text. The Glama adapter now checks the parsed host of a repository URL instead of searching the URL text for `github.com`, which also matched URLs like `https://evil.example/github.com/…`.
- **`initialize` reports Kitsune's version.** `serverInfo.version` was the mcp SDK's version (`1.30.0`) instead of Kitsune's.
- **Streamable HTTP responses are read the way the spec allows.** SSE streams are read as they arrive, and the response is matched to the request by its JSON-RPC id. Before, Kitsune took the first event on the stream, so a progress or log notification sent ahead of the result was mistaken for it. Server-to-client requests on the stream now get an answer (`ping` succeeds, everything else is "method not supported"), so the server never hangs waiting for one. Plain `application/json` replies and batch payloads also work.
- **HTTP sessions are shared under concurrency (closes #66).** Concurrent calls to the same server now share one session and one `initialize`, where before each made its own handshake. Stateless servers, which issue no session id, keep their handshake too. Sessions last at most 30 minutes, at most 64 are cached, and Kitsune closes a session it drops with `DELETE`.
- **MCP Registry entries parse again.** The adapter read the old field names (`registry_name`, `name`, `environment_variables`), so current entries got no install command and no credentials. It now reads `registryType`, `identifier` and `environmentVariables` from the `/v0.1` API, with the old names as a fallback. Each entry's version goes into the command (`npx -y pkg@1.2.3`, `uvx pkg==1.2.3`), so Kitsune's pinning records it, and fixed `packageArguments` are kept. Only the latest version of each server is listed; before, every published version appeared. Deleted entries are skipped, and so are entries Kitsune can't run (Docker or mcpb packages only, or a remote URL with `{variables}` to fill in).
- **MCP Registry search covers the whole registry.** Search used to look only at the first 500 entries (alphabetical, mostly `ai.*`). It now also queries the registry for each word of the query, and lookups by exact name ask the registry directly.

- **Public HTTP servers connect without a login.** Before, every direct HTTP server had to publish OAuth metadata, so public servers were refused with "Cannot reach". Requests now go out without a token unless a login is stored, and only a 401 or 403 starts the login.
- **OAuth discovery follows the current MCP authorization spec.** The login starts from the server's `WWW-Authenticate` challenge and its protected-resource metadata (RFC 9728), so an authorization server on another origin is found. GitHub's MCP server is one example: its authorization server is `github.com/login/oauth`, which the old lookup at the server's own origin never found. Servers without that metadata still work as before. Kitsune only accepts authorization-server metadata that names the issuer it was fetched from, and only HTTPS endpoints. Logins send the server as a `resource` indicator (RFC 8707) and request its scopes, and an `insufficient_scope` challenge asks for a new login with more scope.
- **Logins are stored per server URL, and refreshed once.** Two servers on one host no longer share a token. Logins stored by older versions under the bare hostname move to the new location on first use, so nobody has to log in again. Concurrent calls wait for one refresh instead of each refreshing, which used to invalidate a rotated refresh token and force a new browser login.
- **`auth('<server>')` on a server without OAuth** now says no login is needed, instead of "OAuth failed".

- **Mounted tools keep their exact schema.** `shapeshift()` used to rebuild each downstream tool's parameters from a few basic JSON types. That lost enums, descriptions, nested objects, `$defs` references and unions, and nullable parameters raised `TypeError`. Kitsune now advertises the downstream `inputSchema` and `outputSchema` unchanged, together with `title`, `annotations` and `_meta`. Clients therefore see the same parameters as when connecting directly, and arguments are checked against the real schema. A schema that `jsonschema` can't use falls back to a plain object schema instead of making the tool uncallable.
- **Arguments are forwarded as sent.** An explicit `null` reaches the server instead of being dropped. Path arguments are resolved through symlinks only for local stdio servers; caged (Docker) and remote servers have their own filesystem, so their paths are left alone.
- **Results come back as the server sent them.** Mounted tools return the downstream `CallToolResult` with `isError`, `structuredContent`, images, resource links and `_meta`. Before, everything was flattened into cleaned, truncated text, and errors looked like successes. Kitsune-side failures (such as "outcome unknown") are returned with `isError: true`. The hub's own `call()` tool still returns its text summary.
- **Downstream tool names that clash are reported.** A downstream tool whose name is already registered now shows up as a failed registration instead of being reported as mounted.

### Added
- **Fallback for old HTTP+SSE servers.** Kitsune now also connects to servers that still speak the 2024-11-05 HTTP+SSE transport. When such a server rejects the `initialize` POST with 400, 404 or 405, Kitsune opens its GET event stream as the spec says, and responses on that stream are matched by request id. The `endpoint` event must name a URL on the server's own origin, so the bearer token is never sent to another host.
- **WebSocket replies are matched by request id.** Before, Kitsune ignored the `initialize` reply and took the next frame as the tool result, so a notification could be returned as the answer. It now checks `initialize` (the reply must carry a `protocolVersion`), skips notifications and frames that aren't JSON, and answers server requests. A connection lost after the call was sent reports "outcome unknown". `WebSocketTransport.list_tools()` is new and follows pagination cursors, so `shapeshift()` can discover tools on `ws://` servers. The docs now say WebSocket is a custom transport, not a spec one.
- **Fixture-server tests.** A new test file runs the HTTP transport against real mcp SDK servers on localhost: Streamable HTTP with SSE responses, Streamable HTTP with JSON responses, stateless Streamable HTTP, legacy HTTP+SSE, and a WebSocket server. The test tool sends progress and log notifications before its result.

---

## [0.22.8] — 2026-11-07

Hot-path performance (#102), type checking (#105), supply-chain hardening (#104), docs for clients with tool deferral (#100), and repo cleanup (#101).

### Changed
- **`.env` files are re-read only when they change.** Every `call()`, every `search()` result row and every `auto()` candidate re-parsed all `.env` files; now a stat of `(mtime_ns, size)` decides (2.4 ms → 4 µs per check).
- **Large responses are cut before cleaning.** Four regex passes ran over the whole payload before truncating to ~6,000 characters (1.5 MB response: 20 ms → 0.6 ms, same output).
- **`call()` on the mounted form skips the registry lookup.** It reuses the record `shapeshift()` resolved, instead of fanning out to 7 registries whenever the 5-minute server cache had expired.
- **`search(registry=…)` keeps one instance per registry**, so the npm and PyPI result caches hit between searches.
- **`status()` doesn't wait on busy servers.** A server with a call in flight shows `alive+busy` instead of stalling `status()` up to the 30 s tool timeout; memory checks run off the event loop.

- **Type-checked.** mypy runs in CI and the wheel ships `py.typed`. A child process without a stdin pipe now raises a clear error, and a cancelled registry lookup is recorded as that registry's error instead of breaking the search loop (#105).

### Security
- Every GitHub Action is pinned to a commit SHA, workflows default to read-only tokens, and an OpenSSF Scorecard workflow runs weekly (#104).

### Docs
- Issue templates are now forms, with questions routed to Discussions and vulnerabilities to private advisories. `CODEOWNERS`, `.editorconfig` and a pre-commit config were added (#104).
- Token cost is stated per client: ~1,774 tokens/turn where every tool schema loads up front, ~70 on Claude Code with Tool Search (measured on 2.1.319).
- Removed unreferenced diagrams and finished planning docs; the README architecture diagram no longer carries a stale version label.

---

## [0.22.7] — 2026-10-31

Hot-reload reliability (#94) and a release-pipeline fix (#93).

### Fixed
- **`uvx --from .` doesn't reload your code.** uv builds a local project once and keeps serving that cached build, so `reload()` restarted the old code (measured on every source edit). The docs now use `uv run my-mcp-server`, which installs the project editable, and `connect()`/`reload()` warn when they see `uvx --from <local path>` without a refresh flag.
- **`reload()` recovers from a failed restart.** A restart that failed (say, a syntax error) dropped the connection record, so the next `reload("dev")` answered "No connection named 'dev'". The record is kept and `reload()` starts it again. Custom `timeout` and `inherit_stderr` from `connect()` now survive a reload, and a failed remount is reported as one instead of "remounted".
- **Prompt proxies call their own prompt.** With two or more prompts mounted, every proxy called the last one.
- **OAuth login messages go to stderr.** They were printed to stdout, the MCP server's protocol channel on stdio.

### Added
- End-to-end test: edit a real server's source, `reload()`, and check the new code runs.

### Changed
- Release pipeline: the MCP Registry job waits until npm and PyPI serve the exact `server.json` versions (#93), instead of failing with "version not found" and needing a manual rerun.

---

## [0.22.6] — 2026-10-31

Security and reliability fixes from a code review (#90).

### Fixed
- **No `.env` injection through credential values.** A value containing a newline, CR or NUL could add extra lines to `~/.kitsune/.env`, such as `KITSUNE_SANDBOX=off`, getting past the protected-variable check. `key()`, `auth()` and `auto(keys=)` now refuse such values and invalid variable names; credential harvesting skips them.
- **Schema discovery uses the Docker cage.** `auto()` and `test()` started a community package uncaged just to read its tool list, and only applied the sandbox policy to the call afterwards. Discovery now follows the same policy as execution.
- **Tool calls are never replayed when they may already have run.** Over HTTP, a call on a cached session was sent again after a read timeout, a dropped connection, a 5xx, or a response that wasn't SSE. Servers that answer with plain JSON, which Streamable HTTP allows, ran every call twice. Responses are now read as SSE or JSON, and a call is only re-sent when the server provably never ran it (connection refused, or the session rejected with 400/404). Over stdio, a call is no longer re-sent to a new process when the old one died after receiving it. In both cases Kitsune now reports that the outcome is unknown. Read-only requests such as `tools/list` still retry.
- **Mount and unmount no longer stop the wrong process.** `shapeshift()` with no arguments could kill the process of a server mounted while it was sending its notifications. Mounting a `connect()`ed server now takes the same lock as a registry mount.

### Changed
- **Behaviour:** a lost tool call now returns "outcome unknown, the call may have run" instead of retrying silently.
- Docs and package descriptions say clearly that Docker is optional: hot-reload never uses it, it only cages community packages when installed.
- README badge reads "Awesome MCP Servers: listed".

---

## [0.22.5] — 2026-10-30

### Fixed
- **HTTP/Smithery servers reuse their MCP session** (#66). Every `call()` and tool listing used to run the full initialize handshake and drop the `mcp-session-id`, costing two extra round-trips per call and a new upstream session each time. Sessions are now cached per endpoint, keyed by the bearer token and config, so a token refresh or changed credentials start a new one. A rejected session (404/400, network error) falls back to one fresh handshake; 401/403 keeps the existing auth handling. Servers without a session id stay stateless.
- JSON-RPC request ids are unique within an HTTP session (were always `2`).

### Added
- README: PyPI and npm download badges.
- `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1).

---

## [0.22.4] — 2026-10-19

Docs and packaging only; no runtime changes.

### Added
- **Docs site and homepage** at https://kaiser-data.github.io/kitsune-mcp/ (MkDocs Material, deployed from `main`). PyPI's Homepage/Documentation links, npm's `homepage` and the registry's `websiteUrl` now point there.
- **Hot-reload demo GIF** at the top of the README: a real Claude Code session, 59°C → fix → `reload("dev")` → 15°C, 31 s.

### Changed
- **Docs checked against the real tool surface.** The tools reference is regenerated from the registered signatures and adds the missing `reload`, `compare`, `onboard` and `setup`, with lean vs full profile marked. Quickstart and agent patterns had `call()` arguments in the wrong order and used `shiftback()`, which only exists in the full profile.
- **Shorter, plainer copy** on the README, homepage, hot-reload tutorial and quickstart.
- The demo server pins mcp 1.x in PEP 723 inline metadata, so `uv run weather_server.py` just works.
- Makefile uses uv; CONTRIBUTING describes the real `kitsune_mcp/` layout.

### Removed
- Internal plans, drafts and the unrelated `evals/` framework from the public repo; the stale `agent_manifest.json`.

---

## [0.22.3] — 2026-10-18

### Added
- **Star hint.** The README (also the PyPI page) asks for a GitHub star under the hero and shows a stars badge. The first time `kitsune-mcp` starts it prints a one-line star hint to stderr, once, recorded in `$KITSUNE_HOME/.first_run_done`. stdout stays the clean MCP channel.

### Changed
- The `kitsune-mcp` console script now points at `server:main` (was `server:mcp.run`).

### Removed
- The Smithery badge: the listing returns 404 and the badge image 500.

---

## [0.22.2] — 2026-10-12

### Fixed
- **The first `call()` no longer kills a `connect()`ed server.** The `.env` change detector started from an empty baseline, so its first check always counted as a change and respawned every pooled process. The respawned process also lost its `connect()` name, so `reload("dev")` and `release("dev")` reported "No connection named 'dev'" after any call.
- **Every respawn keeps the `connect()` name**: after a `.env` change and after the process dies mid-call, so `reload` and `release` still find it.
- **`~/.env` is loaded at startup**, so a key that only lives there reaches `connect()`ed servers without depending on a respawn.
- **`call()` on a `connect()` alias stays local.** It used to look the alias up in the registries, so an unrelated npm package named e.g. `dev` lent your server its credential requirements and a `[source: npm]` label. Only live connections count (rows restored from `state.json` are skipped), and a live `connect()` alias wins over a mounted server with the same name.

### Added
- `examples/demo-hot-reload/`: a weather server with one planted bug and a shot list for recording the agent fixing it with `reload`.

### Docs
- The safety docs no longer claim `connect()` requires `confirm=True`. It runs your command as your user, with no consent gate and no cage.
- README rewritten around the MCP REPL (edit → `reload` → `call`): 469 → 172 lines, one-line `claude mcp add` install, lean tool table now lists `connect` / `release` / `reload`.
- Detail moved out of the README into `docs/safety.md`, `docs/configuration.md` and `docs/performance.md`.
- One tagline across `pyproject.toml`, `package.json`, `server.json` and `smithery.yaml`; the Smithery tool list now matches the lean profile.
- Internal plans and reports moved from the repo root to `docs/internal/`. Dead Discord invite removed.

---

## [0.22.1] — 2026-10-01

### Fixed — guard approval prompts could hang, and IPv6 URLs were misread

- An approval prompt now times out after 2 minutes and counts as a no. Some
  clients never render the form and leave the request open, which stalled the
  tool call.
- Clients that don't advertise elicitation (e.g. Claude Desktop) are no longer
  sent a prompt. The call is refused right away, with a hint to allow the tool
  in the policy.
- `http://[::1]:8080/` was read as the host `[` and blocked even when `::1` was
  allowed. Bracketed IPv6 literals are now parsed.

### Fixed — guard read URL paths in commands as file paths

In free-text arguments only a URL's scheme and host were stripped, so
`curl https://pypi.org/simple/` produced the path `/simple` and could fail the
write-root check. The whole URL is now removed before paths are extracted.

---

## [0.22.0] — 2026-10-01

### Security — tool calls can no longer switch off Kitsune's own safety gates

`auth()`, `key()` and `auto(keys=)` wrote any env var the agent named, into
both `~/.kitsune/.env` and `os.environ`. That let a prompt-injected agent set
`KITSUNE_TRUST=community` (skip the trust gate), `KITSUNE_SANDBOX=off` (skip the
Docker cage) or `KITSUNE_ALLOW_LOCAL_FETCH=1` (SSRF). The trust-gate message even
suggested `auth("KITSUNE_TRUST", "community")`. Because unsandboxed stdio servers
inherit the environment, launch levers (`NODE_OPTIONS`, `LD_PRELOAD`,
`PYTHONSTARTUP`, `BASH_ENV`) and supply-chain levers (`PIP_INDEX_URL`,
`NPM_CONFIG_REGISTRY`, `DOCKER_HOST`, proxies, CA bundles) were reachable too.

`_save_to_env` now refuses every `KITSUNE_*` name and those levers
(`credentials.is_protected_env_var`); the tools return a "protected variable"
message and `setup(action="harvest")` skips them. The hints now tell the user to
set `KITSUNE_TRUST` by hand. Ordinary credentials (`GITHUB_TOKEN`, `*_API_KEY`,
`DATABASE_URL`) are unaffected.

### Added — action guard (opt-in, stage 1)

New `kitsune_mcp/guard.py`: a policy check in front of every downstream tool
call, off unless `~/.kitsune/policy.json` exists. Deterministic rules only in this
release: per-server tool `allow`/`ask`/`deny` globs, read/write path roots with
symlinks resolved, a host allowlist (URLs, `git@host:`, IPs, hosts after network
commands), opaque encoded payloads, and always-denied credential paths plus
`~/.kitsune`. `ask` uses MCP elicitation, so only the user can approve. `monitor`
mode (default) logs to `~/.kitsune/guard.log.jsonl` without blocking; an invalid
policy fails closed. `status()` shows the guard's mode and tally. The classifier
stage (a calibrated decision model asked a permission question, with the policy as state) is
specified but not wired; until then, calls it would decide ask the user.

---

## [0.21.1] — 2026-09-07

### Fixed — `pip install kitsune-mcp` was broken by mcp 2.x

The `mcp` dependency had no upper bound, so a fresh resolve picked up mcp 2.x,
which renamed the bundled FastMCP to `MCPServer` and removed
`mcp.server.fastmcp` — imported by `app.py`, `shapeshift.py` and
`tools/shapeshift.py`. Every fresh install died at import:

```
$ kitsune-mcp --help
ModuleNotFoundError: No module named 'mcp.server.fastmcp'
```

Now pinned `mcp>=1.0.0,<2`; the upper bound is load-bearing until a deliberate
v2 migration. Three things had hidden it: `uv.lock` was gitignored so CI
resolved fresh every run, local virtualenvs held older pins, and `test.yml`
triggered only on push/PR — CI had not run since the previous release.

### Fixed — the wheel shipped the entire repo into `site-packages`

`packages = ["."]` silently made the `include` list a no-op, so the wheel
carried `tests/`, `docs/`, `evals/`, `examples/`, `bin/`, `.github/`,
`.gitignore`, `Makefile` and the `plan_*.md` files — installing them at the
root of the user's `site-packages`, where top-level `tests/` and `docs/`
collide with any other package doing the same. The wheel now ships only the
package plus the two entry-point shims: **203 entries / 469K → 35 / 122K**.

### Fixed — `websockets` was an undeclared dependency

The WebSocket transport (`ws://` / `wss://`) imports `websockets`, and three
test modules patch `websockets.connect`, but it was declared nowhere — it was
present only as a transitive dependency of `fastmcp`. Removing that unused
package (never imported anywhere; the code uses the mcp SDK's *bundled*
`mcp.server.fastmcp`, a different project) exposed the gap.

### Added — `[ws]` extra

`pip install 'kitsune-mcp[ws]'` installs the WebSocket transport's dependency.
It stays optional because the production import is lazy and degrades with a
clear message; the runtime hint now names the extra. `websockets` is also in
`dev`, so the suite exercises the transport instead of failing on it.

### Added — `uv.lock` is committed

Reproducible dev and CI environments. Previously gitignored, which is why
every CI run re-resolved dependencies from scratch.

### Changed — lint the whole repo, enforce formatting, weekly upstream canary

- `ruff check .` replaces four hand-listed paths. `evals/`, `examples/` and
  `.github/scripts/` had been outside the lint scope and accumulated 37
  errors; all fixed. Two were `B023` loop-variable captures (in
  `examples/benchmark.py` and the race-condition grader's thread stress
  harness) — latent rather than active, since both closures ran within the
  same iteration; benchmark output verified byte-identical. The `SIM115` in
  the hang-watcher's tailer got a documented `noqa`: that handle must outlive
  its block by design.
- `ruff format --check` is now enforced, and the tree was formatted to match
  (75 files, in a separate commit).
- `test.yml` gains a weekly `schedule` and `workflow_dispatch`. The job
  installs unpinned, so a scheduled run catches an upstream break like the mcp
  2.x one before a user does.

### Docs — remount lean floor to v0.21.0 measured (~1,774 / ~3,561)

PR C's tri-state `sandbox` docstring grew `shapeshift`'s schema cost; live
`python examples/benchmark.py` now reads lean **1,774** / forge **3,561**
(was ~1,685 / ~3,396 at the 0.21.0 cut). Regenerated every live reference:
README savings table, `docs/benchmarks.md`, article / demo-script /
linkedin_post, `server.py` docstring, token-cost + architecture SVGs.

Also closed the deferred hygiene backlog: rewrote `examples/test_session.md`
(lean + `reload` + default cage), stripped stray Chameleon/`receive` from
`docs/compatibility.md` + `docs/transports.md`, modernized issue templates,
and synced `kitsune-dev` / `kitsune-gateway` skills (prefer `reload`, lean
REPL + default cage + ~1,774 floor).

---

## [0.21.0] — 2026-07-23

### Added — lean MCP REPL: `connect` / `release` / `reload` in the default profile

The pitch's headline developer loop (edit → reload → test in one session) was
forge-only, so it was unreachable on a default `pip install`. The REPL trio now
ships in the lean profile:

- `connect`, `release`, and the new **`reload(name)`** are in `_LEAN_TOOL_NAMES`.
  `reload` folds the manual release → connect → shapeshift cycle into one call:
  it kills the stale process, restarts the stored launch command as fresh code,
  and remounts so the client sees the new schemas — removing the "connect handed
  back the old process" footgun (it always releases first).
- Lean floor rises 6 → 9 tools (~1,358 → ~1,685 tokens); still additive on Tool
  Search clients — this is reachability, not a token-savings claim.

### Added — works-now signal on `search()` and demo/onboarding hygiene

- Each `search()` result row now ends with ` | ready: high|mid|low` — a no-probe
  heuristic (`_works_now_label` over `registry._works_now_score`: creds resolved
  + source tier + local transport) so it's obvious which hits run without setup.
- `onboard()`'s 3-step check ends with `shapeshift()` (lean unmount) instead of
  the forge-only `shiftback()`, so the copy-paste check is correct in both
  profiles.
- Rewrote `examples/demo_wow.md` (dropped legacy Chameleon/`receive`/`cast_off`
  and the token-savings framing; lean-only session across the three pillars) and
  realigned `docs/demo-realtime.md` Act 1 to the lean `reload` loop.

### Added — sandbox-by-default on the exec paths (`auto()` / `call()` / `run()`)

`shapeshift(sandbox=True)` was opt-in, but the "magic" execution paths still
spawned community npx/uvx processes uncaged: `auto()` (the model picks the
server), ad-hoc `call()`, and `run()`. These now cage low-trust / unknown-source
local stdio servers by default, **best-effort**:

- Docker present → the launch is wrapped in the same hardened `docker run`
  profile automatically (credential names forwarded value-less, as with
  `sandbox=True`).
- Docker absent → the server still runs (uncaged) and the result carries a
  one-line nudge to install Docker — these paths never hard-fail on a missing
  daemon (unlike `shapeshift(sandbox=True)`, which the user asked for explicitly).
- High-trust registry sources (official / absorbed / mcpregistry / smithery /
  glama) are **not** caged by default; an explicit `KITSUNE_SANDBOX` policy
  still applies on top. Pooled `shapeshift` forms reused by `call()` keep the
  policy `shapeshift()` already applied.
- New helpers in `kitsune_mcp/tools/_state.py`
  (`_sandbox_default_for_exec`, `sandboxed_stdio_transport`,
  `transport_for_exec`); no tool-schema change. 14 new tests.

### Changed — `shapeshift`/`prewarm` cage low-trust sources by default (tri-state `sandbox`)

The mount path now matches the exec paths: community `npm`/`pypi`/`github`
mounts cage automatically instead of only when the model remembered
`sandbox=True`. `shapeshift(..., sandbox=...)` is now tri-state:

- `sandbox=None` (default) → policy decides: low-trust / unknown sources cage in
  Docker when it's present, medium/high-trust registry sources don't.
  **Best-effort** — Docker missing runs uncaged with a nudge note (never
  hard-fails).
- `sandbox=True` → force the cage; still **hard-fails** if Docker is missing or
  the launcher isn't npx/uvx (the user asked explicitly).
- `sandbox=False` → the per-call escape hatch (run uncaged).

- `prewarm()` gained the same tri-state `sandbox` param and default cage, so a
  warm community process isn't left uncaged and then reused by a later `call()`.
- `KITSUNE_SANDBOX=off` is the session-wide escape hatch (turns off the default
  cage everywhere — mount and exec paths).
- Community trust-gate copy now teaches the default cage + `sandbox=False` opt-out
  instead of prompting for `sandbox=True`; README Safety section unified around
  "caged by default when Docker is present". New resolver `_sandbox_for_mount`;
  tests across all three states + Docker present/absent.

### Added — trust-on-first-use (TOFU) version pinning

Resolution-time pinning (`pkg@1.2.3`) makes one session reproducible but
"latest" still drifts across sessions, so the same `shapeshift()` could
silently execute a newer — possibly hijacked — release later. TOFU closes that:

- The first mount of an npm/PyPI server records its exact version in
  `~/.kitsune/pins.json` (atomic, `0600`). Later mounts reuse the pinned
  version and, on drift, launch the pinned version while surfacing
  `⚠️ pinned to X, registry now offers Y` in the shapeshift output.
- `KITSUNE_REPIN=1` adopts the newer version and updates the pin.
- Applied before `server_args` and before the Docker sandbox wrap, so the
  pinned version is what actually launches on host or in the container.
- Honest limits (documented): pins a version, not a content digest;
  `github:` targets and hand-written `connect()` commands carry no version and
  pass through unpinned. New module `kitsune_mcp/pins.py`; no tool-schema
  change (policy via env, like `KITSUNE_TRUST`/`KITSUNE_SANDBOX`).

### Added — Docker sandbox for local npm/PyPI servers (`sandbox=True`)

The hardened Docker profile was previously reachable only via explicit
`docker:` image IDs — npm/PyPI servers still ran as raw host subprocesses.
Now the profile applies to them too:

- **`shapeshift(server_id, sandbox=True)`** wraps the local `npx`/`uvx` launch
  in the locked-down `docker run` profile (`--cap-drop ALL`, read-only rootfs,
  `--pids-limit`, `--memory`, no host filesystem). `npx`/`uvx` caches are
  redirected to the container tmpfs so the read-only rootfs doesn't break
  first-run package download.
- **Secrets never enter the argv.** Credential env vars are forwarded by NAME
  only (`docker -e KEY`) — declared credentials plus the same host-var
  heuristic `inspect()` probes use. Values stay out of `ps` output and the
  process-pool key.
- **`KITSUNE_SANDBOX` session policy:** `community` sandboxes every low-trust
  (npm/pypi/github) mount automatically; `all`/`1` sandboxes every local mount.
- **The community trust gate now teaches the safer path** — it offers
  `confirm=True, sandbox=True` alongside plain `confirm=True`.
- Pre-flight checks fail fast (before the current form is shed) when Docker is
  missing, the server is HTTP-hosted, or the launcher isn't npx/uvx.
- New constants `SANDBOX_NPM_IMAGE` (node:22-slim) / `SANDBOX_PYPI_IMAGE`
  (astral-sh/uv python3.13); `DockerTransport` and the sandbox share one
  `_hardened_docker_flags()` profile builder.

### Security — hardened Docker profile + default version pinning

Responds to an external review noting that "an isolated OS subprocess is not a
sandbox" and that execution was unpinned.

- **DockerTransport is hardened by default.** Every `docker run` now adds
  `--pids-limit 512`, `--security-opt no-new-privileges`, `--cap-drop ALL`, and
  `--read-only` with a writable `--tmpfs /tmp`. Per-call opt-outs: `writable`,
  `cap_add`, `network`, `pids_limit`, `memory`.
- **npm/PyPI versions are pinned at resolution.** `NpmRegistry.get_server` and
  `PyPIRegistry.get_server` now emit `npx -y pkg@<version>` / `uvx pkg==<version>`
  using the exact version the registry reports, so a later run can't silently
  pick up a newer release. Falls back to the bare name when no version is known.
- **Docs:** README "Safety & sandboxing" → "Safety model", split into what it
  does and does not protect against; `confirm=True` documented as a
  model-settable signal, not a human-approval boundary. New `docs/demo-realtime.md`.

### Tests/CI — Docker-independent suite + real-container E2E job

Sandbox-by-default made three tests silently depend on whether the HOST has
docker on PATH (green on a docker-less dev machine, red on CI runners, which
ship Docker). Fixed and made structural:

- Autouse conftest fixture forces `shutil.which("docker")` → `None` suite-wide;
  tests that fake Docker present still patch within their own scope, and tests
  that need the real daemon opt out via the new `real_docker` marker.
- New `docker-e2e` CI job runs `tests/test_docker_e2e.py` against the runner's
  real daemon (gated by `KITSUNE_E2E_DOCKER=1`): a sandboxed
  `uvx mcp-server-time` serves a real tool call through the hardened wrap, and
  `transport_for_exec` cages a low-trust npm server end-to-end — closing the
  "container E2E deferred" gap from the sandbox PRs.
- The job's first run caught a real bug the mocked tests couldn't: Docker's
  default `--tmpfs` options include `noexec`, so npx/uvx could download a
  server into `/tmp` but never execute it (`Permission denied (os error 13)`)
  — every real sandboxed launch was broken. The sandbox wrap now mounts
  `/tmp:rw,exec,nosuid,size=512m`; `DockerTransport`'s scratch tmpfs keeps the
  stricter noexec default (its server ships in the image).

---

## [0.20.8] — 2026-05-24

### Fixed — #44 completed for Smithery servers (thin registry schemas)

v0.20.7 fixed the `shapeshift()` call-example hint for official/stdio servers
but Smithery mounts still showed `arguments={}`. Root cause: Smithery's
registry listing returns `inputSchema` with `type`/`properties` but **omits the
`required` array**, so neither the registered proxy nor the hint knew which
params were mandatory.

- New `_schemas_missing_required()` detects the thin shape (properties present,
  no `required` on any tool).
- `_commit_shapeshift`'s mount path now refetches the live schema via
  `transport.list_tools()` when the registry listing is thin — for both stdio
  and HTTP transports. This corrects **both** the registered proxy schema (so
  the model itself fills required params) and the printed call hint.
- Verified live: `@upstash/context7-mcp` registry listing has `required: None`;
  after refetch, `resolve-library-id` carries `required: ['query', 'libraryName']`.

### Docs

- README baseline framing rewritten to be explicit that Kitsune is itself an
  always-on MCP server with a fixed ~1,321-token floor that never drops to
  zero. Added a break-even note (a single sub-1,321-token server is cheaper
  always-on) and recomputed the Performance tables, which still used a stale
  500/965 base.
- Added `NEXT.md` tracking remaining work (PyPI publish still blocked on a
  mis-scoped token; #43 logout pending live OAuth verification; #34 auto()
  capability filter).

---

## [0.20.7] — 2026-05-16

### Fixed

- **#43 — `auth(name, "logout")` did not actually log the user out.** Local
  token deletion still happened, but the IdP's session cookie meant the next
  `auth()` silently re-issued a token with no browser flow visible. Logout now:
  - Calls the IdP's RFC 7009 revocation endpoint (when advertised via
    `revocation_endpoint` in `.well-known/oauth-authorization-server`) to kill
    the refresh token server-side, then
  - Arms a per-origin force-login flag that the next `ensure_token()` consumes
    by appending `prompt=login` to the authorization URL (OIDC §3.1.2.1) —
    so the IdP must re-prompt even if a valid session cookie exists.
- **#44 — `shapeshift()` hint showed `arguments={}` for tools with required
  params.** Beginners hit a schema-validation error following the hint
  verbatim. The hint now populates every required parameter with a typed
  placeholder (from `_PARAM_EXAMPLES` or a type default), so the printed
  call shape is always valid.
- **#45 — Alarming "⚠️ Could not identify the backing process" warning on
  every HTTP unmount.** Warning was gated on `has_process is not False`,
  which fired for both the genuine stdio-lost-its-key case AND for HTTP
  transports (where `False` is the by-design value). Now gated on
  `has_process is True` — silent no-op for HTTP/SSE, warns only for the
  truly unexpected stdio case.

### Changed

- **#42 — `status()` "Saved vs always-on" counter now sums measured schema
  costs across every server shapeshifted this session, not just inspected
  ones.** Previously the counter only grew via `inspect()`, which doesn't
  exist in the 6-tool lean surface, so the figure under-reported by orders
  of magnitude. New session stat `tokens_avoided_shapeshift: {server_id →
  tokens}` keyed by server to avoid double-counting re-mounts. Rendered
  alongside the legacy inspect figure in `status()`.

### Tests

- 5 new tests for the OAuth logout flow: revocation endpoint discovery,
  RFC 7009 POST shape, no-endpoint short-circuit, `logout()` end-to-end,
  and force-login flag consumption. 600 total tests pass.

---

## [0.20.6] — 2026-05-16

### Fixed — Process-tree termination on unmount (zombie leak)

`shapeshift()` (unmount) and pool eviction were only killing the immediate
`uvx`/`npx` wrapper, orphaning the actual MCP server child. Every shapeshift
cycle leaked one zombie process. Confirmed with `ps`: after `shapeshift()`,
the wrapper PID was gone but its Python child kept running indefinitely.

- Each subprocess is now spawned with `start_new_session=True` (POSIX) /
  `CREATE_NEW_PROCESS_GROUP` (Windows) so the whole tree shares a process
  group.
- New `_kill_process_tree()` helper sends `SIGKILL` to the negated PGID on
  POSIX (`os.killpg`) and `CTRL_BREAK_EVENT` on Windows, then falls back to
  `proc.kill()`. Short-circuits on already-reaped processes.
- All `proc.kill()` callsites that close pool entries now route through the
  helper: atexit cleanup, idle eviction, LRU cap, `.env` rotation, `release()`,
  `shiftback()`, `inspect()` probes, and reconnect retry.
- Live verification: cold start → 4 procs (wrapper + Python child + prior
  leftovers); after `shapeshift()` unmount, the whole tree for the current
  shapeshift is gone instead of just the wrapper.

### Docs — Honest token cost numbers across README and graphics

Audit found stale "~965-token baseline" and "~500 tokens at rest" claims
predating the v0.20.5 TDQS rebuild. Updated to live-measured values
(`examples/benchmark.py`):

- README savings table baseline `965` → `1,321`; recomputed percentages
  (GitHub: 70% → **62%**; 3-server: 81-85% → **74-81%**; 5-server: 88-95% →
  **89-94%**).
- `docs/token-cost-{light,dark}.svg`: kitsune bar values 800/1,190/2,450 →
  1,621/1,921/2,221; savings labels and bar heights re-laid to match.
- `docs/architecture-{light,dark,base}.svg`: "~500 tokens at rest" → "~1,321
  tokens at rest"; version label v0.20.1 → v0.20.6.
- "Five tools at rest" → "Six tools at rest" (lean profile is 6).

---

## [0.20.5] — 2026-05-16

### Fixed — TDQS Behavior/Usage/Completeness scoring for `call` and `search`

Glama's per-tool TDQS scorecard graded `call` at C (2.9/5) and `search` at B
(3.1/5) — both penalized for thin Behavior, Completeness, and Usage Guidelines
sections. The other 4 lean-profile tools (`status`, `shapeshift`, `auth`,
`auto`) scored A and remain untouched.

This release enriches **only** `call` and `search` with:
- 4-line "Returns / Behavior / Side effects" block
- 2-line "Use when / Avoid when" guidance
- 2-3 worked examples
- `Field(description=...)` on every non-obvious parameter

Cost: `call` 188 → 345 tok, `search` 129 → 328 tok. Lean profile total
965 → **1,321 tok**. Still well under the 3,654-token v0.20.2 explosion,
still 70-95% cheaper than always-on for any non-trivial multi-server config.

### CI — release workflow no longer "fails" on Glama display

`npm` and `mcp-registry` publish jobs are now `workflow_dispatch`-only (with
explicit `publish_npm` / `publish_registry` boolean inputs). PyPI is the
release source of truth on tag push and never fails. The two optional
targets require a one-time setup (Trusted Publisher on npmjs.com, both
ecosystems live for MCP Registry) and so are gated to manual invocation
rather than silently soft-failing every release.

This keeps the "Publish Release" workflow status fully green on tag push —
no more half-red "1 of 3 jobs failed" display on Glama or in the Actions UI.

---

## [0.20.4] — 2026-05-16

### Fixed

- **`pyproject.toml` now pins `pydantic>=2.10,<2.13`.** A fresh install on a
  system with an older or newer pydantic crashes at startup with
  `PydanticUserError: A non-annotated attribute was detected: 'result = <class 'str'>'`
  because mcp 1.26's bundled FastMCP uses a `create_model()` pattern that
  pydantic <2.10 and >=2.13 reject. Caught via end-to-end smoke test against
  the published 0.20.3 PyPI artifact.
- **README** updated from `~965 tokens` (benchmark estimator) to `~1,187 tokens`
  (live JSON-RPC `tools/list` measurement). The benchmark's
  `len(json.dumps) // 4` undercounts the envelope overhead; the live number is
  what the model actually sees.

### CI

- npm publish + MCP Registry publish marked `continue-on-error: true`.
  PyPI (via OIDC trusted publishing) is the source of truth and never fails;
  npm needs a one-time Trusted Publisher registration at
  https://www.npmjs.com/package/kitsune-mcp/access, MCP Registry needs both
  ecosystems live. Until those are sorted, those legs fail silently rather
  than blocking the workflow's overall status.

---

## [0.20.3] — 2026-05-16

### Fixed — token diet for the 6 lean-profile tools

v0.20.2's TDQS-grade docstrings ("Use when / Avoid when / Behavior / Examples"
sections + verbose `Field(description=...)` on every parameter) ballooned the
lean-profile resting cost from ~1,110 tok to **3,654 tok** — undercutting the
whole "low context overhead" pitch.

This release trims the descriptions to a sweet spot:
- 1-3 line docstrings with a tight example block
- `Field(description=...)` dropped where the param is obvious from name + docstring
- `examples=[...]` arrays removed (they serialize into the schema)
- Verbose `Use when / Avoid when / Behavior / Examples` blocks lifted to
  `examples/scenarios/` instead of every tool's schema

**Result (measured via `examples/benchmark.py`):**

| | v0.20.1 | v0.20.2 (verbose) | v0.20.3 (this) |
|---|---:|---:|---:|
| Lean profile (6 tools) | 1,110 tok | 3,654 tok | **965 tok** |
| Forge profile (20 tools) | 2,873 tok | 5,765 tok | **2,677 tok** |

Per-tool (lean): shapeshift 252 · auto 194 · call 188 · auth 151 · search 129 · status 50.

README "Token savings vs always-on" tables recalculated against the measured
965-token baseline — savings still meaningful (70% on a single GitHub MCP,
88–95% on a 5-server bundle).

All 595 tests pass.

---

## [0.20.2] — 2026-05-16

### Fixed — process leak in `shiftback()` (#38)

- **`shiftback(kill=True)` is now the default.** Previously `kill=False` silently leaked the underlying server subprocess (~40-50 MB each). With 10 servers explored in a session that adds up to ~400 MB of dead-weight memory the user never asked for. Users who want to keep the pool warm for fast re-attach must now opt in with `kill=False`.
- Docstring and `docs/agent-patterns.md` updated to reflect the new default.

### Fixed — Glama Tool Definition Quality Score (TDQS)

- **All 6 lean-profile tools (`status`, `search`, `auth`, `shapeshift`, `call`, `auto`) rewritten** to score well on Glama's TDQS rubric. Every parameter now carries `Annotated[type, Field(description=...)]` so descriptions surface in `inputSchema.properties[*].description`. Docstrings restructured with explicit "Use when / Avoid when / Behavior / Examples" sections — TDQS heavily penalizes missing usage boundaries (per Glama's research, 89% of surveyed MCP tools fail this).
- `glama.json` `maintainers` array was malformed (objects instead of strings per the official schema at `https://glama.ai/mcp/schemas/server.json`). Fixed to `["kaiser-data"]`; passes schema validation.

### Maintenance

- Issues #35, #36, #37 confirmed fixed on main and closed.
- Issue #38 fixed in this release.
- Issue #34 (auto() ranker for generic web-search tasks) commented with fix plan; still tracked.

---

## [0.15.0] — 2026-05-09

### Fixed — `auto()` arg inference and routing (continued from v0.14.0)

- **Issue #1 fixed — optional search params now filled.** Many Smithery servers declare all params as optional (`required=[]`) but still reject calls without the primary query argument. `_infer_args_from_task` now fills the first `SEARCH_PARAM_NAMES` property (`query`, `q`, `text`, etc.) even when `required` is empty, preventing `query=undefined` errors on `web_search_exa` and similar tools.
- **Issue #3 continued — `"current"` context queries blocked.** Added `"current"`, `"latest"`, `"today"`, `"now"` to `_NL_STARTERS` so `auto("current time in Berlin")` returns `{}` for `timezone` instead of forwarding the full phrase.
- **Path params protected.** New Rule 2a: `path`/`file`/`directory` params are never filled unless the task string looks like a filesystem path (`/…`, `~/…`, `./…`). Prevents `auto("web search for X")` from routing to `mcp-server-git` and calling `search_files(path="web search for X")`.
- **Issue #4 fully fixed — `onboard()` added to lean profile.** `onboard` is now in `_LEAN_TOOLS` so the `auto("onboard") → "call it directly → onboard()"` redirect actually works. Also distinguishes lean vs forge tool names in the redirect message.

### Testing
- Updated `test_auto_args.py` and `test_tool_surface.py` to reflect new behavior.
- Total: **481 tests** (was 480).

---

## [0.14.0] — 2026-05-09

### Fixed — `auto()` routing

- **`_simple_search` now does word-by-word matching** instead of full-string substring matching. `search("what time is it in Tokyo")` now returns `mcp-server-time` because "time" appears in its name. Previously only Smithery (server-side full-text) found anything for NL queries; official/McpRegistry/Glama/npm all returned zero results, so `auto()` routed to random Smithery HTTP servers. (Closes issues #2 and #1.)
- **`auto()` extracts keywords before searching**. Raw NL task `"what time is it in Tokyo"` → search query `"time Tokyo"`. Official registry now surfaces `mcp-server-time` at rank #1. Fallback to raw task if keyword extraction strips everything.
- **`_infer_args_from_task` refuses to forward NL sentences to structured params.** New rule: if the task starts with a question word (`what`, `how`, `where`, …) AND the required param is a structured identifier (`timezone`, `currency`, `language`, `city`, …), return `{}` instead of forwarding the full sentence verbatim. `get_current_time` no longer receives `timezone: "what time is it in Tokyo"`. (Closes issue #3.)
- **`_infer_args_from_task` correctly fills search-like and QA params.** `query`, `q`, `text`, `prompt`, `user_question`, etc. are always filled unconditionally — these are payload params that expect free text. Multiple required string params → `{}` (ambiguous; let LLM supply explicit args).
- **`auto()` guards against built-in Kitsune tool names.** `auto("onboard")` now returns a redirect message instead of searching the registry for an external server named "onboard". (Closes issue #4.)
- **`status()` verifies Smithery API key liveness.** A 3-second ping to `registry.smithery.ai` distinguishes "key set — verified ✓", "key set but INVALID", and "could not verify". (Closes issue #5.)

### Testing
- 23 new tests in `tests/test_v014_fixes.py`.
- Total: **480 tests** (was 457).

---

## [0.13.0] — 2026-05-09

### Security
- **SSRF via redirect blocked** — `_ssrf_safe_request()` validates each redirect hop against `_is_safe_url()`. `fetch()` and `craft()` endpoint proxies now use it, closing the open-redirect bypass (a public URL redirecting to `169.254.169.254` was previously followed without checks).
- `_is_safe_url` moved from `onboarding.py` to `utils.py` — canonical, single definition, no circular-import risk.

### Fixed
- **Probe temp dirs now cleaned up** — `inspect()` wraps the probe subprocess in `try/finally` and calls `shutil.rmtree(tmpdir)` after the probe exits. Previously every `inspect()` call leaked a `kitsune-probe-*` temp dir.
- **SSE multi-line events** — `_parse_sse()` now collects all `data:` lines per event (separated by blank lines) before parsing, matching RFC 6455. Servers that spread a large JSON response across multiple `data:` lines are now handled correctly.
- **`datetime.utcnow()` removed** — replaced with `datetime.now(UTC)` in `onboarding.py` (Python 3.12+ deprecation).
- **PyPI HTML search** — switched from CSS class-name regex (`package-snippet__name`) to stable `/project/<name>/` link extraction. Less fragile across PyPI redesigns.

### Performance
- **NpmRegistry + PyPIRegistry now cache responses** — 60 s TTL for search, 300 s for `get_server`. Cold `MultiRegistry` calls no longer re-fetch npm/PyPI on every search miss.
- `MultiRegistry.bust_cache()` propagates the clear to individual registry caches.

### UX
- **`status()` shows crafted tools** — persistent `crafted_tools` are now listed in the CRAFTED TOOLS section with method + URL, so users know what survived restart.
- **`MCP_CLIENT_INFO.version` reflects actual package version** — reads from `importlib.metadata` instead of being hardcoded to `"1.0.0"`.

### Testing
- 28 new tests in `tests/test_audit_fixes.py` covering: SSRF redirect guard, SSE multi-line parsing, probe tmpdir cleanup, `_restore_crafted_tools`, `bench()`, `test()` quality scorer, `run()`, crafted tools in `status()`, PyPI link-based search, NpmRegistry/PyPIRegistry caching.
- Total: **457 tests** (was 429).

---

## [0.12.0] — 2026-05-09

### Security
- **SSRF protection in `fetch()` and `craft()`** — both tools now block requests to private/loopback addresses (127.x, 10.x, 192.168.x, 169.254.x, localhost), consistent with the existing guard in `skill()`. Override with `KITSUNE_ALLOW_LOCAL_FETCH=1` for local development.

### New Features
- **Parameter aliasing in proxy tools** — `from_timezone` is silently remapped to `source_timezone`, `to_timezone` to `target_timezone`, `from`/`to` to `source`/`target`, `src`/`dst`/`dest` to `source`/`target`, and language variants (`from_lang`, `to_lang`, `input_lang`, `output_lang`). Applied only when the alias key is absent from the tool schema. Closes #9.
- **Shapeshifted tool registration failures now surface** — failed `mcp.add_tool()` calls are no longer silently swallowed; they appear as `⚠️ N tool(s) failed to register: name: error` in the `shapeshift()` output.
- **Session persistence** — `crafted_tools` and `connections` metadata (minus PIDs and `started_at`) now survive server restarts in `~/.kitsune/state.json`. Explored history is capped at 100 entries. Crafted tools are re-registered with FastMCP on startup.
- **`auto()` prefers official stdio servers over Smithery HTTP** — `mcp-server-time` (official, stdio, free) now beats a Smithery HTTP equivalent when both are returned by search. Ties broken by `not (transport == "stdio")` as the 4th sort key.

### CI / Infrastructure
- **mcp-publisher bumped to v1.7.6** — fixes silent MCP Registry publish failures since v0.9.0 (OIDC audience binding changed in v1.7.6).
- **`actions/checkout` → v6**, **`actions/setup-python` → v6** (Dependabot #1, #2).

### Reliability
- `_registry_lock` (`asyncio.Lock`) prevents concurrent shapeshifts from leaving orphaned tools. Without it, two concurrent shapeshifts could interleave shed + register, leaving both servers' tools mounted while session only tracked one.
- `atexit` handler persists session state before killing pool processes on interpreter exit.
- Probe processes from `inspect()`/`compare()` are killed immediately after `list_tools()` returns.
- Registry paginated fetch no longer caches empty/partial results on transient failures.
- `shiftback(kill=True)` no longer mass-kills unrelated `connect()` sessions when pool key is missing — warns instead.
- `source='local'` on HTTP-only Smithery servers returns a clear error before shedding the current form.
- `call()` uses the shapeshifted session's pooled transport instead of re-resolving from registry.

### UX
- `auto()` surfaces registry fetch failures instead of silently returning "no tools listed".
- `compare()` shows `—` instead of `?` for unknown values; error labels are human-readable.
- `search()` warning uses actual exception class per registry.
- `shapeshift()` output includes wall-clock timing for cold npm installs.
- Filesystem server shapeshift proactively hints about `server_args` when no allowed dirs are passed.
- macOS `/tmp` → `/private/tmp` symlink resolved in proxy args.
- httpx INFO logging suppressed by default (`KITSUNE_DEBUG_HTTP=1` to re-enable).

### Correctness
- `tokens_sent` tracked in `StdioTransport`, `PersistentStdioTransport`, `WebSocketTransport`.
- `key()` masks secret value in response; `.env` written with `0o600` permissions.
- `_infer_args_from_task` returns `{}` when tool has multiple required string params.
- `__version__` exposed via `importlib.metadata`.

### Testing
- `tests/test_ssrf.py` — SSRF guard tests for `fetch()` and `craft()`.
- `tests/test_param_aliases.py` — alias normalization logic tests.
- `tests/test_session_persistence.py` — crafted_tools / connections / explored persistence tests.
- 6 integration tests for lean vs forge tool surface.
- `_registry_lock` concurrency tests.
- `tokens_sent` tests for all three previously-broken transports.

---

## [0.11.0] — 2026-05-04

Provider-aware onboarding — closes the rest of issue #8. Configure providers once up front, explore freely. Hermes-style agents now reach a working tool call in ≤3 steps with zero API keys.

### Added
- **`onboard()` tool** — first-run wizard. Shows provider auth state, recommends 5 zero-config servers (`mcp-server-time`, `@modelcontextprotocol/server-memory`, `mcp-server-fetch`, `@modelcontextprotocol/server-filesystem`, `@upstash/context7-mcp`), and ends with a 3-step verification flow. Optional Smithery upgrade path with a direct link to API key setup. (Issue #8 acceptance: "new user reaches working tool call in ≤3 steps".)
- **Multi-provider fallback in `auto()`** — when no `server_hint` is pinned and the chosen provider returns auth-failure response (`"Auth failed"`, `401`, `unauthorized`, etc.), `auto()` walks through the remaining `search()` candidates whose creds it can satisfy. The user asked for "web search", not Provider X.
- **Argument inference in `auto()`** — when `auto()` implicit-selects a tool but caller passed no `arguments`, fills the primary string param (`query`/`q`/`prompt`/`text`/etc., or single required string) from `task`. Without this, every implicit-select search tool failed with `query: undefined`. Existing explicit `arguments` are never overridden.

### Changed
- **`_credentials_ready()` returns three explicit tiers** instead of the ambiguous "no creds declared":
  - `✅ free – no key` for official sources without declared creds
  - `🔑 needs SMITHERY_API_KEY` (or other key name) for Smithery-hosted servers AND any server with declared creds — Smithery is checked unconditionally because per-server creds may be empty but `SMITHERY_API_KEY` is always required
  - `⚠️  community — may need creds` for npm/pypi/github undeclared
  - `🔑 may need OAuth or registry key` for mcpregistry/glama undeclared
  Closes the issue-#8 misread where "no creds" looked like "free".
- **`status()` headline reordered** — `PROVIDERS` section now appears immediately after the title, before everything else. PID/memory/perf stats moved below. Auth state is the actionable info; perf stats aren't.
- **`shapeshift()` pre-flight gate for Smithery-hosted servers** — fails fast with `❌ shapeshift failed: '...' is hosted on Smithery and needs SMITHERY_API_KEY` *before* tools are loaded, instead of letting the user discover the auth wall on the first tool call. Bypassed with `confirm=True`. Includes a direct link to `smithery.ai/account/api-keys` and an offered workaround (`source="local"`).

### Acceptance criteria from issue #8

- ✅ `oauth.py` present and importable (v0.10.2)
- ✅ OAuth 2.1 flow works for direct HTTP servers (v0.10.2)
- ✅ New user reaches working tool call in ≤3 steps with zero API keys (`onboard()` + free-tier list)
- ✅ Search results never show Smithery-hosted as "no creds" (3-tier labels)
- ✅ `shapeshift()` warns before loading server with unconfigured creds (Smithery pre-flight gate)
- ✅ `status()` shows provider auth state primarily (reorder)
- ✅ `auto()` falls back across providers silently on auth failure (multi-provider walk)
- ✅ `auto()` correctly passes args to npm-based servers (argument inference + bug verified absent)

---

## [0.10.2] — 2026-05-03

### Hotfix
- **`kitsune_mcp/oauth.py` is now actually shipped.** v0.10.0 and v0.10.1 wheels were missing the module on PyPI and npm. `transport.py` imports it at line 13 and calls `oauth.ensure_token` / `oauth.delete_tokens` / `oauth._origin` from `HTTPSSETransport(direct=True)`, so every fresh `npx -y kitsune-mcp` and `pip install kitsune-mcp` hit `ImportError: cannot import name 'oauth' from 'kitsune_mcp'` at startup. Local development was unaffected because the file existed on disk; the file was authored locally but never staged. Closes #8 (Bug 1).
- **OAuth 2.1 device/browser flow** for direct HTTP MCP servers (`HTTPSSETransport(direct=True)`) is now functional in installed packages. 29 tests cover the flow end-to-end (`tests/test_oauth.py`).
- **CI guard added** — `tests/test_release_smoke.py` imports every `kitsune_mcp.*` module and asserts `kitsune_mcp.oauth` exports the symbols `transport.py` calls. Any future missing-module-on-publish bug will fail CI before reaching PyPI/npm.

---

## [0.10.1] — 2026-05-03

### Fixed
- **`_make_proxy` no longer forwards `None` for omitted optional params.** When a client called a shapeshifted tool without supplying optional non-string args (integers, booleans, arrays), the proxy filled them with `None` from its `__signature__` defaults and forwarded those `None`s to the inner MCP server, which rejected them with `Input validation error: None is not of type 'integer'` (JSON Schema doesn't permit null for typed params unless explicitly declared as `["type", "null"]`). Affected most non-trivial servers — `mcp-server-fetch` (`max_length`, `start_index`, `raw`), GitHub (`per_page`, `page`), Postgres/SQLite (`limit`, `offset`), Filesystem (`head`, `tail`). The proxy now drops `None`-valued kwargs so the inner server applies its own defaults instead. Falsy-but-not-None values (`0`, `False`, `""`) are preserved. Surfaced during the v0.10.0 setup-coverage tests against `mcp-server-fetch`.

---

## [0.10.0] — 2026-05-02

### Added
- **Auto-resolution of typo'd / wrong-namespace server IDs in `shapeshift()`** — `shapeshift("@modelcontextprotocol/server-time")` now silently resolves to the canonical `mcp-server-time` and proceeds, instead of returning a confusing "not found" error. Multiple plausible matches surface as a `Did you mean: a, b, c` suggestion list. Single high-confidence match auto-resolves on the first turn — agents recover without needing a retry. Closes #6 (the verified piece — see issue thread).
- **Machine-detectable failure marker** — every `shapeshift()` failure response now starts with `❌ shapeshift failed:` so callers can detect failure with one prefix check instead of parsing prose. Successful responses still start with `Shapeshifted into '...'`.
- **`_PaginatedListRegistry` base class** — `McpRegistryIO` and `GlamaRegistry` share a hookable paginated-fetch loop. New paginated registries now cost ~10 lines of overrides instead of ~30 lines of fresh page-loop code.
- **`TTLDict[K, V]` cache primitive** — keyed time-to-live cache with lazy expiry; replaces the ad-hoc `dict[tuple, (value, expires_at)]` pattern that was scattered across `MultiRegistry`.
- **`_fastmcp_compat` shim** — single point of contact for FastMCP private-API access (`_resource_manager._resources`, `_prompt_manager._prompts`). `_assert_internals(mcp)` runs at app startup so any future FastMCP refactor fails loudly at import rather than silently breaking `shiftback()`.
- **Per-registry timeout in `MultiRegistry`** — `search()` and `get_server()` wrap each registry call in `asyncio.wait_for(..., TIMEOUT_REGISTRY_TASK)` so one stalled DNS/TCP-connect can't block the others.
- **`_dotenv_revision` invariant** — documented as monotonically non-decreasing, with a guard test so future fixtures can't break pool eviction by resetting the counter.

### Changed
- **`kitsune_mcp/tools.py` (1782 lines) → `kitsune_mcp/tools/` package** with themed submodules: `discovery.py` (search/inspect/compare/status), `exec.py` (call/run/fetch/test/bench), `morph.py` (shapeshift/shiftback/craft/connect/release), `onboarding.py` (skill/key/auto/setup), `_state.py` (shared helpers + mocks-target namespace). All public imports preserved via `tools/__init__.py` re-exports — no breaking changes.
- **`ServerInfo` is now `frozen=True, slots=True`** — eliminates cache-poisoning via mutation and saves ~30% memory per instance. `dataclasses.replace(srv, ...)` continues to work.
- **`_SmitheryAuth` dataclass with `asyncio.Lock`** — replaces 4 module-level globals; concurrent `get_token()` / `get_namespace()` callers serialize on a lock with double-check, eliminating thundering-herd token refresh.
- **`_evict_stale_pool_entries()` debounced** to once per 30s on the call hot path (force=True still available for tests). Pool sweep is no longer O(N) per tool call.

### Fixed
- **Test mock-patch surface unified** — all `kitsune_mcp.tools.X` patch sites now route through `kitsune_mcp.tools._state.X`, the canonical namespace for cross-cutting state. 133 patch sites updated; future submodule refactors won't silently invalidate tests.

### Issue #6 follow-up (verification notes)
The reported "Bug 1" (`current_form` not set after shapeshift) does not reproduce against a verified-valid server ID. The agent's repro used `@modelcontextprotocol/server-time` — which doesn't exist in any registry. shapeshift correctly returned a "not found" error which the agent misread as success, then was confused when downstream `call()` had no `current_form` to use. The auto-resolution work above fixes the underlying UX failure (typo'd ID → confusing error chain) so the same pattern can't happen again. The architectural claim that ~80% of clients are blind to dynamic tool changes is partially incorrect — the standard `mcp` Python SDK honors `notifications/tools/list_changed` (which Kitsune already sends), and verification confirms tools become visible to spec-compliant clients. Specific clients that don't honor the notification are the right targets to fix once verified — defensive-only code (Solution 1 / refresh tool) deferred until verified reports exist.

---

## [0.9.0] — 2026-04-12

### Added
- **`source=` parameter on `shapeshift()`** — `"local"` forces npx/uvx install (no Smithery key); `"smithery"` forces HTTP; `"official"` requires verified registry listing; `"auto"` (default) keeps current behavior
- **`shiftback(uninstall=True)`** — optionally uninstalls the locally installed package; uvx packages fully removed (`uv tool uninstall`), npx cache auto-expires
- **`KITSUNE_TRUST` env var** — set `"community"` to permanently bypass the community/local confirmation gate for trusted users and agents (`key("KITSUNE_TRUST", "community")`)
- **Credential status in `search()` results** — each row now shows `✅ ready` or `✗ needs API_KEY`
- **`inspect()` next-step CTA** — ends with `Next: key("VAR", "...") then shapeshift("id")` or `Next: shapeshift("id")` based on credential state
- **Lean hint after `shapeshift()`** — servers with >4 tools loaded without a filter show `💡 N tools loaded (~X tokens). For lean mounting: shapeshift("id", tools=[...])`
- **First-run onboarding in `status()`** — clean sessions show a 5-step guide with example flow
- **Registry failure reporting in `search()`** — timed-out registries shown as `⚠️ Skipped: name (timeout)` so partial results are visible

### Fixed
- **Credential check before `_do_shed()`** — missing credentials no longer drop your active form before returning the error
- **`bust_cache(server_id)` now works** — cache uses `(id, source_preference)` tuple keys; old `pop(str)` silently missed every entry
- **`source="official"` gate ordering** — official-source check fires before the trust gate, giving the right error for non-official servers
- **Pool path `current_form_local_install` leak** — pool shapeshift clears local install record so stale data can't trigger `uninstall=True` on the wrong package

### Changed
- `shapeshift()` pool-path and registry-path share a single `_commit_shapeshift()` helper — ~70 lines of duplication removed
- `_credentials_ready()` calls `_to_env_var(k)` once per key instead of three times
- `MultiRegistry._reg_names` precomputed at init instead of on every `search()` call

---

## [0.8.5] — 2026-04-11

### Fixed
- **Circular import** between `registry.py` and `official_registry.py` — `_registry` is now
  a lazy proxy; `MultiRegistry()` is deferred until first use
- **Ruff lint** — 64 errors resolved (import ordering, unused vars, SIM105, B023, UP046);
  CI pipeline is now fully green on Python 3.12 and 3.13

### Added
- Codecov coverage reporting (badge in README, uploads on every CI run)
- Automated GitHub Releases with CHANGELOG excerpt on tag push
- Glama registry listing (`glama.json`)
- Dependabot for weekly pip + GitHub Actions updates
- SECURITY.md and PR template

---

## [0.8.2] — 2026-04-11

### Added
- npm wrapper package — `npx kitsune-mcp` delegates to `uvx kitsune-mcp` (Python)
- Official MCP registry listing (`server.json` for `mcp-publisher`)
- `mcp-name` ownership tag in README for registry verification

---

## [0.8.1] — 2026-04-11

### Fixed
- **Smithery transport rewritten** — replaced dead `server.smithery.ai/{name}/mcp?config=b64` URL
  with the new Smithery Connect API: namespace → service token → connection upsert →
  `api.smithery.ai/connect/{ns}/{id}/mcp`. Fixes 400 "Server configuration is incomplete"
  and "Invalid token" errors from `run.tools`.
- **Registry** now reads `deploymentUrl` from Smithery API response instead of reconstructing stale URLs
- **`_resolve_config`** always writes all credential keys (`None` → JSON `null`) so Smithery's
  schema validator sees all expected keys even when optional vars are unset

### Changed
- `morph.py` → `shapeshift.py` (rename complete; `morph.py` deleted)
- Session keys: `morphed_tools/resources/prompts` → `shapeshift_tools/resources/prompts`
- `.chameleon` directory references → `.kitsune` in `credentials.py`, `session.py`, `transport.py`
- Docker label: `chameleon-mcp=1` → `kitsune-mcp=1`

---

## [0.8.0] — 2026-04-10

### Breaking Changes
- **Package renamed** `protean-mcp` → `kitsune-mcp` — update `pip install` and client configs
- **Package directory renamed** `chameleon_mcp/` → `kitsune_mcp/` — update any direct imports
- **Env var renamed** `CHAMELEON_TOOLS` → `KITSUNE_TOOLS` — update any custom tool filters
- **FastMCP server name** `"protean"` → `"kitsune"` — affects MCP client display name

### Deprecated (remove in v0.9)
- `protean-mcp`, `protean-forge` executables (kept as aliases)
- `chameleon-mcp`, `chameleon-forge` executables (kept as aliases)

### Migration
```bash
pip install kitsune-mcp
# update mcp.json: "command": "kitsune-mcp"
# update env: KITSUNE_TOOLS=... (was CHAMELEON_TOOLS)
```

---

## [0.7.3] — 2026-04-08

### Fixed
- `status()` output header: "CHAMELEON MCP STATUS" → "KITSUNE MCP STATUS"

---

## [0.7.2] — 2026-04-08

### Fixed
- README: absolute image URLs so logo and diagrams render on PyPI

---

## [0.7.1] — 2026-04-08

### Changed
- New logo (`logo_kitsune-mcp.png`) replacing placeholder SVG
- README: removed "a new way" framing; architecture diagrams cleaned of chameleon references
- `docs/architecture.svg`: removed 🦎 emoji from Kitsune MCP label
- `docs/architecture-forge.svg`: "chameleon-forge" → "kitsune-forge"

---

## [0.7.0] — 2026-04-08

### Breaking Changes

- **`morph()` renamed to `receive()`** — update any prompts or scripts that call `morph(...)`
- **`shed()` renamed to `cast_off()`** — update any prompts or scripts that call `shed()`
- **Package renamed from `chameleon-mcp` to `kitsune-mcp`** — update `pip install` and `pyproject.toml` references
- **Executables renamed**: `chameleon-mcp` → `kitsune-mcp`, `chameleon-forge` → `kitsune-forge`

### Migration Guide

| Before | After |
|---|---|
| `pip install chameleon-mcp` | `pip install kitsune-mcp` |
| `"command": "chameleon-mcp"` | `"command": "kitsune-mcp"` |
| `receive("exa")` | `receive("exa")` ← no change |
| `morph("exa")` | `receive("exa")` |
| `shed()` | `cast_off()` |

**Deprecated executables** (`chameleon-mcp`, `chameleon-forge`) are kept as aliases in v0.7.x for backward compatibility and will be removed in v0.8.0.

### Added
- `kitsune-mcp` and `kitsune-forge` as primary entry point executables
- `chameleon-mcp` and `chameleon-forge` kept as deprecated backward-compat aliases

### Changed
- MCP server display name: `"chameleon"` → `"protean"`
- `pyproject.toml` keywords: removed `"smithery"`, added `"mcp-registry"`
- Package description updated to reflect 7-registry architecture

---

## [0.6.2] — 2026-04-08

### Fixed
- `receive()` cold-start: prefer registry results with cached tool schemas over those without (fixes Exa cold-start failure)
- Live `tools/list` HTTP fetch fallback when registry cache is cold
- Smithery URL format: `/mcp` suffix + `api_key` query param (was using wrong format)
- Doubled Smithery URL when `srv.url` was already a full URL
- Pool staleness: auto-evict subprocesses when `.env` changes mid-session

---

## [0.6.1] — 2026-04-07

### Added
- Frictionless credentials: `.env` auto-reload without restart (tracks mtime changes)
- `call()` is mount-aware: `server_id` optional after `receive()`
- `call()` added to lean profile (7 tools total)
- WebSocket transport support (`ws://`, `wss://`)

---

## [0.6.0] — 2026-04-07

### Added
- `receive()` proxies resources + prompts in addition to tools
- Install command validation (shell injection and path traversal blocked)
- Trust tier warnings in `receive()` output
- Credential warnings at mount-time (not just at `call()`-time)
- `examples/benchmark.py` — reproducible token overhead measurement
- Notification compatibility testing
- Provenance shown in all `search()`/`inspect()`/`receive()`/`call()` output

---

## [0.5.9] — 2026-04-06

### Added
- Refactored into `kitsune_mcp/` package structure
- `OfficialMCPRegistry` — seeds from `modelcontextprotocol/servers` GitHub repo
- `inspect()` stores measured `token_cost` from actual tool schemas
- `status()` sums measured costs for inspected-but-not-mounted servers
- Per-server trust tier tracking

### Fixed
- Registry fan-out priority: official > mcpregistry > glama > github > smithery > npm
- PyPI registry is opt-in only (not in default fan-out — too slow)
