@echo off
rem Double-click to start the Hanafuda app in Docker.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" start
pause
