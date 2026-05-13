"""Adapter for web/search MCP servers: Brave, Exa, Linkup, Firecrawl."""

from kitsune_mcp.adapters import Adapter, _register

_SETUP_HINTS: dict[str, str] = {
    "BRAVE_API_KEY": "Free at brave.com/search/api — 250 queries/month, no credit card",
    "EXA_API_KEY": "Free at exa.ai — 1,000 searches/month on signup",
    "LINKUP_API_KEY": "Free tier at app.linkup.so/register",
    "FIRECRAWL_API_KEY": "Free tier at firecrawl.dev — 500 credits on signup",
}


class WebSearchAdapter(Adapter):
    CATEGORY = "web_search"
    KNOWN_IDS = frozenset({
        "brave-search",
        "server-brave-search",
        "exa-mcp-server",
        "exa-search",
        "linkup-mcp",
        "firecrawl-mcp",
    })

    def setup_hint(self, server_id: str, missing_creds: list[str]) -> str:
        for cred in missing_creds:
            hint = _SETUP_HINTS.get(cred.upper())
            if hint:
                return hint
        return ""


_register(WebSearchAdapter())
