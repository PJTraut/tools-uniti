@echo off
setlocal EnableExtensions DisableDelayedExpansion

set "UNITI_BOOTSTRAP=%~dp0scripts\bootstrap.py"

if defined UNITI_PYTHON goto run_override

"%SystemRoot%\System32\where.exe" py >nul 2>nul
if %ERRORLEVEL% EQU 0 goto run_py

"%SystemRoot%\System32\where.exe" python >nul 2>nul
if %ERRORLEVEL% EQU 0 goto run_python

"%SystemRoot%\System32\where.exe" python3 >nul 2>nul
if %ERRORLEVEL% EQU 0 goto run_python3

"%SystemRoot%\System32\where.exe" python3.15 >nul 2>nul
if %ERRORLEVEL% EQU 0 goto run_python315

"%SystemRoot%\System32\where.exe" python3.14 >nul 2>nul
if %ERRORLEVEL% EQU 0 goto run_python314

"%SystemRoot%\System32\where.exe" python3.13 >nul 2>nul
if %ERRORLEVEL% EQU 0 goto run_python313

"%SystemRoot%\System32\where.exe" python3.12 >nul 2>nul
if %ERRORLEVEL% EQU 0 goto run_python312

>&2 echo UNITI requires an installed Python 3.12 or newer.
exit /b 10

:run_override
"%UNITI_PYTHON%" "%UNITI_BOOTSTRAP%" %*
exit /b %ERRORLEVEL%

:run_py
py -3 "%UNITI_BOOTSTRAP%" %*
exit /b %ERRORLEVEL%

:run_python
python "%UNITI_BOOTSTRAP%" %*
exit /b %ERRORLEVEL%

:run_python3
python3 "%UNITI_BOOTSTRAP%" %*
exit /b %ERRORLEVEL%

:run_python315
python3.15 "%UNITI_BOOTSTRAP%" %*
exit /b %ERRORLEVEL%

:run_python314
python3.14 "%UNITI_BOOTSTRAP%" %*
exit /b %ERRORLEVEL%

:run_python313
python3.13 "%UNITI_BOOTSTRAP%" %*
exit /b %ERRORLEVEL%

:run_python312
python3.12 "%UNITI_BOOTSTRAP%" %*
exit /b %ERRORLEVEL%
