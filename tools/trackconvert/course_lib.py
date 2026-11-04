#!/usr/bin/env python3
"""
GT3 course extract / pack library (shared by CLI and GUI).

Expanded:
  - Course container unpack/pack (48 slots)
  - GTRW: grid, checkpoints, markers, wall summary, material histogram
  - Slot 31 AI lines: extract + patch control points (same counts)
  - Top-down bounds helper for GUI map
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Any

SLOT_COUNT = 48
SLOT_ROAD = 28
SLOT_AI = 31

SLOT_HINTS = {
    1: "GTM1 scenery",
    5: "GTM1 scenery2",
    21: "GTM1 sky",
    22: "GTM1 backdrop",
    28: "GTRW road",
    31: "AI lines",
    32: "Env0",
    33: "GTCM map",
    34: "GTRC cameras",
}

FP = 4096.0  # AI fixed-point scale


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def s32(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def s16(data: bytes, off: int) -> int:
    return struct.unpack_from("<h", data, off)[0]


def f32(data: bytes, off: int) -> float:
    return struct.unpack_from("<f", data, off)[0]


def write_u32(buf: bytearray, off: int, value: int) -> None:
    struct.pack_into("<I", buf, off, value & 0xFFFFFFFF)


def write_s32(buf: bytearray, off: int, value: int) -> None:
    struct.pack_into("<i", buf, off, int(value))


def write_f32(buf: bytearray, off: int, value: float) -> None:
    struct.pack_into("<f", buf, off, float(value))


def looks_like_course(data: bytes) -> bool:
    if len(data) < SLOT_COUNT * 4 + 4:
        return False
    return u32(data, 0) == 0 and u32(data, 4) == SLOT_COUNT * 4


def parse_sections(data: bytes) -> list[dict[str, Any]]:
    if len(data) < SLOT_COUNT * 4:
        raise ValueError("file too small for course offset table")
    raw: list[tuple[int, int]] = []
    for i in range(SLOT_COUNT):
        off = u32(data, i * 4)
        if off:
            if off > len(data):
                raise ValueError(f"slot {i}: offset {off} past EOF")
            raw.append((i, off))
    raw.sort(key=lambda t: t[1])
    sections: list[dict[str, Any]] = []
    for idx, (slot, off) in enumerate(raw):
        end = raw[idx + 1][1] if idx + 1 < len(raw) else len(data)
        size = end - off
        tag = ""
        if size >= 4:
            magic = data[off : off + 4]
            if all(32 <= b < 127 for b in magic):
                tag = magic.decode("ascii")
        sections.append(
            {
                "slot": slot,
                "offset": off,
                "size": size,
                "tag": tag,
                "hint": SLOT_HINTS.get(slot, ""),
            }
        )
    return sections


def section_info_text(src: Path) -> str:
    data = src.read_bytes()
    lines = [
        f"file: {src} ({len(data)} bytes)",
        f"looks_like_course: {looks_like_course(data)}",
        "",
    ]
    for sec in parse_sections(data):
        lines.append(
            f"  slot {sec['slot']:2d}  off=0x{sec['offset']:08x}  size={sec['size']:8d}  "
            f"tag={sec['tag'] or '-':4s}  {sec['hint']}"
        )
    return "\n".join(lines)


# --- GTRW -----------------------------------------------------------------


def extract_gtrw_editable(gtrw: bytes, road_dir: Path) -> dict[str, Any]:
    if len(gtrw) < 0x60 or gtrw[0:4] != b"GTRW":
        return {"error": "not GTRW"}

    course_id = u32(gtrw, 0x14)
    length = f32(gtrw, 0x18)
    nmark = u16(gtrw, 0x22)
    mark_off = u32(gtrw, 0x24)
    ngrid = u32(gtrw, 0x28)
    grid_off = u32(gtrw, 0x2C)
    nseg = u32(gtrw, 0x30)
    seg_off = u32(gtrw, 0x34)
    nwall = u32(gtrw, 0x38)
    wall_off = u32(gtrw, 0x3C)
    ncp = u32(gtrw, 0x40)
    cp_off = u32(gtrw, 0x44)

    grid = []
    for i in range(ngrid):
        o = grid_off + i * 16
        if o + 16 > len(gtrw):
            break
        grid.append(
            {
                "index": i,
                "x": f32(gtrw, o),
                "y": f32(gtrw, o + 4),
                "z": f32(gtrw, o + 8),
                "yaw": f32(gtrw, o + 12),
            }
        )

    checkpoints = []
    for i in range(ncp):
        o = cp_off + i * 32
        if o + 32 > len(gtrw):
            break
        checkpoints.append(
            {
                "index": i,
                "x0": f32(gtrw, o),
                "z0": f32(gtrw, o + 4),
                "x1": f32(gtrw, o + 8),
                "z1": f32(gtrw, o + 12),
                "distance": f32(gtrw, o + 16),
                "dir_x": f32(gtrw, o + 20),
                "dir_z": f32(gtrw, o + 24),
                "unknown": f32(gtrw, o + 28),
            }
        )

    markers = []
    for i in range(nmark):
        o = mark_off + i * 8
        if o + 8 > len(gtrw):
            break
        markers.append({"index": i, "flags": u32(gtrw, o), "distance": f32(gtrw, o + 4)})

    walls = []
    for i in range(min(nwall, 50000)):
        o = wall_off + i * 16
        if o + 16 > len(gtrw):
            break
        walls.append(
            {
                "index": i,
                "x": f32(gtrw, o),
                "y": f32(gtrw, o + 4),
                "z": f32(gtrw, o + 8),
                "tag": u32(gtrw, o + 12),
            }
        )

    # Material histogram from segment triangles (read-only)
    materials: dict[int, int] = {}
    tri_total = 0
    for i in range(nseg):
        s = seg_off + i * 0x40
        if s + 0x40 > len(gtrw):
            break
        nv = u16(gtrw, s)
        nt = u16(gtrw, s + 2)
        toff = u32(gtrw, s + 8)
        for t in range(nt):
            tp = toff + t * 16
            if tp + 16 > len(gtrw):
                break
            mat = u16(gtrw, tp + 8)
            materials[mat] = materials.get(mat, 0) + 1
            tri_total += 1

    (road_dir / "grid.json").write_text(json.dumps(grid, indent=2) + "\n", encoding="utf-8")
    (road_dir / "checkpoints.json").write_text(
        json.dumps(checkpoints, indent=2) + "\n", encoding="utf-8"
    )
    (road_dir / "markers.json").write_text(json.dumps(markers, indent=2) + "\n", encoding="utf-8")
    # Walls can be large — write compact
    (road_dir / "walls.json").write_text(json.dumps(walls) + "\n", encoding="utf-8")
    (road_dir / "GTRW.bin").write_bytes(gtrw)

    mat_list = [{"material": k, "triangles": v} for k, v in sorted(materials.items())]
    (road_dir / "materials.json").write_text(json.dumps(mat_list, indent=2) + "\n", encoding="utf-8")

    summary = {
        "course_id": course_id,
        "length": length,
        "segments": nseg,
        "triangles": tri_total,
        "wall_points": len(walls),
        "grid_count": len(grid),
        "checkpoint_count": len(checkpoints),
        "marker_count": len(markers),
        "materials": mat_list,
        "grid_file": "road/grid.json",
        "checkpoints_file": "road/checkpoints.json",
        "markers_file": "road/markers.json",
        "walls_file": "road/walls.json",
        "binary": "road/GTRW.bin",
        "note": "Edit grid/checkpoints/markers then Patch GTRW (counts must match).",
    }
    (road_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def patch_gtrw_from_json(editable_dir: Path) -> str:
    road_dir = editable_dir / "road"
    gtrw_path = road_dir / "GTRW.bin"
    if not gtrw_path.is_file():
        raise FileNotFoundError(f"missing {gtrw_path} — unpack a course first")

    gtrw = bytearray(gtrw_path.read_bytes())
    if gtrw[0:4] != b"GTRW":
        raise ValueError("GTRW.bin is not a GTRW section")

    nmark = u16(gtrw, 0x22)
    mark_off = u32(gtrw, 0x24)
    ngrid = u32(gtrw, 0x28)
    grid_off = u32(gtrw, 0x2C)
    ncp = u32(gtrw, 0x40)
    cp_off = u32(gtrw, 0x44)

    grid = json.loads((road_dir / "grid.json").read_text(encoding="utf-8"))
    cps = json.loads((road_dir / "checkpoints.json").read_text(encoding="utf-8"))
    markers_path = road_dir / "markers.json"
    markers = json.loads(markers_path.read_text(encoding="utf-8")) if markers_path.is_file() else []

    if len(grid) != ngrid:
        raise ValueError(f"grid count mismatch: json={len(grid)} binary={ngrid}")
    if len(cps) != ncp:
        raise ValueError(f"checkpoint count mismatch: json={len(cps)} binary={ncp}")
    if markers and len(markers) != nmark:
        raise ValueError(f"marker count mismatch: json={len(markers)} binary={nmark}")

    for i, g in enumerate(grid):
        o = grid_off + i * 16
        write_f32(gtrw, o, g["x"])
        write_f32(gtrw, o + 4, g["y"])
        write_f32(gtrw, o + 8, g["z"])
        write_f32(gtrw, o + 12, g["yaw"])

    for i, c in enumerate(cps):
        o = cp_off + i * 32
        write_f32(gtrw, o, c["x0"])
        write_f32(gtrw, o + 4, c["z0"])
        write_f32(gtrw, o + 8, c["x1"])
        write_f32(gtrw, o + 12, c["z1"])
        write_f32(gtrw, o + 16, c["distance"])
        write_f32(gtrw, o + 20, c["dir_x"])
        write_f32(gtrw, o + 24, c["dir_z"])
        write_f32(gtrw, o + 28, c["unknown"])

    for i, m in enumerate(markers):
        o = mark_off + i * 8
        write_u32(gtrw, o, int(m.get("flags", 0)))
        write_f32(gtrw, o + 4, float(m.get("distance", 0)))

    gtrw_path.write_bytes(gtrw)

    messages = [
        f"patched grid ({ngrid}) + checkpoints ({ncp}) + markers ({len(markers)}) -> {gtrw_path}"
    ]
    manifest_path = editable_dir / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for slot in manifest.get("slots", []):
            if slot.get("slot") == SLOT_ROAD:
                blob = editable_dir / slot["blob"]
                blob.write_bytes(gtrw)
                messages.append(f"updated {blob}")
                break
    return "\n".join(messages)


# --- AI lines (slot 31) ---------------------------------------------------


def extract_ai_lines(ai: bytes, ai_dir: Path) -> dict[str, Any]:
    if len(ai) < 0x48:
        return {"error": "AI section too small"}
    size = u32(ai, 0)
    if u32(ai, 4) != 8 or size > len(ai):
        return {"error": "bad AI header"}

    build = ""
    for i in range(0x28, 0x48):
        if ai[i] >= 0x20:
            build += chr(ai[i])
        else:
            break

    lines_out = []
    for li in range(7):
        off = u32(ai, 0x0C + 4 * li)
        points = []
        if off and off + 4 <= size:
            n = u32(ai, off)
            for k in range(n):
                p = off + 4 + k * 40
                if p + 40 > size:
                    break
                flags = u32(ai, p)
                raw_x = s32(ai, p + 4)
                raw_z = s32(ai, p + 8)
                segment = u32(ai, p + 16)
                raw_radius = s32(ai, p + 24)
                packed = u32(ai, p + 36)
                # world: x mirrored
                wx = -raw_x / FP
                wz = raw_z / FP
                heading = -float(s16_from_u16(packed & 0xFFFF)) * (2 * math.pi / FP)
                points.append(
                    {
                        "index": k,
                        "x": wx,
                        "z": wz,
                        "flags": flags,
                        "segment": segment,
                        "radius_m": (raw_radius / FP) if (flags & 1) else 0.0,
                        "heading": heading,
                        "raw_x": raw_x,
                        "raw_z": raw_z,
                        "raw_radius": raw_radius,
                        "packed": packed,
                    }
                )
        closed = False
        if len(points) >= 4:
            dx = points[0]["x"] - points[-1]["x"]
            dz = points[0]["z"] - points[-1]["z"]
            closed = math.hypot(dx, dz) < 250.0
        lines_out.append({"line": li, "closed": closed, "count": len(points), "points": points})

    (ai_dir / "AI.bin").write_bytes(ai)
    (ai_dir / "lines.json").write_text(json.dumps(lines_out, indent=2) + "\n", encoding="utf-8")
    summary = {
        "build": build.strip(),
        "lines": [{"line": L["line"], "count": L["count"], "closed": L["closed"]} for L in lines_out],
        "binary": "ai/AI.bin",
        "json": "ai/lines.json",
    }
    (ai_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def s16_from_u16(v: int) -> int:
    v &= 0xFFFF
    return v - 0x10000 if v >= 0x8000 else v


def patch_ai_from_json(editable_dir: Path) -> str:
    ai_dir = editable_dir / "ai"
    ai_path = ai_dir / "AI.bin"
    if not ai_path.is_file():
        raise FileNotFoundError(f"missing {ai_path}")

    ai = bytearray(ai_path.read_bytes())
    size = u32(ai, 0)
    lines = json.loads((ai_dir / "lines.json").read_text(encoding="utf-8"))

    for L in lines:
        li = int(L["line"])
        off = u32(ai, 0x0C + 4 * li)
        if not off:
            continue
        n = u32(ai, off)
        pts = L.get("points", [])
        if len(pts) != n:
            raise ValueError(f"AI line {li}: count mismatch json={len(pts)} binary={n}")
        for k, pt in enumerate(pts):
            p = off + 4 + k * 40
            # Prefer raw_* if present; else convert from world x/z
            if "raw_x" in pt and "raw_z" in pt:
                raw_x = int(pt["raw_x"])
                raw_z = int(pt["raw_z"])
            else:
                raw_x = int(round(-float(pt["x"]) * FP))
                raw_z = int(round(float(pt["z"]) * FP))
            flags = int(pt.get("flags", 0))
            if "raw_radius" in pt:
                raw_radius = int(pt["raw_radius"])
            else:
                raw_radius = int(round(float(pt.get("radius_m", 0)) * FP)) if (flags & 1) else 0
            packed = int(pt.get("packed", 0))
            if "heading" in pt and "packed" not in pt:
                # world heading -> sim packed low 16
                h = -float(pt["heading"]) * FP / (2 * math.pi)
                packed = (packed & 0xFFFF0000) | (int(round(h)) & 0xFFFF)
            write_u32(ai, p, flags)
            write_s32(ai, p + 4, raw_x)
            write_s32(ai, p + 8, raw_z)
            write_u32(ai, p + 16, int(pt.get("segment", 0)))
            write_s32(ai, p + 24, raw_radius)
            write_u32(ai, p + 36, packed)

    ai_path.write_bytes(ai)

    messages = [f"patched AI lines -> {ai_path}"]
    manifest_path = editable_dir / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for slot in manifest.get("slots", []):
            if slot.get("slot") == SLOT_AI:
                blob = editable_dir / slot["blob"]
                blob.write_bytes(ai)
                messages.append(f"updated {blob}")
                break
    return "\n".join(messages)


# --- unpack / pack --------------------------------------------------------


def unpack_course(src: Path, dst: Path) -> str:
    data = src.read_bytes()
    warnings: list[str] = []
    if not looks_like_course(data):
        warnings.append("warning: file does not look like a GT3 course (continuing)")

    sections = parse_sections(data)
    dst.mkdir(parents=True, exist_ok=True)
    blobs = dst / "blobs"
    blobs.mkdir(exist_ok=True)

    manifest: dict[str, Any] = {
        "source": str(src),
        "size": len(data),
        "format": "gt3-course-v2",
        "slots": [],
    }

    for sec in sections:
        slot = sec["slot"]
        blob_name = f"slot_{slot:02d}{('_' + sec['tag']) if sec['tag'] else ''}.bin"
        blob_path = blobs / blob_name
        chunk = data[sec["offset"] : sec["offset"] + sec["size"]]
        blob_path.write_bytes(chunk)
        entry: dict[str, Any] = {
            "slot": slot,
            "tag": sec["tag"],
            "hint": sec["hint"],
            "blob": f"blobs/{blob_name}",
            "size": sec["size"],
        }
        manifest["slots"].append(entry)

        if slot == SLOT_ROAD and sec["tag"] == "GTRW":
            road_dir = dst / "road"
            road_dir.mkdir(exist_ok=True)
            entry["gtrw"] = extract_gtrw_editable(chunk, road_dir)
        elif slot == SLOT_AI:
            ai_dir = dst / "ai"
            ai_dir.mkdir(exist_ok=True)
            entry["ai"] = extract_ai_lines(chunk, ai_dir)

    (dst / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    msg = f"unpacked {len(sections)} sections -> {dst}"
    if warnings:
        return "\n".join(warnings) + "\n" + msg
    return msg


def pack_course(editable_dir: Path, out_path: Path) -> str:
    manifest_path = editable_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"missing {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    slots = sorted(manifest["slots"], key=lambda s: s["slot"])
    gtrw_bin = editable_dir / "road" / "GTRW.bin"
    ai_bin = editable_dir / "ai" / "AI.bin"

    table = bytearray(SLOT_COUNT * 4)
    body = bytearray()
    cursor = SLOT_COUNT * 4

    payloads: dict[int, bytes] = {}
    for entry in slots:
        slot = int(entry["slot"])
        blob_path = editable_dir / entry["blob"]
        if slot == SLOT_ROAD and gtrw_bin.is_file():
            payloads[slot] = gtrw_bin.read_bytes()
        elif slot == SLOT_AI and ai_bin.is_file():
            payloads[slot] = ai_bin.read_bytes()
        else:
            if not blob_path.is_file():
                raise FileNotFoundError(f"missing blob {blob_path}")
            payloads[slot] = blob_path.read_bytes()

    for slot in sorted(payloads.keys()):
        write_u32(table, slot * 4, cursor)
        body.extend(payloads[slot])
        cursor += len(payloads[slot])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(bytes(table) + bytes(body))
    return f"packed {len(payloads)} sections -> {out_path} ({out_path.stat().st_size} bytes)"


# --- JSON helpers / map bounds --------------------------------------------


def load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save_json_list(path: Path, rows: list[dict[str, Any]], indent: int | None = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=indent) + "\n", encoding="utf-8")


def load_grid(editable_dir: Path) -> list[dict[str, Any]]:
    return load_json_list(editable_dir / "road" / "grid.json")


def save_grid(editable_dir: Path, grid: list[dict[str, Any]]) -> None:
    save_json_list(editable_dir / "road" / "grid.json", grid)


def load_checkpoints(editable_dir: Path) -> list[dict[str, Any]]:
    return load_json_list(editable_dir / "road" / "checkpoints.json")


def save_checkpoints(editable_dir: Path, cps: list[dict[str, Any]]) -> None:
    save_json_list(editable_dir / "road" / "checkpoints.json", cps)


def load_markers(editable_dir: Path) -> list[dict[str, Any]]:
    return load_json_list(editable_dir / "road" / "markers.json")


def save_markers(editable_dir: Path, rows: list[dict[str, Any]]) -> None:
    save_json_list(editable_dir / "road" / "markers.json", rows)


def load_ai_lines(editable_dir: Path) -> list[dict[str, Any]]:
    return load_json_list(editable_dir / "ai" / "lines.json")


def save_ai_lines(editable_dir: Path, lines: list[dict[str, Any]]) -> None:
    save_json_list(editable_dir / "ai" / "lines.json", lines)


def map_bounds(editable_dir: Path) -> tuple[float, float, float, float] | None:
    """Return (min_x, min_z, max_x, max_z) from grid, checkpoints, AI line 0."""
    xs: list[float] = []
    zs: list[float] = []
    for g in load_grid(editable_dir):
        xs.append(float(g["x"]))
        zs.append(float(g["z"]))
    for c in load_checkpoints(editable_dir):
        xs.extend([float(c["x0"]), float(c["x1"])])
        zs.extend([float(c["z0"]), float(c["z1"])])
    lines = load_ai_lines(editable_dir)
    if lines and lines[0].get("points"):
        for p in lines[0]["points"]:
            xs.append(float(p["x"]))
            zs.append(float(p["z"]))
    walls_path = editable_dir / "road" / "walls.json"
    if walls_path.is_file():
        # sample walls for bounds (can be huge)
        walls = json.loads(walls_path.read_text(encoding="utf-8"))
        step = max(1, len(walls) // 2000)
        for w in walls[::step]:
            xs.append(float(w["x"]))
            zs.append(float(w["z"]))
    if not xs:
        return None
    pad = 20.0
    return min(xs) - pad, min(zs) - pad, max(xs) + pad, max(zs) + pad


def zip_work_folder(editable_dir: Path, zip_path: Path) -> str:
    """Zip an unpacked work folder for sharing / backup."""
    import zipfile
    editable_dir = Path(editable_dir)
    zip_path = Path(zip_path)
    if not (editable_dir / "manifest.json").is_file():
        raise FileNotFoundError("not a work folder (missing manifest.json)")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in editable_dir.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(editable_dir).as_posix())
    return f"zipped {editable_dir} -> {zip_path} ({zip_path.stat().st_size} bytes)"


def unzip_work_folder(zip_path: Path, dest: Path) -> str:
    import zipfile
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest)
    if not (dest / "manifest.json").is_file():
        # maybe single top-level folder inside zip
        subs = [p for p in dest.iterdir() if p.is_dir()]
        if len(subs) == 1 and (subs[0] / "manifest.json").is_file():
            return f"unzipped -> {subs[0]}"
        raise ValueError("zip does not look like a course work folder")
    return f"unzipped -> {dest}"


def main_cli(argv: list[str] | None = None) -> None:
    import argparse

    ap = argparse.ArgumentParser(description="GT3 course unpack/pack tool")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_info = sub.add_parser("info", help="list course sections")
    p_info.add_argument("course")

    p_un = sub.add_parser("unpack", help="course file -> editable directory")
    p_un.add_argument("course")
    p_un.add_argument("outdir")

    p_pack = sub.add_parser("pack", help="editable directory -> course file")
    p_pack.add_argument("indir")
    p_pack.add_argument("course_out")

    p_patch = sub.add_parser("patch-gtrw", help="apply grid/checkpoints/markers into GTRW.bin")
    p_patch.add_argument("indir")

    p_ai = sub.add_parser("patch-ai", help="apply ai/lines.json into AI.bin")
    p_ai.add_argument("indir")

    p_bl = sub.add_parser("export-blender", help="export road mesh + AI + grid for Blender")
    p_bl.add_argument("indir")
    p_bl.add_argument("outdir")
    p_bl.add_argument("--y-up", action="store_true", help="keep GT3 Y-up (default Z-up)")

    p_obj = sub.add_parser("import-obj", help="write OBJ vertex positions into GTRW (same count)")
    p_obj.add_argument("indir")
    p_obj.add_argument("obj")
    p_obj.add_argument("--y-up", action="store_true", help="OBJ is Y-up (default assumes Z-up Blender export)")

    p_sc = sub.add_parser("export-scenery", help="export GTM1/scenery slots + heuristic point clouds")
    p_sc.add_argument("indir")
    p_sc.add_argument("outdir")

    p_zip = sub.add_parser("zip-work", help="zip an unpacked work folder")
    p_zip.add_argument("indir")
    p_zip.add_argument("zipfile")

    args = ap.parse_args(argv)
    if args.cmd == "info":
        print(section_info_text(Path(args.course)))
    elif args.cmd == "unpack":
        print(unpack_course(Path(args.course), Path(args.outdir)))
    elif args.cmd == "pack":
        print(pack_course(Path(args.indir), Path(args.course_out)))
    elif args.cmd == "patch-gtrw":
        print(patch_gtrw_from_json(Path(args.indir)))
    elif args.cmd == "patch-ai":
        print(patch_ai_from_json(Path(args.indir)))
    elif args.cmd == "export-blender":
        from blender_export import export_for_blender
        print(export_for_blender(Path(args.indir), Path(args.outdir), z_up=not args.y_up))
    elif args.cmd == "import-obj":
        from mesh_io import import_obj_into_gtrw
        print(import_obj_into_gtrw(Path(args.indir), Path(args.obj), from_z_up=not args.y_up))
    elif args.cmd == "export-scenery":
        from mesh_io import export_gtm1_scenery
        print(export_gtm1_scenery(Path(args.indir), Path(args.outdir), z_up=True))
    elif args.cmd == "zip-work":
        print(zip_work_folder(Path(args.indir), Path(args.zipfile)))


if __name__ == "__main__":
    main_cli()
