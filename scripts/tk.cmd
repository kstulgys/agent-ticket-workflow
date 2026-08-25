@echo off
rem tk for cmd.exe and PowerShell, which read no shebang. Git Bash and WSL run
rem scripts/tk itself.
rem
rem Each candidate is asked to import a module before it is trusted. On Windows
rem the name python3, and often python, is the Microsoft Store stub: it prints
rem an advert and exits 9009, and the probe below fails it so the next name
rem gets its turn. py is the launcher that ships with every python.org install.
setlocal enabledelayedexpansion
set "TK=%~dp0tk"
for %%I in (py python python3) do (
  %%I -c "import sys" >nul 2>&1 && (
    %%I "%TK%" %*
    exit /b !errorlevel!
  )
)
>&2 echo tk needs Python 3.11 or newer on PATH.
>&2 echo Install it from https://www.python.org/downloads/windows/ and select
>&2 echo "Add python.exe to PATH", then run this again.
exit /b 1
