#!/usr/bin/env python3
"""
OBJ ↔ GTRW helpers for the course tool.

Write-back strategy (pragmatic):
  - Parse road.obj vertices in order
  - If count matches GTRW vertex stream order, overwrite XYZ in place
  - Topology (indices, materials, spatial grids) is left unchanged
  - Full remesh / add-remove triangles is not supported
"""

from __future__ import annotations

import re
import struct
from pathlib import Path
from typing import Any

import course_lib as lib
from blender_export import parse_gtrw_mesh


def load_obj_vertices(path: Path) -> list[tuple[float, float, float]]:
    verts: list[tuple[float, float, float]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("v "):
            parts = line.split()
            if len(parts) >= 4:
                verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
    return verts


def obj_to_gtrw_space(
    verts: list[tuple[float, float, float]], *, from_z_up: bool
) -> list[tuple[float, float, float]]:
    """Convert Blender Z-up export back to GT3 Y-up if needed."""
    if not from_z_up:
        return verts
    # Export used (x, -z, y) for Z-up → inverse: x, z_out=y, y_out=-y_blender? 
    # Export: x' = x, y' = -z, z' = y  =>  x = x', y = z', z = -y'
    out = []
    for x, y, z in verts:
        out.append((x, z, -y))
    return out


def write_gtrw_vertices(gtrw: bytearray, verts: list[tuple[float, float, float]]) -> int:
    """Overwrite vertex positions in segment order. Returns number written."""
    nseg = lib.u32(gtrw, 0x30)
    seg_off = lib.u32(gtrw, 0x34)
    vi = 0
    for i in range(nseg):
        s = seg_off + i * 0x40
        if s + 0x40 > len(gtrw):
            break
        nv = lib.u16(gtrw, s)
        voff = lib.u32(gtrw, s + 4)
        for k in range(nv):
            if vi >= len(verts):
                raise ValueError(
                    f"OBJ has fewer vertices than GTRW (need more after segment {i} vert {k})"
                )
            o = voff + k * 16
            x, y, z = verts[vi]
            lib.write_f32(gtrw, o, x)
            lib.write_f32(gtrw, o + 4, y)
            lib.write_f32(gtrw, o + 8, z)
            # word at +12 (attrs) preserved
            vi += 1
    if vi != len(verts):
        raise ValueError(
            f"vertex count mismatch: OBJ={len(verts)} GTRW_stream={vi} "
            "(export must be unedited topology / same vertex order)"
        )
    return vi


def import_obj_into_gtrw(
    editable_dir: Path,
    obj_path: Path,
    *,
    from_z_up: bool = True,
) -> str:
    """Load OBJ, write vertex positions into road/GTRW.bin + blob."""
    gtrw_path = editable_dir / "road" / "GTRW.bin"
    if not gtrw_path.is_file():
        raise FileNotFoundError(f"missing {gtrw_path}")
    verts = load_obj_vertices(obj_path)
    if not verts:
        raise ValueError("no vertices in OBJ")
    verts = obj_to_gtrw_space(verts, from_z_up=from_z_up)

    # Validate count first
    mesh = parse_gtrw_mesh(gtrw_path.read_bytes())
    if len(verts) != len(mesh["vertices"]):
        raise ValueError(
            f"vertex count mismatch: OBJ={len(verts)} GTRW={len(mesh['vertices'])}. "
            "Only in-place edits (same topology) are supported."
        )

    gtrw = bytearray(gtrw_path.read_bytes())
    n = write_gtrw_vertices(gtrw, verts)
    gtrw_path.write_bytes(gtrw)

    messages = [f"wrote {n} vertices into {gtrw_path}"]
    man = editable_dir / "manifest.json"
    if man.is_file():
        import json

        manifest = json.loads(man.read_text(encoding="utf-8"))
        for slot in manifest.get("slots", []):
            if slot.get("slot") == lib.SLOT_ROAD:
                blob = editable_dir / slot["blob"]
                blob.write_bytes(gtrw)
                messages.append(f"updated {blob}")
                break
    messages.append("Topology/materials/spatial grids unchanged. Pack course to use in-game.")
    return "\n".join(messages)


def export_gtm1_scenery(editable_dir: Path, out_dir: Path, *, z_up: bool = True) -> str:
    """
    Export scenery-related slots for inspection.
    Full GTM1 decode needs the game's gtm1 module (not in this tool snapshot).
    We export:
      - raw slot blobs
      - a crude vertex point-cloud OBJ by scanning float triplets (heuristic)
    """
    editable_dir = Path(editable_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    man_path = editable_dir / "manifest.json"
    if not man_path.is_file():
        raise FileNotFoundError("manifest.json missing — unpack first")

    import json

    manifest = json.loads(man_path.read_text(encoding="utf-8"))
    scenery_slots = {1, 5, 9, 13, 21, 22, 23, 24, 27}
    exported = []
    for entry in manifest.get("slots", []):
        slot = int(entry["slot"])
        if slot not in scenery_slots:
            continue
        blob_path = editable_dir / entry["blob"]
        if not blob_path.is_file():
            continue
        data = blob_path.read_bytes()
        tag = entry.get("tag") or "bin"
        name = f"slot_{slot:02d}_{tag}"
        (out_dir / f"{name}.bin").write_bytes(data)
        # Heuristic: dump plausible world-scale float triplets as point cloud
        pts = _heuristic_float_points(data)
        if pts:
            lines = [f"# heuristic points from {name} ({len(pts)} pts)", f"o {name}"]
            for x, y, z in pts:
                if z_up:
                    lines.append(f"v {x:.6f} {-z:.6f} {y:.6f}")
                else:
                    lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")
            (out_dir / f"{name}_points.obj").write_text("\n".join(lines) + "\n", encoding="utf-8")
        exported.append({"slot": slot, "tag": tag, "size": len(data), "heuristic_points": len(pts)})

    (out_dir / "scenery_index.json").write_text(json.dumps(exported, indent=2) + "\n", encoding="utf-8")
    (out_dir / "README_SCENERY.txt").write_text(
        "GT3 scenery export (best-effort)\n"
        "================================\n\n"
        "Raw GTM1 (and related) slot blobs are saved as .bin.\n"
        "*_points.obj files are HEURISTIC point clouds (aligned float triplets\n"
        "in a plausible coordinate range). They are for orientation only — not\n"
        "a full mesh with triangles/textures.\n\n"
        "True GTM1 mesh export requires the game's gtm1 parser (nodes/chunks/\n"
        "texture sets). When that is linked into the tool, this will be replaced\n"
        "with proper OBJ/glTF geometry.\n",
        encoding="utf-8",
    )
    return (
        f"Scenery export → {out_dir}\n"
        f"  {len(exported)} slots\n"
        f"  See scenery_index.json and README_SCENERY.txt"
    )


def _heuristic_float_points(data: bytes, limit: int = 200000) -> list[tuple[float, float, float]]:
    """Scan for little-endian float triplets that look like metres-scale positions."""
    pts: list[tuple[float, float, float]] = []
    n = len(data)
    # 4-byte aligned scan
    for o in range(0, n - 12, 4):
        try:
            x, y, z = struct.unpack_from("<fff", data, o)
        except struct.error:
            continue
        if not all(map(_finite_reasonable, (x, y, z))):
            continue
        # Prefer points near each other in stream that look like mesh verts
        pts.append((x, y, z))
        if len(pts) >= limit:
            break
    return pts


def _finite_reasonable(v: float) -> bool:
    if v != v or abs(v) > 50000:  # NaN or huge
        return False
    return abs(v) > 1e-6 or v == 0.0
