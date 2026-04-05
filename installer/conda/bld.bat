@echo off
REM ============================================================================
REM OpenForge EDA - Conda build script (Windows)
REM ============================================================================

echo ==^> Building OpenForge EDA for conda (Windows)

REM ---------------------------------------------------------------------------
REM Build and install Python packages
REM ---------------------------------------------------------------------------
echo ==^> Installing Python packages

for %%P in (core cli api desktop crypto) do (
    if exist "%SRC_DIR%\packages\%%P" (
        echo     Installing %%P...
        "%PYTHON%" -m pip install --no-deps --no-build-isolation "%SRC_DIR%\packages\%%P"
        if errorlevel 1 exit /b 1
    )
)

REM ---------------------------------------------------------------------------
REM Build Rust tools
REM ---------------------------------------------------------------------------
echo ==^> Building Rust tools

set CARGO_HOME=%SRC_DIR%\.cargo
if not exist "%CARGO_HOME%" mkdir "%CARGO_HOME%"

cd "%SRC_DIR%"
cargo build --release
if errorlevel 1 exit /b 1

for %%T in (openforge-ct openforge-sca openforge-entropy openforge-lint openforge-wave) do (
    if exist "%SRC_DIR%\target\release\%%T.exe" (
        copy /Y "%SRC_DIR%\target\release\%%T.exe" "%LIBRARY_BIN%\%%T.exe"
        echo     Installed %%T.exe
    ) else (
        echo     WARNING: %%T.exe not found
    )
)

REM ---------------------------------------------------------------------------
REM Build web frontend
REM ---------------------------------------------------------------------------
echo ==^> Building web frontend

if exist "%SRC_DIR%\packages\web\package.json" (
    cd "%SRC_DIR%\packages\web"
    call npm ci
    if errorlevel 1 exit /b 1
    call npm run build
    if errorlevel 1 exit /b 1
    if exist "%SRC_DIR%\packages\web\build" (
        mkdir "%PREFIX%\share\openforge\web" 2>nul
        xcopy /E /I /Y "%SRC_DIR%\packages\web\build\*" "%PREFIX%\share\openforge\web\"
    )
)

echo ==^> Build complete
