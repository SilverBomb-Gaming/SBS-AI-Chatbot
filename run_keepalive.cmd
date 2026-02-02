@echo off
setlocal
set "PROJECT_ROOT=%~dp0"
set "PYTHON_EXE=%PROJECT_ROOT%.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
  echo Virtual environment python not found: %PYTHON_EXE%
  exit /b 1
)
echo PYTHON_EXE=%PYTHON_EXE%
pushd "%PROJECT_ROOT%" >NUL
"%PYTHON_EXE%" tools\virtual_controller_keepalive.py %*
set "EXIT_CODE=%ERRORLEVEL%"
popd >NUL
exit /b %EXIT_CODE%
