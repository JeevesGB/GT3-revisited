# GT3 Track Extractor

Extract Gran Turismo 3 course files to **glTF / Blender**, edit, and **pack back** into game-compatible files.

Lives in the GT3-revisited tree under `tools/trackconvert`.

## Setup

```bat
cd tools\trackconvert
install_requirements.bat
```

## CLI

```bat
REM Inspect a course
python -m gt3course info path\to\testcourse.gz

REM Extract → work/ + blender/ (road.gltf, road.obj, scenery, textures)
python -m gt3course extract path\to\testcourse.gz out\testcourse

REM Pack work folder → game file (applies Blender road/scenery OBJs if present)
python -m gt3course pack out\testcourse\work out\testcourse.gz
```

## GUI

```bat
run.bat
```

## Round-trip rules (game load)

- Unpack writes `structure_lock.json` with exact per-slot sizes.
- Pack **fails** if any slot size changes — geometry write-back is **in-place only**.
- Prefer editing positions (use `road_positions.f32` or keep topology when using OBJ).
- Full from-scratch tracks still need a valid template course (clone structure, reshape geometry).

## Layout after extract

```
out/<name>/
  work/                 unpacked 48-slot blobs + road/ + ai/ + structure_lock.json
  blender/
    road.gltf + .bin    road mesh for Blender
    road.obj            alternate mesh
    road_positions.f32  exact game-space verts (best write-back)
    scenery/            GTM1 scenery OBJ + textures
    textures/
  extract_summary.json
```
