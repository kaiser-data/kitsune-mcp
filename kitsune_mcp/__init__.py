from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("kitsune-mcp")
except PackageNotFoundError:
    __version__ = "unknown"
