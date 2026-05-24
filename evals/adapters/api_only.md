# adapter: api_only

Raw model API call. No tools, no multi-turn. The fairest baseline because the harness contributes minimally to the result.

## Contract

**Input the runner provides to the model:**
- A system prompt: `"You are a software engineer. Apply the requested change as a unified diff. Output ONLY the diff, no prose."`
- The `task.prompt.instruction`
- The fixture, serialised as a tree listing + concatenated file contents inside `<file path="...">...</file>` tags
- The `task.prompt.system_prompt_addendum` if present

**Output the model is expected to produce:**
- A single unified diff parseable by `git apply --check`

**The adapter:**
- Times the request
- Captures `usage` (input/output tokens, cached if applicable)
- Saves the raw response as `transcript[0]`
- Writes `result.json` per `tasks/schemas/result.schema.json`

## Systems this adapter targets

| System | Model ID examples | Notes |
|---|---|---|
| Anthropic API | `claude-opus-4-7`, `claude-sonnet-4-6-20251101`, `claude-haiku-4-5-20251001` | Recommend prompt caching on the fixture portion to amortise across n_runs |
| OpenAI API | `gpt-4o-2024-11-20`, `o1-preview`, `o3` | Pricing differs sharply between tiers — record exactly |
| Google API | `gemini-1.5-pro`, `gemini-2.0-flash` | 1M-token context allows full repos in prompt; useful for long-context tasks |
| Ollama (local) | `llama3.3:70b`, `qwen2.5-coder:32b`, `deepseek-coder-v2` | Set `cost_usd: 0` in result; report wall time and GPU |
| vLLM / TGI | Any open-weights model | Same as Ollama |

## Capabilities supported

- `read_files`: yes (entire fixture is in the prompt)
- `write_files`: no (model outputs a diff string)
- `shell_exec`: no
- `multi_turn`: no
- `web_access`: no
- `long_context_64k` / `_128k`: model-dependent

Tasks declaring capabilities this adapter can't satisfy MUST be skipped (record `errors: [{stage: "compat", message: "capability X unavailable"}]` and exit).

## Caveats

- **Fixture-in-prompt has token-count limits.** A 200-file repo won't fit; you'll need to send a directory listing + selectively included files, or skip the task. Document the truncation in `errors`.
- **Models hallucinate diffs frequently.** Expect `git apply --check` failure rate of 5–25% even on syntactically valid output. This IS the data — don't auto-retry.
- **Temperature.** Default `temperature=0` for reproducibility. For reliability tasks, vary seed/temp explicitly per run.
- **System prompt parity.** Different vendors interpret system prompts differently. Document any per-vendor wording differences in `harness_config`.

## Minimum implementation checklist

- [ ] Build fixture serialisation (`<file path="...">...</file>` tree)
- [ ] Wire API client per vendor (one file each)
- [ ] Capture `usage` accurately — pay attention to caching tokens for Anthropic
- [ ] Parse diff from response (strip code-fence wrappers, validate with `git apply --check`)
- [ ] Translate API errors into `errors[]` rather than crashing the runner
- [ ] Emit `result.json` validating against the schema
