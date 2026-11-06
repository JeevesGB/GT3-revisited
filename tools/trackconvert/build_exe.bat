@echo off
REM Build standalone Course Tool exe (requires PyInstaller)
cd /d "%~dp0"
py -m pip install -r requirements.txt pyinstaller
py -m PyInstaller --noconfirm --windowed --name GT3CourseTool ^
  --paths . ^
  --add-data "icons;icons" ^
  --add-data "blender;blender" ^
  --icon icons\app_256.png ^
  main.py
echo.
echo Output: dist\GT3CourseTool\GT3CourseTool.exe
