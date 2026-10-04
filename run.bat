@echo off
setlocal
cd /d "%~dp0"

set "VENV_PYW=venv\Scripts\pythonw.exe"
set "VENV_PY=venv\Scripts\python.exe"

if exist "%VENV_PYW%" (
    start "" "%VENV_PYW%" main.py %*
) else if exist "%VENV_PY%" (
    start "" "%VENV_PY%" main.py %*
) else (
    where pythonw >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        start "" pythonw main.py %*
    ) else (
        where python >nul 2>&1
        if %ERRORLEVEL% equ 0 (
            python main.py %*
        ) else (
            echo [ERROR] Python environment not found!
            echo Please ensure Python and virtual environment are installed.
            pause
        )
    )
)

endlocal
