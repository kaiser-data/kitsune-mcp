Output demo.mp4

Set Shell "zsh"
Set FontSize 24
Set Width 1200
Set Height 760
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

Type `Use kitsune: connect("uv run weather_server.py", name="dev"), then call get_weather for Berlin before reading any code. If it looks wrong, fix the code, reload("dev") and check again. Answer in one short line.`
Sleep 800ms
Enter

Wait+Screen@480s /15 ?°C|15 degrees/
Sleep 8s

Hide
Ctrl+C
Ctrl+C
Sleep 1s
