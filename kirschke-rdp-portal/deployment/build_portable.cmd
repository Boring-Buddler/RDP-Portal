@echo off
setlocal
powershell -NoProfile -File "%~dp0build_portable.ps1" %*
exit /b %ERRORLEVEL%
