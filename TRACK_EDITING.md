# GT3 course files and track editing

This document describes the **course container**, the important **section types**, what the
game assumes about them, and how **export → edit → import / rebuild** works in GT3 Revisited.

Implementation references:

- Container / slots: `src/formats/course/course_file.*`, `docs/formats/course.md`
- Road surface: `src/formats/course/road.*`
- Scenery models: `src/formats/model/gtm1.*`
- Export (viewer): `src/formats/model/gltf_export.*`, Course viewer **R2**
- Import / pack: `src/formats/course/course_import.*`, `course_pack.*`
- CLI: `gt3tool course …`

---

## 1. What a “course file” is

On disc, each track is one file under something like:

```text
courses/US/trialmt
courses/EU/tahitidirt
```

In GT3.VOL many of these are **gzip-compressed**. After inflation you get a raw **48-slot
container**:

```text
[ 48 × u32 offsets ][ section bytes … ]
```

- Offset `0` = slot empty  
- Non-zero offset = start of that slot’s payload  
- Section size = distance to the next used offset (or EOF)

Every retail course uses the **same slot numbers** for the same kinds of data.

### Important slots

| Slot | Magic | Role |
|------|--------|------|
| 1 | `GTM1` | Main scenery (what you mostly see) |
| 2–4 | `Vls0` | Visibility lists for slot 1 (main / mirror / split) |
| 5 | `GTM1` | Reflection / secondary scenery |
| 6 | `Vls0` | Visibility for slot 5 |
| 21 | `GTM1` | Sky dome |
| 22 | `GTM1` | Distant backdrop |
| 23–24 | `GTM1` | Reflection / mirror sky helpers |
| 27 | `GTM1` | Licence course line (some `L_*` files) |
| **28** | **`GTRW`** | **Drivable road, walls, checkpoints, start grid** |
| 31 | — | AI driving lines |
| 32 | `Env0` | Fog / lights |
| 33 | `GTCM` | HUD minimap |
| 34 | `GTRC` | Replay cameras |
| 37–40 | — | AI driver parameter sets |

A full “track” for racing is **not** only a mesh: physics, AI, cameras, and culling all
depend on these sections staying consistent with each other.

---

## 2. Coordinate system

Shared by GTM1 scenery, GTRW road, checkpoints, AI:

- **Metres**
- **Y up**
- Same world space as the race simulation

glTF export from the Course viewer uses glTF conventions (**+Y up**, model facing **+Z**).
The engine’s glTF loader applies the same axis conventions used for car mods so round-trips
stay aligned when you use the built-in export/import path.

---

## 3. GTRW — road surface (slot 28)

**This is the driveline the physics uses**, not just decoration.

### Layout (offsets from `GTRW`)

Rough map (see `docs/formats/course.md` and `road.h` for full detail):

| Offset | Meaning |
|--------|---------|
| `0x00` | `"GTRW"` + size |
| `0x14` | Course id |
| `0x18` | Track length (m) |
| `0x20` | Markers |
| `0x28` | Start grid poses |
| `0x30` | **Segment count** + segment table offset |
| `0x38` | Wall points |
| `0x40` | Checkpoints |
| `0x48` | Spatial lookup grids (triangles / walls) |

### Segments

Each segment (~`0x40` bytes) owns:

- Vertex count / triangle count  
- Offset to vertices `{f32 x,y,z; u16,u16 attrs}` (16 bytes each)  
- Offset to triangles `{u16 a,b,c, …; material; flags}` (16 bytes each)  
- Neighbour segment ids, wall refs, bounds  

Triangles are **indexed into that segment’s vertices** (not a single global buffer).

### Why topology mattered for the first importer

The first import path only **patched floats in place** so:

- Section **byte size** stayed identical  
- Segment counts / grids / neighbours stayed valid  

If you change vertex or triangle counts in Blender, those tables must be **rebuilt**, not
patched. That is the **rebuild** path (below).

### What else hangs off GTRW

- **Checkpoints** — progress, lap line  
- **Walls** — collision ribbons  
- **Start grid** — race spawn poses  
- **Spatial grids** — fast “which triangle am I over?” queries  

A pure visual remesh that ignores these will look fine in a viewer and still break racing
until those structures are regenerated or copied carefully from a template.

---

## 4. GTM1 — scenery (slots 1, 5, 21, …)

Same family of format as **car bodies**:

- Header, **nodes**, **chunks**, **texture sets**  
- Chunks hold **VIF packets** (positions, UVs, strips, colours)  
- **Node programs** decide what draws from where  
- Optional **visibility lists** (`Vls0`) limit which nodes draw from a given viewpoint  

Editing scenery topology means encoding new packets and programs, not only saving an OBJ.
Position-only import can reshape an existing GTM1 when vertex counts match the decoded
export order.

Textures live in Tex1-style blocks inside/near GTM1; the Course viewer export embeds them
in the GLB as PNGs for Blender.

