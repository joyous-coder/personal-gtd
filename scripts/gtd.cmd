@echo off
setlocal enabledelayedexpansion
set "DIR=%~dp0"
set "MISSING="
for %%m in (config dida models notes report review_note scoring settle) do (
  if not exist "%DIR%lib\%%m.py" set "MISSING=!MISSING! %%m"
)
if not "!MISSING!"=="" (
  echo personal-gtd 安装不完整：缺少源码!MISSING! 1>&2
  echo 只有 .pyc 不可用（字节码与 Python 版本绑定）。用 gtd pack 打源码包重装。 1>&2
  exit /b 2
)
if defined PERSONAL_GTD_PYTHON (
  "%PERSONAL_GTD_PYTHON%" "%DIR%gtd.py" %*
  exit /b %ERRORLEVEL%
)
where python >nul 2>&1
if %ERRORLEVEL%==0 (
  python "%DIR%gtd.py" %*
) else (
  py -3 "%DIR%gtd.py" %*
)
exit /b %ERRORLEVEL%
