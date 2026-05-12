from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("kitsune-mcp")
except PackageNotFoundError:
    __version__ = "unknown"
