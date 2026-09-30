@echo off
rem Strategy lab: dashboard + backtest queue. Double-click, then open the address it prints.
rem Optional port: start_lab.cmd 8770
cd /d "%~dp0"
set PYTHONUTF8=1
python serve.py %*
pause
