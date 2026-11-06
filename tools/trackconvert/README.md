# GT3 Course Tool

Unpack, view, edit, and export Gran Turismo 3 course files.

## Layout

```
trackconvert/
  main.py                 # launch: python main.py
  requirements.txt
  build_exe.bat
  icons/
  blender/
    import_gt3_course.py  # Blender helper script
  gt3course/
    core/                 # formats only
      course.py           # unpack / pack / grid / AI / CP
      tex1.py             # Tex1 texture decode
      mesh_io.py          # OBJ write-back helpers
    export/
      blender.py          # track package (OBJ + MTL)
      gltf.py             # glTF 2.0
      gtm1.py             # scenery mesh + textures
    ui/
      app.py              # main window
      map_view.py         # top-down map editor
      viewer.py           # 3D orbit viewer
      batch.py
      theme.py
```

## Run

```bash
cd tools/trackconvert
pip install -r requirements.txt
python main.py
```

Or: `python -m gt3course`
