import asyncio
import json
import re
import shutil

from chameleon_mcp.constants import MAX_RESPONSE_TOKENS


def _estimate_tokens(text) -> int:
    if isinstance(text, list):
        return sum(len(json.dumps(t)) for t in text) // 4
    return len(str(text)) // 4


def _truncate(text: str, max_tokens: int = MAX_RESPONSE_TOKENS) -> str:
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n[...truncated at ~{max_tokens} tokens]"


def _clean_response(text: str) -> str:
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)  # strip markdown links, keep label
    text = re.sub(r'!\[[^\]]*\]', '', text)                # strip images
    text = re.sub(r'\n{3,}', '\n\n', text)                 # collapse blank lines
    text = re.sub(r'[ \t]{2,}', ' ', text)                 # collapse spaces
    return text.strip()


def _strip_html(text: str) -> str:
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = (text
            .replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
            .replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' '))
    return _clean_response(text)


def _extract_content(result: dict) -> str:
    content = result.get("content", [])
    if content:
        text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
        return "\n".join(text_parts) if text_parts else json.dumps(content, indent=2)
    return json.dumps(result, indent=2)


async def _try_axonmcp(url: str, intent: str) -> str | None:
    axon = shutil.which("axon-mcp")
    if not axon:
        return None
    try:
        cmd = [axon, "browse", url]
        if intent:
            cmd += ["--intent", intent]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=20.0)
        result = stdout.decode().strip()
        return result if result else None
    except Exception:
        return None
