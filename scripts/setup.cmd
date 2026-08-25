@echo off
rem The wizard is a bash script, and cmd.exe and PowerShell cannot run one.
rem This finds the bash that Git for Windows installs and hands the run to it,
rem with every argument passed through: setup.cmd azure runs the azure stage.
rem
rem System32\bash.exe is left out on purpose. That one is the WSL launcher, and
rem a wizard that ran inside WSL would write the token to the Linux home while
rem the agent reads the Windows one.
rem
rem HERE turns into forward slashes before bash sees it. In a path of
rem backslashes dirname finds no separator, answers ".", and the wizard then
rem looks for tk in the calling directory instead of beside itself.
setlocal enabledelayedexpansion
set "HERE=%~dp0"
set "HERE=%HERE:\=/%"
set "BASH="
if exist "%ProgramFiles%\Git\bin\bash.exe" set "BASH=%ProgramFiles%\Git\bin\bash.exe"
if not defined BASH if exist "%ProgramFiles(x86)%\Git\bin\bash.exe" set "BASH=%ProgramFiles(x86)%\Git\bin\bash.exe"
if not defined BASH if exist "%LOCALAPPDATA%\Programs\Git\bin\bash.exe" set "BASH=%LOCALAPPDATA%\Programs\Git\bin\bash.exe"
if not defined BASH for /f "delims=" %%G in ('where git.exe 2^>nul') do (
  if not defined BASH if exist "%%~dpG..\bin\bash.exe" set "BASH=%%~dpG..\bin\bash.exe"
)
if not defined BASH (
  >&2 echo Setup needs the bash that Git for Windows installs.
  >&2 echo Get it from https://git-scm.com/download/win, then run this again.
  exit /b 1
)
"%BASH%" "%HERE%setup.sh" %*
exit /b !errorlevel!
