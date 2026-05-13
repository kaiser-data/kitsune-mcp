"""Adapter for database MCP servers: Postgres, SQLite, MySQL."""

from kitsune_mcp.adapters import Adapter, _register

_SETUP_HINTS: dict[str, str] = {
    "DATABASE_URL": "Format: postgresql://user:password@host:5432/dbname",
    "POSTGRES_URL": "Format: postgresql://user:password@host:5432/dbname",
    "POSTGRESQL_URL": "Format: postgresql://user:password@host:5432/dbname",
    "MYSQL_URL": "Format: mysql://user:password@host:3306/dbname",
    "SQLITE_DB_PATH": "Provide the absolute path to your .db file: /path/to/database.db",
    "DATABASE_URI": "Format: postgresql://user:password@host:5432/dbname or sqlite:///path/to/db",
}


class DatabaseAdapter(Adapter):
    CATEGORY = "database"
    KNOWN_IDS = frozenset({
        "server-postgres",
        "mcp-server-sqlite",
        "postgres-mcp-server",
        "mcp-mysql",
    })

    def setup_hint(self, server_id: str, missing_creds: list[str]) -> str:
        for cred in missing_creds:
            hint = _SETUP_HINTS.get(cred.upper())
            if hint:
                return hint
        # Generic hint if no specific match
        if missing_creds:
            return "Database servers need a connection URL — check the server docs for the format"
        return ""


_register(DatabaseAdapter())
