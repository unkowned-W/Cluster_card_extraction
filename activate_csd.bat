@echo off
if not defined CSD_API_HOME set "CSD_API_HOME=D:\CCDC\ccdc-software\csd-python-api"
if exist "%CSD_API_HOME%\miniconda\Scripts\activate.bat" (
    call "%CSD_API_HOME%\miniconda\Scripts\activate.bat"
) else (
    echo CSD activation script not found: %CSD_API_HOME%\miniconda\Scripts\activate.bat
)
cd /d "%~dp0"
echo CSD Python API environment activated.
python -c "import ccdc, sys; print(sys.executable); print('ccdc ok')"
