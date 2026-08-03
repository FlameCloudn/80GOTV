@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_fixed_tunnel.ps1"
if errorlevel 1 pause