---

## 5. Other sections (short)

| Section | Editing notes |
|---------|----------------|
| **AI lines (31)** | Polylines the AI follows; edit as paths, not as render mesh |
| **Env0 (32)** | Fog, ambient, lamp types — mostly parameters |
| **GTCM (33)** | 2D map art for the HUD |
| **GTRC (34)** | Replay camera path |
| **Vls0** | Must stay consistent with GTM1 node indices if scenery nodes change |

---

## 6. Workflows in GT3 Revisited

### A. View / export (already in-engine)

1. Developer options → **Course viewer**  
2. Select course  
3. **R2** → `userdata/exports/courses/<name>.glb`  

That GLB is the decoded **render model** (mainly scenery at the current viewer options),
suitable for Blender inspection and surface edits.

### B. Position import (structure-preserving)

```text
gt3tool course import <original_course> <edited.glb> <out_course>
```

Or Course viewer **L2** (writes a mod override under `mods/course_import/files/…`).

**Select+L2** runs **rebuild-road** (new GTRW from GLB topology) into the same mod folder.

Rules:

- Prefer **same topology** as the export (same vertex counts)  
- Writes **positions only** into GTRW and/or GTM1  
- Output **raw size** matches the original container  

### C. Road rebuild from GLB (new GTRW data)

```text
gt3tool course rebuild-road <original_course> <road.glb> <out_course>
```

This **builds a new GTRW** from the GLB’s triangle mesh and drops it into slot 28 of a
copy of the original course (other slots kept). Section sizes may change; the container
offset table is rewritten.

**Current rebuild capabilities (initial implementation):**

- One or more meshes in the GLB → road vertices/triangles  
- Materials → GTRW material ids when name/index allows; else default surface  
- Copies course id / length / markers / grid / checkpoints / walls from the **template**
  GTRW when possible (so racing metadata survives)  
- Rebuilds a **minimal spatial grid** (or copies template grid only if triangle count matches)

**Not yet a full track compiler:** AI, cameras, and scenery are still taken from the template
course unless you replace those slots separately.

### D. Unpack / pack work folder

```text
gt3tool course extract <course> <out_dir>
gt3tool course pack    <work_dir> <out_course>
```

Useful for inspecting blobs (`blobs/slot_28_GTRW.bin`, etc.) and tooling outside the viewer.

---

## 7. Editing guidance (Blender)

### Safe for position import

- Export with R2  
- Move vertices; avoid dissolve / subdivide / remesh  
- Re-export GLB  
- Import with L2 or `course import`  

### Road rebuild

- Mesh should be the **driveable surface** (or a dedicated road export)  
- Triangles only (Blender: triangulate)  
- Reasonable scale (metres, same as game)  
- Optional: keep a copy of the original course as **template** for AI/checkpoints  

### Scenery

- Treat GTM1 as advanced: visual reshape with matching counts, or future full encode  
- Do not expect an arbitrary sculpt to replace slot 1 without a scenery encoder  

---

## 8. File types you’ll see on disk

| File | Meaning |
|------|---------|
| `courses/<region>/<name>` or `.gz` | Game course container |
| `exports/courses/<name>.glb` | Viewer export for editing |
| `mods/course_import/files/courses/...` | Imported override loaded through VFS |
| `work/manifest.json` | Unpack listing of slots |
| `work/structure_lock.json` | Original sizes (strict pack mode) |
| `work/road/GTRW.bin` | Extracted road section |
| `blender/road.gltf` | Tooling export of road mesh |

---

## 9. Design principles

1. **Never ship a course the game can’t parse** — validate container + `GTRW`/`GTM1` magics after write.  
2. **Template + replace** — start from a retail course; replace the sections you can encode.  
3. **Road first** — drivability is GTRW; scenery can lag.  
4. **Explicit modes** — “import positions” vs “rebuild road” so users know what changed.  

---

## 10. Roadmap

| Stage | Status |
|-------|--------|
| Container unpack/pack | Done |
| Viewer GLB export | Done |
| Position import (1:1) | Done |
| **GTRW rebuild from GLB** | **Done** (1 segment; template metadata kept) |
| Boundary walls from mesh | **Done** (optional) |
| Checkpoint sampling from mesh AABB | **Done** (optional flag) |
| Course viewer Sel+L2 rebuild | **Done** |
| Spatial lookup grid encode | **Done** (uniform cells in rebuild-road) |
| GTM1 scenery encode | **Partial**: position rewrite + experimental mesh sidecar |
| AI line edit tools | **Done** (JSON export/import, GLB polyline → line) |



## AI line tools

```bat
gt3tool course ai-export   course.gz  lines.json
gt3tool course ai-import   course.gz  lines.json  out.gz
gt3tool course ai-from-glb course.gz  path.glb    out.gz  0
```

JSON lists up to 7 lines with world-space points (`x,y,z`), `flags`, `radius`, `heading`, `segment`.
