@echo off
REM OpenForge EDA Desktop Launcher
set OPENFORGE_HOME=%~dp0
set PYTHONPATH=%OPENFORGE_HOME%packages\core\src;%OPENFORGE_HOME%packages\desktop\src;%OPENFORGE_HOME%packages\cli\src;%OPENFORGE_HOME%packages\api\src
python -c "from openforge_desktop.main import main; main()" %*
