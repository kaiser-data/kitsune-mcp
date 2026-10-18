# /// script
# dependencies = ["mcp~=1.27"]
# ///
"""Demo MCP server for the Kitsune hot-reload GIF.

It has one planted bug: get_weather labels Fahrenheit as Celsius, so Berlin
comes back at a sweltering 59°C. The agent is meant to spot it, fix the
conversion, reload("dev") and call the tool again. See README.md here.

No network, no API key: readings are fixed so every take of the demo matches.
Needs the mcp 1.x SDK (mcp 2.x renamed FastMCP). The inline script metadata
above pins it, so `uv run weather_server.py` just works.
Reset the bug before another take with: git checkout -- weather_server.py
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("demo-weather")

# Readings as the (pretend) upstream API returns them: Fahrenheit.
_READINGS_F = {
    "berlin": 59.0,
    "tokyo": 71.6,
    "new york": 50.0,
    "sydney": 77.0,
}


def _to_celsius(fahrenheit: float) -> float:
    return fahrenheit  # BUG: missing (f - 32) * 5 / 9


@mcp.tool()
def get_weather(city: str) -> str:
    """Current temperature for a city, in degrees Celsius."""
    reading = _READINGS_F.get(city.strip().lower())
    if reading is None:
        known = ", ".join(c.title() for c in _READINGS_F)
        return f"No data for {city!r}. Known cities: {known}"
    return f"{city.title()}: {_to_celsius(reading):.0f}°C"


if __name__ == "__main__":
    mcp.run()
