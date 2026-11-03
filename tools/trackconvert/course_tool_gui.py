#!/usr/bin/env python3
"""
GT3 Course Tool GUI — unpack / map preview / edit grid, checkpoints, markers, AI / pack.

  python course_tool_gui.py

PyInstaller:
  pyinstaller --noconfirm --windowed --onefile --name GT3CourseTool --paths . course_tool_gui.py
"""

from __future__ import annotations

import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

if getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(sys.executable).resolve().parent))
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import course_lib as lib  # noqa: E402

APP_TITLE = "GT3 Course Tool"
APP_GEOM = "1100x720"


class CourseToolApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry(APP_GEOM)
        self.minsize(800, 560)

        self.course_path = tk.StringVar()
        self.work_dir = tk.StringVar()
        self.out_path = tk.StringVar()
        self.status = tk.StringVar(value="Open a course file or work folder.")
        self.ai_line_sel = tk.IntVar(value=0)
        self.map_show = {
            "grid": tk.BooleanVar(value=True),
            "checkpoints": tk.BooleanVar(value=True),
            "ai": tk.BooleanVar(value=True),
            "walls": tk.BooleanVar(value=False),
        }

        self._grid_rows: list[dict] = []
        self._cp_rows: list[dict] = []
        self._marker_rows: list[dict] = []
        self._ai_lines: list[dict] = []
        self._walls: list[dict] = []

        self._build_ui()

    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}

        frm = ttk.LabelFrame(self, text="Paths")
        frm.pack(fill="x", **pad)
        self._row_path(frm, 0, "Course file", self.course_path, self._browse_course)
        self._row_path(frm, 1, "Work folder", self.work_dir, self._browse_work)
        self._row_path(frm, 2, "Output course", self.out_path, self._browse_out)

        act = ttk.Frame(self)
        act.pack(fill="x", **pad)
        for text, cmd in (
            ("Info", self._on_info),
            ("Unpack", self._on_unpack),
            ("Reload", self._on_reload),
            ("Save JSON", self._on_save_json),
            ("Patch GTRW", self._on_patch_gtrw),
            ("Patch AI", self._on_patch_ai),
            ("Pack course", self._on_pack),
            ("Export Blender", self._on_export_blender),
            ("Redraw map", self._redraw_map),
        ):
            ttk.Button(act, text=text, command=cmd).pack(side="left", padx=2)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, **pad)

        self.map_frame = ttk.Frame(nb)
        self.grid_frame = ttk.Frame(nb)
        self.cp_frame = ttk.Frame(nb)
        self.marker_frame = ttk.Frame(nb)
        self.ai_frame = ttk.Frame(nb)
        self.mat_frame = ttk.Frame(nb)
        self.log_frame = ttk.Frame(nb)

        nb.add(self.map_frame, text="Map")
        nb.add(self.grid_frame, text="Start grid")
        nb.add(self.cp_frame, text="Checkpoints")
        nb.add(self.marker_frame, text="Markers")
        nb.add(self.ai_frame, text="AI lines")
        nb.add(self.mat_frame, text="Materials")
        nb.add(self.log_frame, text="Log")

        # Map
        map_tools = ttk.Frame(self.map_frame)
        map_tools.pack(fill="x", padx=6, pady=2)
        for key, label in (
            ("grid", "Grid"),
            ("checkpoints", "Checkpoints"),
            ("ai", "AI line"),
            ("walls", "Walls (sampled)"),
        ):
            ttk.Checkbutton(
                map_tools, text=label, variable=self.map_show[key], command=self._redraw_map
            ).pack(side="left", padx=4)
        ttk.Label(map_tools, text="AI#").pack(side="left", padx=(12, 2))
        ttk.Spinbox(
            map_tools, from_=0, to=6, width=4, textvariable=self.ai_line_sel, command=self._redraw_map
        ).pack(side="left")

        self.canvas = tk.Canvas(self.map_frame, bg="#1a1d23", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=6, pady=4)
        self.canvas.bind("<Configure>", lambda _e: self._redraw_map())

        # Grid table
        self.grid_tree = self._make_tree(
            self.grid_frame,
            ("index", "x", "y", "z", "yaw"),
            ("Index", "X", "Y", "Z", "Yaw"),
        )
        self.grid_tree.bind("<<TreeviewSelect>>", self._on_grid_select)
        self.g_vars = {k: tk.StringVar() for k in ("x", "y", "z", "yaw")}
        self._edit_bar(self.grid_frame, self.g_vars, self._apply_grid, [("x", "X"), ("y", "Y"), ("z", "Z"), ("yaw", "Yaw")])

        # Checkpoints
        self.cp_tree = self._make_tree(
            self.cp_frame,
            ("index", "x0", "z0", "x1", "z1", "distance"),
            ("Index", "X0", "Z0", "X1", "Z1", "Dist"),
        )
        self.cp_tree.bind("<<TreeviewSelect>>", self._on_cp_select)
        self.c_vars = {
            k: tk.StringVar()
            for k in ("x0", "z0", "x1", "z1", "distance", "dir_x", "dir_z", "unknown")
        }
        self._edit_bar(
            self.cp_frame,
            self.c_vars,
            self._apply_cp,
            [
                ("x0", "X0"),
                ("z0", "Z0"),
                ("x1", "X1"),
                ("z1", "Z1"),
                ("distance", "Dist"),
                ("dir_x", "DirX"),
                ("dir_z", "DirZ"),
                ("unknown", "Unk"),
            ],
        )

        # Markers
        self.marker_tree = self._make_tree(
            self.marker_frame, ("index", "flags", "distance"), ("Index", "Flags", "Distance")
        )
        self.marker_tree.bind("<<TreeviewSelect>>", self._on_marker_select)
        self.m_vars = {k: tk.StringVar() for k in ("flags", "distance")}
        self._edit_bar(
            self.marker_frame,
            self.m_vars,
            self._apply_marker,
            [("flags", "Flags"), ("distance", "Distance")],
        )

        # AI
        ai_top = ttk.Frame(self.ai_frame)
        ai_top.pack(fill="x", padx=6, pady=4)
        ttk.Label(ai_top, text="Line").pack(side="left")
        self.ai_combo = ttk.Combobox(ai_top, values=[str(i) for i in range(7)], width=4, state="readonly")
        self.ai_combo.set("0")
        self.ai_combo.pack(side="left", padx=4)
        self.ai_combo.bind("<<ComboboxSelected>>", lambda _e: self._fill_ai_tree())
        self.ai_info = tk.StringVar(value="")
        ttk.Label(ai_top, textvariable=self.ai_info).pack(side="left", padx=8)

        self.ai_tree = self._make_tree(
            self.ai_frame,
            ("index", "x", "z", "flags", "segment", "radius_m", "heading"),
            ("Index", "X", "Z", "Flags", "Seg", "Radius", "Heading"),
        )
        self.ai_tree.bind("<<TreeviewSelect>>", self._on_ai_select)
        self.a_vars = {k: tk.StringVar() for k in ("x", "z", "flags", "segment", "radius_m", "heading")}
        self._edit_bar(
            self.ai_frame,
            self.a_vars,
            self._apply_ai,
            [
                ("x", "X"),
                ("z", "Z"),
                ("flags", "Flags"),
                ("segment", "Seg"),
                ("radius_m", "Radius"),
                ("heading", "Heading"),
            ],
        )

        # Materials
        self.mat_tree = self._make_tree(
            self.mat_frame, ("material", "triangles"), ("Material", "Triangles")
        )
        ttk.Label(
            self.mat_frame,
            text="Read-only histogram from GTRW triangles (0=tarmac, others kerb/dirt/…).",
        ).pack(anchor="w", padx=8, pady=4)

        # Log
        self.log = tk.Text(self.log_frame, height=12, wrap="word")
        self.log.pack(fill="both", expand=True, padx=6, pady=6)

        ttk.Label(self, textvariable=self.status, anchor="w").pack(fill="x", padx=8, pady=4)

        menubar = tk.Menu(self)
        file_m = tk.Menu(menubar, tearoff=0)
        file_m.add_command(label="Open course…", command=self._browse_course)
        file_m.add_command(label="Open work folder…", command=self._browse_work)
        file_m.add_separator()
        file_m.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=file_m)
        help_m = tk.Menu(menubar, tearoff=0)
        help_m.add_command(label="About", command=self._about)
        menubar.add_cascade(label="Help", menu=help_m)
        self.config(menu=menubar)

    def _row_path(self, parent, row, label, var, browse_cmd):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=2)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", padx=4, pady=2)
        ttk.Button(parent, text="Browse…", command=browse_cmd).grid(row=row, column=2, padx=6, pady=2)
        parent.columnconfigure(1, weight=1)

    def _make_tree(self, parent, columns, headings):
        wrap = ttk.Frame(parent)
        wrap.pack(fill="both", expand=True, padx=6, pady=4)
        tree = ttk.Treeview(wrap, columns=columns, show="headings", height=14)
        for col, head in zip(columns, headings):
            tree.heading(col, text=head)
            tree.column(col, width=88 if col != "index" else 48, anchor="center")
        ys = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=ys.set)
        tree.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        return tree

    def _edit_bar(self, parent, vars_map, apply_cmd, labels):
        bar = ttk.LabelFrame(parent, text="Edit selected")
        bar.pack(fill="x", padx=6, pady=4)
        for i, (k, lab) in enumerate(labels):
            ttk.Label(bar, text=lab).grid(row=0, column=i * 2, sticky="e", padx=2)
            ttk.Entry(bar, textvariable=vars_map[k], width=11).grid(
                row=0, column=i * 2 + 1, padx=2, pady=2
            )
        ttk.Button(bar, text="Apply to row", command=apply_cmd).grid(
            row=0, column=len(labels) * 2, padx=8
        )

    # Paths
    def _browse_course(self) -> None:
        p = filedialog.askopenfilename(title="Course file")
        if p:
            self.course_path.set(p)
            src = Path(p)
            if not self.work_dir.get():
                self.work_dir.set(str(src.parent / f"{src.name}_edit"))
            if not self.out_path.get():
                self.out_path.set(str(src.parent / f"{src.name}_mod"))

    def _browse_work(self) -> None:
        p = filedialog.askdirectory(title="Work folder")
        if p:
            self.work_dir.set(p)
            self._on_reload()

    def _browse_out(self) -> None:
        p = filedialog.asksaveasfilename(title="Output course")
        if p:
            self.out_path.set(p)

    def _log(self, msg: str) -> None:
        self.log.insert("end", msg.rstrip() + "\n")
        self.log.see("end")
        self.status.set(msg.splitlines()[-1][:140])

    def _err(self, title: str, exc: BaseException) -> None:
        self._log(f"ERROR: {exc}")
        messagebox.showerror(title, str(exc))

    # Actions
    def _on_info(self) -> None:
        p = Path(self.course_path.get().strip())
        if not p.is_file():
            messagebox.showwarning(APP_TITLE, "Choose a course file.")
            return
        try:
            self._log(lib.section_info_text(p))
        except Exception as e:
            self._err("Info failed", e)

    def _on_unpack(self) -> None:
        src = Path(self.course_path.get().strip())
        dst = Path(self.work_dir.get().strip())
        if not src.is_file():
            messagebox.showwarning(APP_TITLE, "Choose a course file.")
            return
        try:
            msg = lib.unpack_course(src, dst)
            self._log(msg)
            self._on_reload()
            messagebox.showinfo(APP_TITLE, msg)
        except Exception as e:
            self._err("Unpack failed", e)

    def _on_reload(self) -> None:
        wd = Path(self.work_dir.get().strip())
        if not wd.is_dir():
            return
        try:
            self._grid_rows = lib.load_grid(wd)
            self._cp_rows = lib.load_checkpoints(wd)
            self._marker_rows = lib.load_markers(wd)
            self._ai_lines = lib.load_ai_lines(wd)
            walls_path = wd / "road" / "walls.json"
            self._walls = (
                json.loads(walls_path.read_text(encoding="utf-8")) if walls_path.is_file() else []
            )
            self._fill_grid_tree()
            self._fill_cp_tree()
            self._fill_marker_tree()
            self._fill_ai_tree()
            self._fill_mat_tree()
            self._redraw_map()
            self._log(
                f"reloaded grid={len(self._grid_rows)} cp={len(self._cp_rows)} "
                f"markers={len(self._marker_rows)} ai_lines={len(self._ai_lines)} walls={len(self._walls)}"
            )
        except Exception as e:
            self._err("Reload failed", e)

    def _on_save_json(self) -> None:
        wd = Path(self.work_dir.get().strip())
        try:
            lib.save_grid(wd, self._grid_rows)
            lib.save_checkpoints(wd, self._cp_rows)
            lib.save_markers(wd, self._marker_rows)
            lib.save_ai_lines(wd, self._ai_lines)
            self._log("saved grid/checkpoints/markers/ai JSON")
        except Exception as e:
            self._err("Save failed", e)

    def _on_patch_gtrw(self) -> None:
        wd = Path(self.work_dir.get().strip())
        try:
            lib.save_grid(wd, self._grid_rows)
            lib.save_checkpoints(wd, self._cp_rows)
            lib.save_markers(wd, self._marker_rows)
            msg = lib.patch_gtrw_from_json(wd)
            self._log(msg)
            messagebox.showinfo(APP_TITLE, msg)
        except Exception as e:
            self._err("Patch GTRW failed", e)

    def _on_patch_ai(self) -> None:
        wd = Path(self.work_dir.get().strip())
        try:
            lib.save_ai_lines(wd, self._ai_lines)
            msg = lib.patch_ai_from_json(wd)
            self._log(msg)
            messagebox.showinfo(APP_TITLE, msg)
        except Exception as e:
            self._err("Patch AI failed", e)

    def _on_pack(self) -> None:
        wd = Path(self.work_dir.get().strip())
        out = Path(self.out_path.get().strip())
        try:
            lib.save_grid(wd, self._grid_rows)
            lib.save_checkpoints(wd, self._cp_rows)
            lib.save_markers(wd, self._marker_rows)
            lib.save_ai_lines(wd, self._ai_lines)
            if (wd / "road" / "GTRW.bin").is_file():
                lib.patch_gtrw_from_json(wd)
            if (wd / "ai" / "AI.bin").is_file():
                lib.patch_ai_from_json(wd)
            msg = lib.pack_course(wd, out)
            self._log(msg)
            messagebox.showinfo(APP_TITLE, msg)
        except Exception as e:
            self._err("Pack failed", e)

    def _on_export_blender(self) -> None:
        wd = Path(self.work_dir.get().strip())
        if not wd.is_dir():
            messagebox.showwarning(APP_TITLE, "Unpack a course first.")
            return
        out = filedialog.askdirectory(title="Blender export folder")
        if not out:
            return
        try:
            from blender_export import export_for_blender

            msg = export_for_blender(wd, Path(out), z_up=True)
            self._log(msg)
            messagebox.showinfo(APP_TITLE, msg)
        except Exception as e:
            self._err("Blender export failed", e)

    def _about(self) -> None:
        messagebox.showinfo(
            APP_TITLE,
            "GT3 Course Tool\n\n"
            "Unpack courses, preview map, edit start grid, checkpoints,\n"
            "markers and AI control points, then pack for GT3-revisited.\n\n"
            "Counts cannot change (in-place patch). Scenery is copy-through.\n"
            "Export Blender writes road.obj for editing in Blender.",
        )

    # Tables
    def _fill_grid_tree(self) -> None:
        t = self.grid_tree
        t.delete(*t.get_children())
        for g in self._grid_rows:
            t.insert(
                "",
                "end",
                iid=str(g["index"]),
                values=(g["index"], f"{g['x']:.4f}", f"{g['y']:.4f}", f"{g['z']:.4f}", f"{g['yaw']:.5f}"),
            )

    def _fill_cp_tree(self) -> None:
        t = self.cp_tree
        t.delete(*t.get_children())
        for c in self._cp_rows:
            t.insert(
                "",
                "end",
                iid=str(c["index"]),
                values=(
                    c["index"],
                    f"{c['x0']:.3f}",
                    f"{c['z0']:.3f}",
                    f"{c['x1']:.3f}",
                    f"{c['z1']:.3f}",
                    f"{c['distance']:.3f}",
                ),
            )

    def _fill_marker_tree(self) -> None:
        t = self.marker_tree
        t.delete(*t.get_children())
        for m in self._marker_rows:
            t.insert(
                "",
                "end",
                iid=str(m["index"]),
                values=(m["index"], m.get("flags", 0), f"{m.get('distance', 0):.3f}"),
            )

    def _fill_ai_tree(self) -> None:
        t = self.ai_tree
        t.delete(*t.get_children())
        try:
            li = int(self.ai_combo.get())
        except ValueError:
            li = 0
        line = next((L for L in self._ai_lines if int(L.get("line", -1)) == li), None)
        if not line:
            self.ai_info.set("no data")
            return
        self.ai_info.set(f"{line.get('count', 0)} points  closed={line.get('closed')}")
        for p in line.get("points", []):
            t.insert(
                "",
                "end",
                iid=str(p["index"]),
                values=(
                    p["index"],
                    f"{p['x']:.3f}",
                    f"{p['z']:.3f}",
                    p.get("flags", 0),
                    p.get("segment", 0),
                    f"{p.get('radius_m', 0):.2f}",
                    f"{p.get('heading', 0):.3f}",
                ),
            )

    def _fill_mat_tree(self) -> None:
        t = self.mat_tree
        t.delete(*t.get_children())
        wd = Path(self.work_dir.get().strip())
        path = wd / "road" / "materials.json"
        if not path.is_file():
            return
        for row in json.loads(path.read_text(encoding="utf-8")):
            t.insert("", "end", values=(row.get("material"), row.get("triangles")))

    def _on_grid_select(self, _e=None) -> None:
        sel = self.grid_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        for g in self._grid_rows:
            if int(g["index"]) == idx:
                for k in self.g_vars:
                    self.g_vars[k].set(str(g.get(k, "")))
                break

    def _on_cp_select(self, _e=None) -> None:
        sel = self.cp_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        for c in self._cp_rows:
            if int(c["index"]) == idx:
                for k in self.c_vars:
                    self.c_vars[k].set(str(c.get(k, "")))
                break

    def _on_marker_select(self, _e=None) -> None:
        sel = self.marker_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        for m in self._marker_rows:
            if int(m["index"]) == idx:
                self.m_vars["flags"].set(str(m.get("flags", 0)))
                self.m_vars["distance"].set(str(m.get("distance", 0)))
                break

    def _on_ai_select(self, _e=None) -> None:
        sel = self.ai_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        li = int(self.ai_combo.get())
        line = next((L for L in self._ai_lines if int(L.get("line", -1)) == li), None)
        if not line:
            return
        for p in line.get("points", []):
            if int(p["index"]) == idx:
                for k in self.a_vars:
                    self.a_vars[k].set(str(p.get(k, "")))
                break

    def _apply_grid(self) -> None:
        sel = self.grid_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        try:
            for g in self._grid_rows:
                if int(g["index"]) == idx:
                    for k in self.g_vars:
                        g[k] = float(self.g_vars[k].get())
                    break
            self._fill_grid_tree()
            self.grid_tree.selection_set(str(idx))
            self._redraw_map()
            self._log(f"grid {idx} updated")
        except ValueError as e:
            self._err("Invalid number", e)

    def _apply_cp(self) -> None:
        sel = self.cp_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        try:
            for c in self._cp_rows:
                if int(c["index"]) == idx:
                    for k in self.c_vars:
                        c[k] = float(self.c_vars[k].get())
                    break
            self._fill_cp_tree()
            self.cp_tree.selection_set(str(idx))
            self._redraw_map()
            self._log(f"checkpoint {idx} updated")
        except ValueError as e:
            self._err("Invalid number", e)

    def _apply_marker(self) -> None:
        sel = self.marker_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        try:
            for m in self._marker_rows:
                if int(m["index"]) == idx:
                    m["flags"] = int(float(self.m_vars["flags"].get()))
                    m["distance"] = float(self.m_vars["distance"].get())
                    break
            self._fill_marker_tree()
            self.marker_tree.selection_set(str(idx))
            self._log(f"marker {idx} updated")
        except ValueError as e:
            self._err("Invalid number", e)

    def _apply_ai(self) -> None:
        sel = self.ai_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        li = int(self.ai_combo.get())
        try:
            for L in self._ai_lines:
                if int(L.get("line", -1)) != li:
                    continue
                for p in L.get("points", []):
                    if int(p["index"]) != idx:
                        continue
                    p["x"] = float(self.a_vars["x"].get())
                    p["z"] = float(self.a_vars["z"].get())
                    p["flags"] = int(float(self.a_vars["flags"].get()))
                    p["segment"] = int(float(self.a_vars["segment"].get()))
                    p["radius_m"] = float(self.a_vars["radius_m"].get())
                    p["heading"] = float(self.a_vars["heading"].get())
                    # force recompute of raw on patch from world coords
                    p.pop("raw_x", None)
                    p.pop("raw_z", None)
                    p.pop("raw_radius", None)
                    p.pop("packed", None)
                    break
            self._fill_ai_tree()
            self.ai_tree.selection_set(str(idx))
            self._redraw_map()
            self._log(f"AI line {li} point {idx} updated")
        except ValueError as e:
            self._err("Invalid number", e)

    # Map
    def _redraw_map(self) -> None:
        c = self.canvas
        c.delete("all")
        w, h = max(c.winfo_width(), 10), max(c.winfo_height(), 10)
        wd = Path(self.work_dir.get().strip())
        bounds = lib.map_bounds(wd) if wd.is_dir() else None
        if not bounds:
            c.create_text(w / 2, h / 2, text="Unpack a course to preview", fill="#888")
            return
        min_x, min_z, max_x, max_z = bounds
        span_x = max(max_x - min_x, 1e-3)
        span_z = max(max_z - min_z, 1e-3)
        margin = 24
        scale = min((w - 2 * margin) / span_x, (h - 2 * margin) / span_z)

        def sx(x: float) -> float:
            return margin + (x - min_x) * scale

        def sz(z: float) -> float:
            # flip Z so +Z is up on canvas
            return h - margin - (z - min_z) * scale

        if self.map_show["walls"].get() and self._walls:
            step = max(1, len(self._walls) // 4000)
            for wp in self._walls[::step]:
                c.create_oval(
                    sx(wp["x"]) - 0.8,
                    sz(wp["z"]) - 0.8,
                    sx(wp["x"]) + 0.8,
                    sz(wp["z"]) + 0.8,
                    outline="#3a4555",
                    fill="#3a4555",
                )

        if self.map_show["ai"].get() and self._ai_lines:
            li = int(self.ai_line_sel.get())
            line = next((L for L in self._ai_lines if int(L.get("line", -1)) == li), None)
            if line and line.get("points"):
                pts = line["points"]
                for i in range(len(pts) - 1):
                    c.create_line(
                        sx(pts[i]["x"]),
                        sz(pts[i]["z"]),
                        sx(pts[i + 1]["x"]),
                        sz(pts[i + 1]["z"]),
                        fill="#5b9bd5",
                        width=2,
                    )
                if line.get("closed") and len(pts) > 1:
                    c.create_line(
                        sx(pts[-1]["x"]),
                        sz(pts[-1]["z"]),
                        sx(pts[0]["x"]),
                        sz(pts[0]["z"]),
                        fill="#5b9bd5",
                        width=2,
                    )
                for p in pts:
                    c.create_oval(
                        sx(p["x"]) - 2,
                        sz(p["z"]) - 2,
                        sx(p["x"]) + 2,
                        sz(p["z"]) + 2,
                        outline="#7ec8ff",
                        fill="#2a6aa5",
                    )

        if self.map_show["checkpoints"].get():
            for cp in self._cp_rows:
                c.create_line(
                    sx(cp["x0"]),
                    sz(cp["z0"]),
                    sx(cp["x1"]),
                    sz(cp["z1"]),
                    fill="#e6c07b",
                    width=2,
                )

        if self.map_show["grid"].get():
            for g in self._grid_rows:
                x, z = sx(g["x"]), sz(g["z"])
                c.create_oval(x - 4, z - 4, x + 4, z + 4, outline="#f0a0a0", fill="#c05050")
                c.create_text(x + 8, z, text=str(g["index"]), fill="#ddd", anchor="w")

        c.create_text(
            8,
            8,
            anchor="nw",
            fill="#666",
            text=f"bounds X[{min_x:.0f},{max_x:.0f}] Z[{min_z:.0f},{max_z:.0f}]  scale={scale:.3f}",
        )


def main() -> None:
    CourseToolApp().mainloop()


if __name__ == "__main__":
    main()
