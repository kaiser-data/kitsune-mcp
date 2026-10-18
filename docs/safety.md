# Safety model

Reach into 130k community servers only works if unknown code can be **contained**. Consent, sandbox, and pins are product features — not footnotes.

**Headline controls**

- `confirm=True` (or `KITSUNE_TRUST`) before community / local mounts
- **Community npm/PyPI mounts cage in hardened Docker by default** (when Docker is present); `sandbox=False` or `KITSUNE_SANDBOX=off` opts out, `sandbox=True` forces it, `KITSUNE_SANDBOX=all` cages every local mount
- TOFU pins in `~/.kitsune/pins.json` — later malicious publishes don't silently replace what you already ran

## What it protects against

**1. Unverified code without consent**

| Tier | Sources | On mount |
|---|---|---|
| High | `official` | runs directly |
| Medium | `mcpregistry`, `glama`, `smithery` | runs directly |
| Community | `npm`, `pypi`, `github` | **requires `confirm=True`** |
| Your own | local `connect()` command | runs directly, as your user, uncaged. Approve `connect` in your client |

`KITSUNE_TRUST=community` waives the gate; `status()` warns when that override is active. Only the user can set it: `auth()`, `key()` and `auto(keys=)` refuse every `KITSUNE_*` variable, plus launch and supply-chain levers such as `NODE_OPTIONS`, `LD_PRELOAD`, `PIP_INDEX_URL` and `DOCKER_HOST`, because unsandboxed servers inherit the environment.

> **`confirm=True` is not a human-approval boundary.** The model can set it. Real approval belongs in your client's tool-approval UI.

**2. Shell injection at spawn.** Install commands are validated (no `& ; | $ \` `\n` / `../`) and launched with `create_subprocess_exec` — no shell. Vets the launch line, not what the package does once running.

**3. SSRF.** `fetch()` and registry HTTP are HTTPS-only; private/loopback/non-global hosts blocked; **every redirect hop re-validated** (`KITSUNE_ALLOW_LOCAL_FETCH=1` to opt out).

**4. Credential exposure.** `~/.kitsune/.env` and `oauth/` at mode `0600`; OAuth 2.1 + PKCE S256 + DCR (RFC 7591); missing-cred warnings before calls; `auth(id, "logout")` clears tokens (RFC 7009 where available).

**5. Docker sandbox for untrusted local servers — on by default.** Community `npm`/`pypi`/`github` mounts (and the `auto()`/`call()`/`run()` exec paths) cage automatically when Docker is on `PATH`; no host FS, `--cap-drop ALL`, read-only rootfs, RAM/PID caps. Cred env vars forwarded by **name** only (`docker -e KEY`) — never in argv, `ps`, or the pool key. First sandboxed mount pulls `node:22-slim` / `uv:python3.13-bookworm-slim`. Best-effort: no Docker → runs uncaged with a nudge (an explicit `sandbox=True` hard-fails instead). Opt out per-call with `sandbox=False` or session-wide with `KITSUNE_SANDBOX=off`. Filesystem-style servers need host paths and don't fit the sandbox.

**6. Action guard (opt-in).** The cage handles bad *servers*; the guard handles bad *calls* to good ones, such as an injected agent asking the official GitHub server to push. With `~/.kitsune/policy.json` present, every downstream call (mounted tools, `call`, `run`, `auto`, `test`, `bench`) is checked first: tool `allow`/`ask`/`deny` globs per server, read/write path roots, a host allowlist, and opaque encoded payloads (gzip/zlib behind base64 or hex). Credential stores (`~/.ssh`, `~/.aws`, `.env`, `/var/run/secrets`, …) and `~/.kitsune` itself are always denied. `ask` goes to the **user** through MCP elicitation; the agent has no argument to approve itself, and clients without elicitation get a block. As of October 2026, Claude Code and Cursor show the prompt and Claude Desktop does not, so on Desktop `ask` acts as `block`: allow the tool in the policy instead. A prompt left unanswered for 2 minutes counts as a no. A client-side hook can answer for the user, so treat an approval as the client's word, not proof that a person saw it. `mode: "monitor"` (the default) only logs to `~/.kitsune/guard.log.jsonl` (argument hashes, not values). Free-text arguments (`command`, `sql`, …) and unlisted tools need a classifier that isn't wired yet, so today they ask. Design: [`docs/superpowers/specs/2026-09-26-action-guard-design.md`](https://github.com/kaiser-data/kitsune-mcp/blob/main/docs/superpowers/specs/2026-09-26-action-guard-design.md).

```json
{"version": 1, "mode": "enforce", "default": "ask",
 "network": {"allow": ["api.github.com"]},
 "paths": {"read": ["~/code"], "write": ["~/code/my-project"]},
 "servers": {"github": {"allow": ["get_*", "list_*", "search_*"], "ask": ["create_pull_request"], "deny": ["push_files", "delete_*"]}}}
```

## What it does NOT do

- **Cage needs Docker + opt-in-trusted sources.** Community mounts cage by default *only when Docker is present*; without it (or with `sandbox=False`/`KITSUNE_SANDBOX=off`, or for medium/high-trust sources) local stdio runs as your user — full FS, network, inherited env. Process isolation ≠ a security boundary.
- **Docker ≠ kernel boundary.** Hardened flags blunt escalation / fork bombs / FS tampering; not a guarantee against container escape. No default non-root / `--network none` (most servers need egress).
- **TOFU ≠ digest pin.** Pins a version, not a content hash. `github:` / `git+` / hand-written `connect()` commands aren't pinned. High assurance: pin by digest or vendor.
- **Guard ≠ semantic understanding.** It sees tool names and arguments, not what a server does with them; a server that ignores its own `path` argument, or a tool with a misleading name, gets past the path and verb rules.
- **Tools first.** Resource/prompt proxying is narrower (URI templates skipped; HTTP path differs). "Any server" means tool execution.

**Bottom line:** strong for supervised developer and personal use. **Do not run unattended with production admin, billing, or security credentials in default local mode.** Keep Docker installed so the default cage engages, and prefer client approval for untrusted packages.

See guards live: [`docs/demo-realtime.md`](https://github.com/kaiser-data/kitsune-mcp/blob/main/docs/demo-realtime.md#act-3).

---

[← README](https://github.com/kaiser-data/kitsune-mcp#readme)
