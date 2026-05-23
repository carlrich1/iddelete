@echo off
REM Convenience launcher (Windows).
setlocal
cd /d "%~dp0\.."

if not exist backend\.venv (
    python -m venv backend\.venv
    backend\.venv\Scripts\python -m pip install -U pip
    backend\.venv\Scripts\pip install -r backend\requirements.txt
)

REM Load .env if present
if exist backend\.env (
    for /f "usebackq tokens=1,* delims==" %%A in ("backend\.env") do (
        if not "%%A"=="" if not "%%A:~0,1"=="#" set %%A=%%B
    )
)

backend\.venv\Scripts\python -m backend.app
endlocal
