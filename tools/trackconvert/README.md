# GT3 Course Tool

Standalone unpack / preview / edit / pack utility for Gran Turismo 3 course files
(as used by GT3-revisited).

## Features

| Area | What you can do |
|------|------------------|
| **Container** | Unpack/pack 48-slot course files; opaque blob round-trip |
| **Start grid** | Edit positions + yaw (in-place, same count) |
| **Checkpoints** | Edit sector/line segments |
| **Markers** | Edit distance markers on the race line |
| **AI lines** | Edit control points (x, z, radius, heading, flags) on lines 0–6 |
| **Materials** | Read-only triangle material histogram |
| **Map** | Top-down preview: grid, checkpoints, AI, sampled walls |

## Layout

```text
tools/course_tool/
  course_lib.py
  course_tool_gui.py
  build_exe.bat
  README.md
```

## Run

```bash
python tools/course_tool/course_tool_gui.py

# CLI
python tools/course_tool/course_lib.py info course
python tools/course_tool/course_lib.py unpack course out/work
python tools/course_tool/course_lib.py patch-gtrw out/work
python tools/course_tool/course_lib.py patch-ai out/work
python tools/course_tool/course_lib.py pack out/work course_mod
```

## GUI workflow

1. Browse course → **Unpack**
2. **Map** tab to orient; toggle layers
3. Edit tables → **Apply to row**
4. **Patch GTRW** and/or **Patch AI**
5. **Pack course** for GT3-revisited

## Standalone EXE

```bat
cd tools\course_tool
build_exe.bat
```

→ `dist/GT3CourseTool.exe`

## Limits

- Cannot add/remove grid slots, checkpoints, markers, or AI points
- Scenery / visibility / env: copy-through only
- Always keep backups of original courses
