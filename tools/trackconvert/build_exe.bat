@echo off
REM Build GT3CourseTool.exe with PyInstaller (run from repo root or this folder)
setlocal
cd /d "%~dp0"

python -m pip install --upgrade pyinstaller
python -m PyInstaller --noconfirm --windowed --onefile --name GT3CourseTool --paths . course_tool_gui.py

echo.
echo Output: dist\GT3CourseTool.exe
endlocal
