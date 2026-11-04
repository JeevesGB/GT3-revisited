# GT3 Course Tool

Professional PyQt6 workspace for unpacking, map-editing, Blender export, and packing GT3 course files (GT3-revisited).

## Run

```bash
pip install PyQt6
python tools/trackconvert/course_tool_qt.py
```

## Workspace features

- Dark Fusion theme, dockable **Inspector / Overview / Output**
- Persistent window layout, last paths, **recent courses** (`QSettings`)
- Dirty-state tracking with save prompt on exit
- Status bar: clean/modified · stats · work path
- Map: zoom / pan / drag handles (grid, AI, checkpoints)
- Background **batch** with progress + cancel
- Full edit pipeline: JSON · Patch GTRW/AI · Pack · OBJ import/export

## Modules

| File | Role |
|------|------|
| `course_tool_qt.py` | Main workspace GUI |
| `course_lib.py` | Unpack / pack / patch / zip |
| `blender_export.py` | Road OBJ + Blender helper |
| `mesh_io.py` | OBJ→GTRW, scenery dump |
| `course_tool_gui.py` | Legacy tkinter UI |

## PyInstaller

```bash
pyinstaller --noconfirm --windowed --onefile --name GT3CourseTool ^
  --paths tools/trackconvert tools/trackconvert/course_tool_qt.py
```
