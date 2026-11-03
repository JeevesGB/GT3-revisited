#!/usr/bin/env python3
"""Export unpacked GT3 course work folders to Blender-friendly OBJ + JSON."""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import course_lib as lib

BLENDER_IMPORT_SCRIPT = r'''"""
Blender import helper for GT3 Course Tool export folders.

In Blender: Scripting → Open this file → Run Script
Or: blender --python import_gt3_course.py -- /path/to/export_folder
"""
import json
import sys
from pathlib import Path

import bpy

def find_export_dir() -> Path:
    argv = sys.argv
    if "--" in argv:
        i = argv.index("--")
        if i + 1 < len(argv):
            return Path(argv[i + 1])
    return Path(__file__).resolve().parent

def main():
    d = find_export_dir()
    road = d / "road.obj"
    if not road.is_file():
        raise SystemExit(f"road.obj not found in {d}")

    bpy.ops.wm.obj_import(filepath=str(road))
    for name in ("walls.obj", "ai_lines.obj"):
        p = d / name
        if p.is_file():
            bpy.ops.wm.obj_import(filepath=str(p))

    empties = d / "empties.json"
    if empties.is_file():
        data = json.loads(empties.read_text(encoding="utf-8"))
        grid_coll = bpy.data.collections.new("GT3_Grid")
        bpy.context.scene.collection.children.link(grid_coll)
        for g in data.get("grid", []):
            bpy.ops.object.empty_add(type="PLAIN_AXES", location=g["location"])
            obj = bpy.context.active_object
            obj.name = f"grid_{g['index']}"
            obj.rotation_euler[2] = g.get("yaw", 0)
            grid_coll.objects.link(obj)
            try:
                bpy.context.scene.collection.objects.unlink(obj)
            except Exception:
                pass
        cp_coll = bpy.data.collections.new("GT3_Checkpoints")
        bpy.context.scene.collection.children.link(cp_coll)
        for c in data.get("checkpoints", []):
            curve_data = bpy.data.curves.new(f"cp_{c['index']}", type="CURVE")
            curve_data.dimensions = "3D"
            spline = curve_data.splines.new("POLY")
            spline.points.add(1)
            p0, p1 = c["p0"], c["p1"]
            spline.points[0].co = (p0[0], p0[1], p0[2], 1)
            spline.points[1].co = (p1[0], p1[1], p1[2], 1)
            curve_obj = bpy.data.objects.new(f"cp_{c['index']}", curve_data)
            cp_coll.objects.link(curve_obj)

    print(f"GT3 course imported from {d}")

if __name__ == "__main__":
    main()
'''


def parse_gtrw_mesh(gtrw: bytes) -> dict[str, Any]:
    if len(gtrw) < 0x60 or gtrw[0:4] != b"GTRW":
        raise ValueError("not GTRW")
    nseg = lib.u32(gtrw, 0x30)
    seg_off = lib.u32(gtrw, 0x34)
    nwall = lib.u32(gtrw, 0x38)
    wall_off = lib.u32(gtrw, 0x3C)

    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    seg_info = []

    for i in range(nseg):
        s = seg_off + i * 0x40
        if s + 0x40 > len(gtrw):
            break
        nv = lib.u16(gtrw, s)
        nt = lib.u16(gtrw, s + 2)
        voff = lib.u32(gtrw, s + 4)
        toff = lib.u32(gtrw, s + 8)
        base = len(vertices)
        for k in range(nv):
            o = voff + k * 16
            if o + 12 > len(gtrw):
                break
            vertices.append((lib.f32(gtrw, o), lib.f32(gtrw, o + 4), lib.f32(gtrw, o + 8)))
        for k in range(nt):
            t = toff + k * 16
            if t + 16 > len(gtrw):
                break
            a, b, c = lib.u16(gtrw, t), lib.u16(gtrw, t + 2), lib.u16(gtrw, t + 4)
            mat = lib.u16(gtrw, t + 8)
            if a < nv and b < nv and c < nv:
                faces.append((base + a, base + b, base + c, mat))
        seg_info.append({"index": i, "vertices": nv, "triangles": nt})

    walls = []
    for i in range(nwall):
        o = wall_off + i * 16
        if o + 16 > len(gtrw):
            break
        walls.append((lib.f32(gtrw, o), lib.f32(gtrw, o + 4), lib.f32(gtrw, o + 8)))

    return {
        "vertices": vertices,
        "faces": faces,
        "walls": walls,
        "segments": seg_info,
        "course_id": lib.u32(gtrw, 0x14),
        "length": lib.f32(gtrw, 0x18),
    }


