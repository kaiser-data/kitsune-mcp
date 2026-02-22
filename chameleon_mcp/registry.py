import asyncio
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx

from chameleon_mcp.constants import TIMEOUT_FETCH_URL, MAX_EXPLORE_DESC
from chameleon_mcp.utils import _estimate_tokens
from chameleon_mcp.credentials import _registry_headers, _smithery_available

REGISTRY_BASE = "https://registry.smithery.ai"


@dataclass
class ServerInfo:
    id: str
    name: str
    description: str
    source: str           # "smithery" | "npm"
    transport: str        # "http" | "stdio"
    url: str = ""
    install_cmd: list = field(default_factory=list)
    credentials: dict = field(default_factory=dict)  # {field: description}
    tools: list = field(default_factory=list)         # lazy-loaded
    token_cost: int = 0


class BaseRegistry(ABC):
    @abstractmethod
    async def search(self, query: str, limit: int) -> list: ...

    @abstractmethod
    async def get_server(self, id: str): ...


class SmitheryRegistry(BaseRegistry):
    async def search(self, query: str, limit: int) -> list:
        if not _smithery_available():
            return []
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    f"{REGISTRY_BASE}/servers",
                    params={"q": f"{query} is:verified", "pageSize": limit},
                    headers=_registry_headers(),
                    timeout=TIMEOUT_FETCH_URL,
                )
                r.raise_for_status()
                data = r.json()
        except Exception:
            return []

        results = []
        for s in data.get("servers", []):
            qname = s.get("qualifiedName", "")
            if not qname:
                continue
            credentials = {}
            for conn in s.get("connections", []):
                for k, val in conn.get("configSchema", {}).get("properties", {}).items():
                    credentials[k] = val.get("description", "")
            remote = s.get("remote", False)
            results.append(ServerInfo(
                id=qname,
                name=s.get("displayName") or qname,
                description=(s.get("description") or "").strip()[:MAX_EXPLORE_DESC],
                source="smithery",
                transport="http" if remote else "stdio",
                url=f"https://server.smithery.ai/{qname}" if remote else "",
                install_cmd=[],
                credentials=credentials,
                tools=[],
                token_cost=0,
            ))
        return results

    async def get_server(self, id: str):
        if not _smithery_available():
            return None
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    f"{REGISTRY_BASE}/servers/{id}",
                    headers=_registry_headers(),
                    timeout=TIMEOUT_FETCH_URL,
                )
                r.raise_for_status()
                s = r.json()
        except Exception:
            return None

        credentials = {}
        for conn in s.get("connections", []):
            for k, val in conn.get("configSchema", {}).get("properties", {}).items():
                credentials[k] = val.get("description", "")
        tools = s.get("tools") or []
        remote = s.get("remote", False)
        qname = s.get("qualifiedName", id)
        return ServerInfo(
            id=qname,
            name=s.get("displayName") or qname,
            description=(s.get("description") or "").strip(),
            source="smithery",
            transport="http" if remote else "stdio",
            url=f"https://server.smithery.ai/{qname}" if remote else "",
            install_cmd=[],
            credentials=credentials,
            tools=tools,
            token_cost=_estimate_tokens(tools),
        )


class NpmRegistry(BaseRegistry):
    """Search npm for MCP server packages — no auth required."""

    async def search(self, query: str, limit: int) -> list:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    "https://registry.npmjs.org/-/v1/search",
                    params={"text": f"mcp-server {query}", "size": limit * 2},
                    timeout=TIMEOUT_FETCH_URL,
                )
                r.raise_for_status()
                data = r.json()
        except Exception:
            return []

        results = []
        for obj in data.get("objects", []):
            pkg = obj.get("package", {})
            name = pkg.get("name", "")
            if not name:
                continue
            keywords = [k.lower() for k in (pkg.get("keywords") or [])]
            if not any(k in ("mcp", "model-context-protocol", "mcp-server") for k in keywords):
                continue
            desc = (pkg.get("description") or "").strip()[:MAX_EXPLORE_DESC]
            results.append(ServerInfo(
                id=name,
                name=name,
                description=desc,
                source="npm",
                transport="stdio",
                url="",
                install_cmd=["npx", "-y", name],
                credentials={},
                tools=[],
                token_cost=0,
            ))
            if len(results) >= limit:
                break
        return results

    async def get_server(self, id: str):
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    f"https://registry.npmjs.org/{id}",
                    timeout=TIMEOUT_FETCH_URL,
                )
                r.raise_for_status()
                pkg = r.json()
        except Exception:
            return None

        latest = pkg.get("dist-tags", {}).get("latest", "")
        version_data = pkg.get("versions", {}).get(latest, {})
        desc = (version_data.get("description") or pkg.get("description") or "").strip()
        return ServerInfo(
            id=id,
            name=id,
            description=desc,
            source="npm",
            transport="stdio",
            url="",
            install_cmd=["npx", "-y", id],
            credentials={},
            tools=[],
            token_cost=0,
        )


class MultiRegistry(BaseRegistry):
    """Fan out to all registries, dedup by name, Smithery results first."""

    def __init__(self):
        self._registries = [SmitheryRegistry(), NpmRegistry()]

    async def search(self, query: str, limit: int) -> list:
        tasks = [reg.search(query, limit) for reg in self._registries]
        all_results = await asyncio.gather(*tasks, return_exceptions=True)
        seen = set()
        smithery_results, npm_results = [], []
        for batch in all_results:
            if isinstance(batch, Exception):
                continue
            for srv in batch:
                k = re.sub(r'[^a-z0-9]', '', srv.name.lower())
                if k not in seen:
                    seen.add(k)
                    if srv.source == "smithery":
                        smithery_results.append(srv)
                    else:
                        npm_results.append(srv)
        return (smithery_results + npm_results)[:limit]

    async def get_server(self, id: str):
        for reg in self._registries:
            result = await reg.get_server(id)
            if result:
                return result
        return None


_registry = MultiRegistry()
