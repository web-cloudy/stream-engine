@echo off
rem ===== Server B (edge): mirrors Server A and serves viewers =====
rem  EDIT the address below to point at YOUR Server A:
set ORIGIN=http://CHANGE-ME-SERVER-A-IP:5000
"%~dp0StreamEngineServer\StreamEngineServer.exe" --role edge --port 5000 --origin %ORIGIN%
pause