def write_obj(path: Path, vertices, faces, *, name: str = "road", flip_yz: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    by_mat: dict[int, list[tuple[int, int, int]]] = {}
    for a, b, c, mat in faces:
        by_mat.setdefault(mat, []).append((a, b, c))

    lines = [f"# GT3 course road mesh — {name}", f"o {name}", "mtllib road.mtl"]
    for x, y, z in vertices:
        if flip_yz:
            lines.append(f"v {x:.6f} {-z:.6f} {y:.6f}")
        else:
            lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")
    for mat in sorted(by_mat.keys()):
        lines.append(f"g mat_{mat}")
        lines.append(f"usemtl mat_{mat}")
        for a, b, c in by_mat[mat]:
            lines.append(f"f {a + 1} {b + 1} {c + 1}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    palette = [
        (0.55, 0.55, 0.55),
        (0.85, 0.25, 0.25),
        (0.75, 0.55, 0.25),
        (0.30, 0.65, 0.30),
        (0.80, 0.75, 0.40),
        (0.40, 0.40, 0.80),
        (0.70, 0.40, 0.70),
        (0.30, 0.70, 0.70),
    ]
    mtl = ["# GT3 road materials"]
    for mat in sorted(by_mat.keys()):
        r, g, b = palette[mat % len(palette)]
        mtl += [f"newmtl mat_{mat}", f"Kd {r:.3f} {g:.3f} {b:.3f}", "d 1.0", ""]
    (path.parent / "road.mtl").write_text("\n".join(mtl), encoding="utf-8")


def write_walls_obj(path: Path, walls, *, flip_yz: bool = False) -> None:
    lines = ["# GT3 wall points", "o walls"]
    for x, y, z in walls:
        if flip_yz:
            lines.append(f"v {x:.6f} {-z:.6f} {y:.6f}")
        else:
            lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_ai_obj(path: Path, lines_data, *, flip_yz: bool = False) -> None:
    out = ["# GT3 AI control polylines"]
    vbase = 1
    for L in lines_data:
        pts = L.get("points", [])
        if len(pts) < 2:
            continue
        out.append(f"o ai_line_{L.get('line', 0)}")
        for p in pts:
            x, z = float(p["x"]), float(p["z"])
            if flip_yz:
                out.append(f"v {x:.6f} {-z:.6f} 0.000000")
            else:
                out.append(f"v {x:.6f} 0.000000 {z:.6f}")
        for i in range(len(pts) - 1):
            out.append(f"l {vbase + i} {vbase + i + 1}")
        if L.get("closed"):
            out.append(f"l {vbase + len(pts) - 1} {vbase}")
        vbase += len(pts)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def write_empties_json(path: Path, editable_dir: Path, *, flip_yz: bool = False) -> None:
    def conv(x, y, z):
        return [x, -z, y] if flip_yz else [x, y, z]

    grid = [
        {
            "index": g["index"],
            "location": conv(float(g["x"]), float(g["y"]), float(g["z"])),
            "yaw": float(g["yaw"]),
        }
        for g in lib.load_grid(editable_dir)
    ]
    cps = [
        {
            "index": c["index"],
            "p0": conv(float(c["x0"]), 0.0, float(c["z0"])),
            "p1": conv(float(c["x1"]), 0.0, float(c["z1"])),
            "distance": float(c["distance"]),
        }
        for c in lib.load_checkpoints(editable_dir)
    ]
    path.write_text(
        json.dumps({"coordinate_system": "z_up" if flip_yz else "y_up", "grid": grid, "checkpoints": cps}, indent=2)
        + "\n",
        encoding="utf-8",
    )


def export_for_blender(editable_dir: Path, out_dir: Path, *, z_up: bool = True) -> str:
    editable_dir = Path(editable_dir)
    out_dir = Path(out_dir)
    gtrw_path = editable_dir / "road" / "GTRW.bin"
    if not gtrw_path.is_file():
        raise FileNotFoundError(f"missing {gtrw_path} — unpack a course first")

    mesh = parse_gtrw_mesh(gtrw_path.read_bytes())
    out_dir.mkdir(parents=True, exist_ok=True)

    write_obj(out_dir / "road.obj", mesh["vertices"], mesh["faces"], name="gt3_road", flip_yz=z_up)
    write_walls_obj(out_dir / "walls.obj", mesh["walls"], flip_yz=z_up)

    ai_lines = lib.load_ai_lines(editable_dir)
    if ai_lines:
        write_ai_obj(out_dir / "ai_lines.obj", ai_lines, flip_yz=z_up)

    write_empties_json(out_dir / "empties.json", editable_dir, flip_yz=z_up)
    (out_dir / "import_gt3_course.py").write_text(BLENDER_IMPORT_SCRIPT, encoding="utf-8")

    meta = {
        "format": "gt3-blender-v1",
        "coordinate_system": "z_up" if z_up else "y_up",
        "source_work": str(editable_dir),
        "course_id": mesh["course_id"],
        "length": mesh["length"],
        "vertices": len(mesh["vertices"]),
        "faces": len(mesh["faces"]),
        "walls": len(mesh["walls"]),
        "segments": len(mesh["segments"]),
        "note": "Visual edit in Blender. Mesh→GTRW round-trip not implemented yet.",
    }
    (out_dir / "export_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (out_dir / "README_BLENDER.txt").write_text(
        "GT3 Course → Blender\n\n"
        "1. File → Import → Wavefront (.obj) → road.obj\n"
        "2. Or run import_gt3_course.py in Blender Scripting\n"
        "3. Materials mat_N = GTRW surface types (tarmac/kerb/dirt/...)\n\n"
        "Z-up by default (Blender). Grid empties + checkpoint curves via the helper script.\n"
        "Road mesh write-back to GTRW is not available yet — use Course Tool JSON for grid/AI.\n",
        encoding="utf-8",
    )
    return (
        f"Blender export → {out_dir}\n"
        f"  vertices={len(mesh['vertices'])} faces={len(mesh['faces'])} walls={len(mesh['walls'])}\n"
        f"  Import road.obj in Blender (or run import_gt3_course.py)"
    )
