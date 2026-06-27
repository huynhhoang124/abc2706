@echo off
cd /d "%~dp0"
echo ====================================================
echo   TIEN HANH DONG GOI IELTS WRITING HELPER (WinAssist)
echo ====================================================
echo.
echo 1. Dang cai dat PyInstaller trong moi truong ao...
.\venv\Scripts\pip install pyinstaller
if %errorlevel% neq 0 (
    echo Co loi xay ra khi cai dat PyInstaller.
    pause
    exit /b
)
echo.
echo 2. Dang dong goi ung dung thanh file EXE duy nhat (chay an)...
.\venv\Scripts\pyinstaller --noconsole --onefile --name="WinAssist" main.py
if %errorlevel% neq 0 (
    echo Co loi xay ra khi dong goi bang PyInstaller.
    pause
    exit /b
)
echo.
echo ====================================================
echo   DONG GOI HOAN TAT!
echo   File chay duoc nam tai: dist\WinAssist.exe
echo ====================================================
echo.
pause
exit
