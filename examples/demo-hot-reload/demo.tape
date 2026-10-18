Output demo.mp4

Set Shell "zsh"
Set FontSize 20
Set Width 1400
Set Height 860
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 25ms
Set WindowBar Colorful

Hide
Type "cd ~/my-weather-mcp && unset CLAUDECODE CLAUDE_PID CLAUDE_EFFORT ${(k)parameters[(I)CLAUDE_CODE_*]} && clear"
Enter
Type `claude() { command claude --strict-mcp-config --mcp-config ~/.kitsune-demo-mcp.json --setting-sources project --allowedTools mcp__kitsune Read Edit "$@"; } && clear`
Enter
Sleep 500ms
Type "claude"
Enter
Wait+Screen@60s /Try "/
Sleep 1s
Show

Type `Connect my MCP server with kitsune: connect("uv run --with mcp~=1.27 python weather_server.py", name="dev"). Get the weather for Berlin. If it looks wrong, fix the code, reload("dev") and check again.`
Sleep 800ms
Enter

Wait+Screen@480s /15 ?°C|15 degrees/
Sleep 6s

Hide
Ctrl+C
Ctrl+C
Sleep 1s
