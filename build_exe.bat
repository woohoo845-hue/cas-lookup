@echo off
echo ============================================
echo  CAS Lookup - Build EXE
echo ============================================
echo.

:: Check Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3.9+ and add to PATH.
    pause
    exit /b 1
)

echo [1/3] Installing dependencies...
pip install streamlit requests beautifulsoup4 pyinstaller --quiet
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

echo [2/3] Building EXE (this takes 2-5 minutes)...
pyinstaller cas_lookup.spec --noconfirm
if errorlevel 1 (
    echo ERROR: Build failed. See output above for details.
    pause
    exit /b 1
)

echo [3/3] Done!
echo.
echo ============================================
echo  EXE created at:  dist\CAS_Lookup.exe
echo  Double-click it to run the app.
echo  Your browser will open automatically.
echo  Use the Network IP shown to open on phone.
echo ============================================
echo.
pause
