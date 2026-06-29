@echo off
rem ===== Server A (origin): clients upload here =====
"%~dp0StreamEngineServer\StreamEngineServer.exe" --role origin --port 5000
pause
