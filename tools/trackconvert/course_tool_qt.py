#!/usr/bin/env python3
"""
GT3 Course Tool — professional PyQt6 workspace

  pip install PyQt6
  python course_tool_qt.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from PyQt6.QtCore import QPointF, QSettings, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QActionGroup,
    QBrush,
    QColor,
    QFont,
    QKeySequence,
    QPainter,
    QPalette,
    QPen,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QStatusBar,
    QStyleFactory,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import course_lib as lib
from blender_export import export_for_blender
from mesh_io import export_gtm1_scenery, import_obj_into_gtrw

APP_TITLE = "GT3 Course Tool"
APP_ORG = "GT3Revisited"
APP_NAME = "CourseTool"
APP_VERSION = "0.4.0"


def apply_dark_theme(app: QApplication) -> None:
    app.setStyle(QStyleFactory.create("Fusion"))
    pal = QPalette()
    base = QColor("#1e1e24")
    alt = QColor("#25252e")
    text = QColor("#e6e6ea")
    disabled = QColor("#7a7a85")
    highlight = QColor("#3d6ea8")
    button = QColor("#2c2c36")
    pal.setColor(QPalette.ColorRole.Window, base)
    pal.setColor(QPalette.ColorRole.WindowText, text)
    pal.setColor(QPalette.ColorRole.Base, QColor("#18181e"))
    pal.setColor(QPalette.ColorRole.AlternateBase, alt)
    pal.setColor(QPalette.ColorRole.ToolTipBase, alt)
    pal.setColor(QPalette.ColorRole.ToolTipText, text)
    pal.setColor(QPalette.ColorRole.Text, text)
    pal.setColor(QPalette.ColorRole.Button, button)
    pal.setColor(QPalette.ColorRole.ButtonText, text)
    pal.setColor(QPalette.ColorRole.BrightText, QColor("#ff6666"))
    pal.setColor(QPalette.ColorRole.Highlight, highlight)
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.Link, QColor("#6cb6ff"))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled)
    app.setPalette(pal)
    app.setStyleSheet(
        """
        QToolBar { spacing: 4px; padding: 4px; border: none; background: #25252e; }
        QToolBar QToolButton { padding: 6px 10px; border-radius: 4px; }
        QToolBar QToolButton:hover { background: #343442; }
        QStatusBar { background: #25252e; }
        QDockWidget::title { background: #2c2c36; padding: 6px; }
        QHeaderView::section { background: #2c2c36; padding: 4px; border: 1px solid #3a3a48; }
        QTableWidget { gridline-color: #333340; }
        QLineEdit, QComboBox, QTextEdit, QPlainTextEdit {
            border: 1px solid #3a3a48; border-radius: 3px; padding: 3px;
            background: #18181e; selection-background-color: #3d6ea8;
        }
        QTabWidget::pane { border: 1px solid #3a3a48; }
        QTabBar::tab { background: #25252e; padding: 6px 12px; margin-right: 2px; }
        QTabBar::tab:selected { background: #3d6ea8; }
        QProgressBar { border: 1px solid #3a3a48; text-align: center; }
        QProgressBar::chunk { background: #3d6ea8; }
        """
    )


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------


class CourseMapView(QGraphicsView):
    pointMoved = pyqtSignal()
    selectionChanged = pyqtSignal(object)  # meta dict or None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor("#141418")))
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self.tool = "grid"
        self.ai_line = 0
        self.move_whole_cp = False
        self.show_layers = {"grid": True, "checkpoints": True, "ai": True, "walls": False}

        self._grid: list[dict] = []
        self._cps: list[dict] = []
        self._ai: list[dict] = []
        self._walls: list[dict] = []
        self._drag_item = None
        self._drag_meta: dict | None = None
        self._selected_meta: dict | None = None

    def wheelEvent(self, event):
        self.scale(1.15 if event.angleDelta().y() > 0 else 1 / 1.15, 1.15 if event.angleDelta().y() > 0 else 1 / 1.15)

    def set_data(self, grid, cps, ai_lines, walls):
        self._grid, self._cps, self._ai, self._walls = grid, cps, ai_lines, walls
        self.rebuild()

    def rebuild(self):
        self._scene.clear()
        self._drag_item = None
        self._drag_meta = None

        if self.show_layers.get("walls") and self._walls:
            step = max(1, len(self._walls) // 4000)
            pen = QPen(QColor("#3a4555"))
            brush = QBrush(QColor("#3a4555"))
            for w in self._walls[::step]:
                x, z = float(w["x"]), float(w["z"])
                self._scene.addEllipse(x - 0.4, -z - 0.4, 0.8, 0.8, pen, brush)

        if self.show_layers.get("ai") and self._ai:
            line = next((L for L in self._ai if int(L.get("line", -1)) == self.ai_line), None)
            if line and line.get("points"):
                pts = line["points"]
                pen = QPen(QColor("#5b9bd5"), 1.5)
                for i in range(len(pts) - 1):
                    self._scene.addLine(
                        float(pts[i]["x"]), -float(pts[i]["z"]),
                        float(pts[i + 1]["x"]), -float(pts[i + 1]["z"]), pen,
                    )
                if line.get("closed") and len(pts) > 1:
                    self._scene.addLine(
                        float(pts[-1]["x"]), -float(pts[-1]["z"]),
                        float(pts[0]["x"]), -float(pts[0]["z"]), pen,
                    )
                for p in pts:
                    self._add_handle(
                        float(p["x"]), float(p["z"]), 2.5, "#2a6aa5",
                        {"kind": "ai", "line": self.ai_line, "index": int(p["index"])},
                    )

        if self.show_layers.get("checkpoints"):
            pen = QPen(QColor("#e6c07b"), 1.5)
            for cp in self._cps:
                self._scene.addLine(
                    float(cp["x0"]), -float(cp["z0"]),
                    float(cp["x1"]), -float(cp["z1"]), pen,
                )
                for end, kx, kz in (("0", "x0", "z0"), ("1", "x1", "z1")):
                    self._add_handle(
                        float(cp[kx]), float(cp[kz]), 3.0, "#886622",
                        {
                            "kind": "cp", "index": int(cp["index"]), "end": end,
                            "ox0": float(cp["x0"]), "oz0": float(cp["z0"]),
                            "ox1": float(cp["x1"]), "oz1": float(cp["z1"]),
                        },
                    )

        if self.show_layers.get("grid"):
            for g in self._grid:
                self._add_handle(
                    float(g["x"]), float(g["z"]), 4.0, "#c05050",
                    {"kind": "grid", "index": int(g["index"])},
                )
                t = QGraphicsSimpleTextItem(str(g["index"]))
                t.setBrush(QBrush(QColor("#ddd")))
                t.setPos(float(g["x"]) + 5, -float(g["z"]) - 4)
                t.setFlag(QGraphicsSimpleTextItem.GraphicsItemFlag.ItemIgnoresTransformations)
                self._scene.addItem(t)

        rect = self._scene.itemsBoundingRect().adjusted(-50, -50, 50, 50)
        self._scene.setSceneRect(rect)

    def fit_all(self):
        if not self._scene.items():
            return
        self.fitInView(self._scene.itemsBoundingRect().adjusted(-20, -20, 20, 20), Qt.AspectRatioMode.KeepAspectRatio)

    def _add_handle(self, x, z, r, color, meta):
        item = QGraphicsEllipseItem(x - r, -z - r, r * 2, r * 2)
        item.setBrush(QBrush(QColor(color)))
        item.setPen(QPen(QColor("#eee")))
        item.setData(0, meta)
        item.setZValue(10)
        item.setCursor(Qt.CursorShape.PointingHandCursor)
        self._scene.addItem(item)
        return item

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            sp = self.mapToScene(event.position().toPoint())
            for it in self._scene.items(sp):
                meta = it.data(0)
                if not meta:
                    continue
                kind = meta.get("kind")
                if self.tool == "grid" and kind != "grid":
                    continue
                if self.tool == "ai" and kind != "ai":
                    continue
                if self.tool == "checkpoint" and kind != "cp":
                    continue
                self._drag_item = it
                self._drag_meta = dict(meta)
                self._selected_meta = dict(meta)
                self.selectionChanged.emit(self._selected_meta)
                self.setDragMode(QGraphicsView.DragMode.NoDrag)
                event.accept()
                return
            self._selected_meta = None
            self.selectionChanged.emit(None)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_item is not None and self._drag_meta is not None:
            sp = self.mapToScene(event.position().toPoint())
            x, z = sp.x(), -sp.y()
            meta = self._drag_meta
            kind = meta["kind"]
            if kind == "grid":
                for g in self._grid:
                    if int(g["index"]) == meta["index"]:
                        g["x"], g["z"] = x, z
                        break
            elif kind == "ai":
                for L in self._ai:
                    if int(L.get("line", -1)) != meta["line"]:
                        continue
                    for p in L.get("points", []):
                        if int(p["index"]) == meta["index"]:
                            p["x"], p["z"] = x, z
                            p.pop("raw_x", None)
                            p.pop("raw_z", None)
                            break
            elif kind == "cp":
                for cp in self._cps:
                    if int(cp["index"]) != meta["index"]:
                        continue
                    if self.move_whole_cp:
                        ax = meta["ox0"] if meta["end"] == "0" else meta["ox1"]
                        az = meta["oz0"] if meta["end"] == "0" else meta["oz1"]
                        dx, dz = x - ax, z - az
                        cp["x0"] = meta["ox0"] + dx
                        cp["z0"] = meta["oz0"] + dz
                        cp["x1"] = meta["ox1"] + dx
                        cp["z1"] = meta["oz1"] + dz
                    elif meta["end"] == "0":
                        cp["x0"], cp["z0"] = x, z
                    else:
                        cp["x1"], cp["z1"] = x, z
                    break
            r = self._drag_item.rect().width() / 2
            self._drag_item.setRect(x - r, -z - r, r * 2, r * 2)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_item is not None:
            self._drag_item = None
            self._drag_meta = None
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.rebuild()
            self.pointMoved.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


# ---------------------------------------------------------------------------
# Background batch
# ---------------------------------------------------------------------------


class BatchWorker(QThread):
    progress = pyqtSignal(int, int, str)
    log_line = pyqtSignal(str)
    finished_ok = pyqtSignal(int, int)

    def __init__(self, courses: list[Path], out_root: Path, do_blender: bool, parent=None):
        super().__init__(parent)
        self.courses = courses
        self.out_root = out_root
        self.do_blender = do_blender
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        ok = fail = 0
        total = len(self.courses)
        for i, course in enumerate(self.courses):
            if self._cancel:
                self.log_line.emit("Batch cancelled.")
                break
            self.progress.emit(i, total, course.name)
            try:
                data = course.read_bytes()
                if not lib.looks_like_course(data):
                    self.log_line.emit(f"skip (not a course): {course.name}")
                    continue
                work = self.out_root / "work" / course.name
                self.log_line.emit(lib.unpack_course(course, work))
                if self.do_blender:
                    self.log_line.emit(
                        export_for_blender(work, self.out_root / "blender" / course.name, z_up=True)
                    )
                ok += 1
            except Exception as e:
                self.log_line.emit(f"FAIL {course.name}: {e}")
                fail += 1
        self.progress.emit(total, total, "done")
        self.finished_ok.emit(ok, fail)


# ---------------------------------------------------------------------------
# Main workspace
# ---------------------------------------------------------------------------


class CourseToolWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE}  ·  {APP_VERSION}")
        self.resize(1400, 900)

        self.settings = QSettings(APP_ORG, APP_NAME)
        self._dirty = False
        self._grid: list[dict] = []
        self._cps: list[dict] = []
        self._markers: list[dict] = []
        self._ai: list[dict] = []
        self._walls: list[dict] = []
        self._undo: list = []
        self._redo: list = []
        self._batch_thread = None
        self._batch_progress = None
        self._updating_inspector = False

        self._build_central()
        self._build_docks()
        self._build_menu()
        self._build_toolbar()
        self._build_statusbar()
        self._restore_geometry()
        self._rebuild_recent_menu()

        self._set_dirty(False)
        self._log(f"{APP_TITLE} {APP_VERSION} ready.")

    # --- chrome ---

    def _build_central(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # Path bar
        path = QHBoxLayout()
        self.ed_course = QLineEdit()
        self.ed_course.setPlaceholderText("Course file…")
        self.ed_work = QLineEdit()
        self.ed_work.setPlaceholderText("Work folder…")
        self.ed_out = QLineEdit()
        self.ed_out.setPlaceholderText("Packed output…")
        for label, edit, slot in (
            ("Course", self.ed_course, self._browse_course),
            ("Work", self.ed_work, self._browse_work),
            ("Out", self.ed_out, self._browse_out),
        ):
            path.addWidget(QLabel(label))
            path.addWidget(edit, 1)
            b = QToolButton()
            b.setText("…")
            b.clicked.connect(slot)
            path.addWidget(b)
        root.addLayout(path)

        # Map + tables
        split = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(split, 1)

        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)

        layers = QHBoxLayout()
        self.chk_grid = QCheckBox("Grid")
        self.chk_grid.setChecked(True)
        self.chk_cp = QCheckBox("CP")
        self.chk_cp.setChecked(True)
        self.chk_ai = QCheckBox("AI")
        self.chk_ai.setChecked(True)
        self.chk_walls = QCheckBox("Walls")
        self.cmb_tool = QComboBox()
        self.cmb_tool.addItems(["grid", "ai", "checkpoint"])
        self.cmb_ai = QComboBox()
        self.cmb_ai.addItems([str(i) for i in range(7)])
        self.chk_whole_cp = QCheckBox("Whole CP")
        btn_fit = QPushButton("Fit")
        btn_fit.clicked.connect(lambda: self.map.fit_all())
        for w in (
            self.chk_grid, self.chk_cp, self.chk_ai, self.chk_walls,
            QLabel("Drag"), self.cmb_tool, QLabel("AI#"), self.cmb_ai,
            self.chk_whole_cp, btn_fit,
        ):
            layers.addWidget(w)
        layers.addStretch(1)
        left_l.addLayout(layers)

        self.map = CourseMapView()
        left_l.addWidget(self.map, 1)
        split.addWidget(left)

        self.tabs = QTabWidget()
        self.tbl_grid = self._make_table(["index", "x", "y", "z", "yaw"])
        self.tbl_cp = self._make_table(["index", "x0", "z0", "x1", "z1", "distance"])
        self.tbl_markers = self._make_table(["index", "flags", "distance"])
        self.tbl_ai = self._make_table(["index", "x", "z", "flags", "segment", "radius_m", "heading"])
        self.tbl_mat = self._make_table(["material", "triangles"])
        self.tbl_mat.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        self.tabs.addTab(self.tbl_grid, "Start grid")
        self.tabs.addTab(self.tbl_cp, "Checkpoints")
        self.tabs.addTab(self.tbl_markers, "Markers")
        ai_w = QWidget()
        ai_l = QVBoxLayout(ai_w)
        ai_l.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel("Line"))
        self.cmb_ai_table = QComboBox()
        self.cmb_ai_table.addItems([str(i) for i in range(7)])
        self.cmb_ai_table.currentIndexChanged.connect(self._fill_ai_table)
        row.addWidget(self.cmb_ai_table)
        row.addStretch(1)
        ai_l.addLayout(row)
        ai_l.addWidget(self.tbl_ai)
        self.tabs.addTab(ai_w, "AI lines")
        self.tabs.addTab(self.tbl_mat, "Materials")
        split.addWidget(self.tabs)
        split.setSizes([820, 520])

        for chk in (self.chk_grid, self.chk_cp, self.chk_ai, self.chk_walls):
            chk.toggled.connect(self._sync_map_layers)
        self.cmb_tool.currentTextChanged.connect(self._sync_map_layers)
        self.cmb_ai.currentIndexChanged.connect(self._sync_map_layers)
        self.chk_whole_cp.toggled.connect(self._sync_map_layers)
        self.map.pointMoved.connect(self._after_map_edit)
        self.map.selectionChanged.connect(self._on_map_selection)

        self.tbl_grid.itemChanged.connect(lambda *_: self._table_to_grid())
        self.tbl_cp.itemChanged.connect(lambda *_: self._table_to_cp())
        self.tbl_markers.itemChanged.connect(lambda *_: self._table_to_markers())
        self.tbl_ai.itemChanged.connect(lambda *_: self._table_to_ai())

    def _build_docks(self):
        # Inspector
        self.inspector = QTextEdit()
        self.inspector.setReadOnly(True)
        self.inspector.setPlaceholderText("Select a map handle to inspect.")
        dock_i = QDockWidget("Inspector", self)
        dock_i.setObjectName("dockInspector")
        dock_i.setWidget(self.inspector)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock_i)

        # Overview
        self.txt_overview = QTextEdit()
        self.txt_overview.setReadOnly(True)
        dock_o = QDockWidget("Overview", self)
        dock_o.setObjectName("dockOverview")
        dock_o.setWidget(self.txt_overview)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock_o)
        self.tabifyDockWidget(dock_i, dock_o)
        dock_i.raise_()

        # Log
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setFont(QFont("Consolas", 10))
        dock_l = QDockWidget("Output", self)
        dock_l.setObjectName("dockLog")
        dock_l.setWidget(self.txt_log)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock_l)

    def _build_menu(self):
        m = self.menuBar()
        f = m.addMenu("&File")
        f.addAction(self._act("Open course…", self._browse_course, QKeySequence.StandardKey.Open))
        f.addAction(self._act("Open work folder…", self._browse_work))
        self.menu_recent = f.addMenu("Recent courses")
        f.addSeparator()
        f.addAction(self._act("Unpack", self._unpack, "Ctrl+U"))
        f.addAction(self._act("Reload work", self._reload, QKeySequence.StandardKey.Refresh))
        f.addAction(self._act("Save JSON", self._save_json, QKeySequence.StandardKey.Save))
        f.addAction(self._act("Pack course", self._pack, "Ctrl+P"))
        f.addSeparator()
        f.addAction(self._act("Zip work…", self._zip_work))
        f.addSeparator()
        f.addAction(self._act("Exit", self.close, QKeySequence.StandardKey.Quit))

        e = m.addMenu("&Edit")
        e.addAction(self._act("Undo", self._undo_edit, QKeySequence.StandardKey.Undo))
        e.addAction(self._act("Redo", self._redo_edit, QKeySequence.StandardKey.Redo))
        e.addSeparator()
        e.addAction(self._act("Fit map", lambda: self.map.fit_all(), "Ctrl+0"))

        t = m.addMenu("&Tools")
        for label, slot, seq in (
            ("Patch GTRW", self._patch_gtrw, "Ctrl+Shift+G"),
            ("Patch AI", self._patch_ai, "Ctrl+Shift+A"),
            ("Export Blender…", self._export_blender, "Ctrl+E"),
            ("Import OBJ→GTRW…", self._import_obj, "Ctrl+I"),
            ("Export scenery…", self._export_scenery, None),
            ("Batch process…", self._batch, "Ctrl+B"),
        ):
            t.addAction(self._act(label, slot, seq))

        v = m.addMenu("&View")
        v.addAction(self._act("Reset dock layout", self._reset_docks))

        h = m.addMenu("&Help")
        h.addAction(self._act("Keyboard shortcuts", self._shortcuts_help))
        h.addAction(self._act("About", self._about))

    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setObjectName("mainToolbar")
        tb.setMovable(False)
        self.addToolBar(tb)
        for label, slot in (
            ("Unpack", self._unpack),
            ("Reload", self._reload),
            ("Save JSON", self._save_json),
            ("Patch GTRW", self._patch_gtrw),
            ("Patch AI", self._patch_ai),
            ("Pack", self._pack),
            ("Blender", self._export_blender),
            ("Import OBJ", self._import_obj),
            ("Scenery", self._export_scenery),
            ("Batch", self._batch),
            ("Undo", self._undo_edit),
            ("Redo", self._redo_edit),
        ):
            tb.addAction(self._act(label, slot))

    def _build_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.lbl_dirty = QLabel("")
        self.lbl_stats = QLabel("")
        self.lbl_path = QLabel("")
        self.lbl_path.setMinimumWidth(200)
        sb.addWidget(self.lbl_dirty)
        sb.addWidget(self.lbl_stats, 1)
        sb.addPermanentWidget(self.lbl_path)

    def _act(self, text, slot, shortcut=None) -> QAction:
        a = QAction(text, self)
        a.triggered.connect(slot)
        if shortcut is not None:
            if isinstance(shortcut, str):
                a.setShortcut(QKeySequence(shortcut))
            else:
                a.setShortcut(shortcut)
        return a

    # --- settings / recent ---

    def _restore_geometry(self):
        geo = self.settings.value("geometry")
        state = self.settings.value("windowState")
        if geo is not None:
            self.restoreGeometry(geo)
        if state is not None:
            self.restoreState(state)
        course = self.settings.value("lastCourse", "")
        work = self.settings.value("lastWork", "")
        out = self.settings.value("lastOut", "")
        if course:
            self.ed_course.setText(str(course))
        if work:
            self.ed_work.setText(str(work))
        if out:
            self.ed_out.setText(str(out))

    def closeEvent(self, event):
        if self._dirty:
            r = QMessageBox.question(
                self, APP_TITLE,
                "You have unsaved table/map edits in memory.\nSave JSON before exit?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
            )
            if r == QMessageBox.StandardButton.Save:
                self._save_json()
            elif r == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())
        self.settings.setValue("lastCourse", self.ed_course.text())
        self.settings.setValue("lastWork", self.ed_work.text())
        self.settings.setValue("lastOut", self.ed_out.text())
        super().closeEvent(event)

    def _add_recent(self, path: str):
        recent = self.settings.value("recentCourses", [])
        if not isinstance(recent, list):
            recent = list(recent) if recent else []
        recent = [str(p) for p in recent if str(p) != path]
        recent.insert(0, path)
        self.settings.setValue("recentCourses", recent[:12])
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        self.menu_recent.clear()
        recent = self.settings.value("recentCourses", [])
        if not isinstance(recent, list):
            recent = list(recent) if recent else []
        if not recent:
            a = self.menu_recent.addAction("(empty)")
            a.setEnabled(False)
            return
        for p in recent:
            self.menu_recent.addAction(p, lambda checked=False, path=p: self._open_recent(path))

    def _open_recent(self, path: str):
        self.ed_course.setText(path)
        src = Path(path)
        if src.is_file():
            if not self.ed_work.text().strip():
                self.ed_work.setText(str(src.parent / f"{src.name}_edit"))
            if not self.ed_out.text().strip():
                self.ed_out.setText(str(src.parent / f"{src.name}_mod"))

    def _reset_docks(self):
        self.settings.remove("windowState")
        QMessageBox.information(self, APP_TITLE, "Dock layout reset will apply on next launch.")

    # --- state ---

    def _set_dirty(self, dirty: bool):
        self._dirty = dirty
        self.lbl_dirty.setText("● modified" if dirty else "○ clean")
        self.lbl_dirty.setStyleSheet("color: #e6c07b;" if dirty else "color: #7a7a85;")
        title = f"{APP_TITLE}  ·  {APP_VERSION}"
        wd = self.ed_work.text().strip()
        if wd:
            title += f"  —  {Path(wd).name}"
        if dirty:
            title = "• " + title
        self.setWindowTitle(title)
        self.lbl_stats.setText(
            f"grid {len(self._grid)}  ·  cp {len(self._cps)}  ·  "
            f"markers {len(self._markers)}  ·  ai lines {len(self._ai)}  ·  walls {len(self._walls)}"
        )
        self.lbl_path.setText(wd or "no work folder")

    def _log(self, msg: str):
        self.txt_log.append(msg.rstrip())
        self.statusBar().showMessage(msg.splitlines()[-1][:180], 6000)

    def _err(self, title: str, exc: BaseException):
        self._log(f"ERROR: {exc}")
        QMessageBox.critical(self, title, str(exc))

    def _work(self) -> Path:
        return Path(self.ed_work.text().strip())

    def _push_undo(self):
        self._undo.append(
            {
                "grid": copy.deepcopy(self._grid),
                "cp": copy.deepcopy(self._cps),
                "markers": copy.deepcopy(self._markers),
                "ai": copy.deepcopy(self._ai),
            }
        )
        if len(self._undo) > 50:
            self._undo.pop(0)
        self._redo.clear()

    def _restore(self, snap):
        self._grid = snap["grid"]
        self._cps = snap["cp"]
        self._markers = snap["markers"]
        self._ai = snap["ai"]
        self._fill_all_tables()
        self._refresh_map()
        self._set_dirty(True)

    def _undo_edit(self):
        if not self._undo:
            self.statusBar().showMessage("Nothing to undo")
            return
        self._redo.append(
            {
                "grid": copy.deepcopy(self._grid),
                "cp": copy.deepcopy(self._cps),
                "markers": copy.deepcopy(self._markers),
                "ai": copy.deepcopy(self._ai),
            }
        )
        self._restore(self._undo.pop())
        self._log("undo")

    def _redo_edit(self):
        if not self._redo:
            self.statusBar().showMessage("Nothing to redo")
            return
        self._undo.append(
            {
                "grid": copy.deepcopy(self._grid),
                "cp": copy.deepcopy(self._cps),
                "markers": copy.deepcopy(self._markers),
                "ai": copy.deepcopy(self._ai),
            }
        )
        self._restore(self._redo.pop())
        self._log("redo")

    def _sync_map_layers(self):
        self.map.tool = self.cmb_tool.currentText()
        self.map.ai_line = self.cmb_ai.currentIndex()
        self.map.move_whole_cp = self.chk_whole_cp.isChecked()
        self.map.show_layers = {
            "grid": self.chk_grid.isChecked(),
            "checkpoints": self.chk_cp.isChecked(),
            "ai": self.chk_ai.isChecked(),
            "walls": self.chk_walls.isChecked(),
        }
        self.map.rebuild()

    def _refresh_map(self):
        self.map.set_data(self._grid, self._cps, self._ai, self._walls)
        self._sync_map_layers()

    def _after_map_edit(self):
        self._fill_all_tables()
        self._set_dirty(True)
        self._log("map edit applied")

    def _on_map_selection(self, meta):
        if not meta:
            self.inspector.setPlainText("No selection.")
            return
        lines = [f"kind: {meta.get('kind')}", ""]
        for k, v in meta.items():
            if k == "kind":
                continue
            lines.append(f"{k}: {v}")
        # enrich from live data
        if meta.get("kind") == "grid":
            for g in self._grid:
                if int(g["index"]) == int(meta["index"]):
                    lines.append("")
                    lines.append(f"x={g['x']:.4f} y={g['y']:.4f} z={g['z']:.4f}")
                    lines.append(f"yaw={g['yaw']:.5f} rad")
                    break
        self.inspector.setPlainText("\n".join(lines))

    # --- tables ---

    def _make_table(self, cols):
        t = QTableWidget(0, len(cols))
        t.setHorizontalHeaderLabels(cols)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setAlternatingRowColors(True)
        return t

    def _block_tables(self, block: bool):
        for t in (self.tbl_grid, self.tbl_cp, self.tbl_markers, self.tbl_ai):
            t.blockSignals(block)

    def _fill_table(self, table, rows, keys):
        table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, k in enumerate(keys):
                val = row.get(k, "")
                text = f"{val:.6g}" if isinstance(val, float) else str(val)
                table.setItem(r, c, QTableWidgetItem(text))

    def _fill_all_tables(self):
        self._block_tables(True)
        self._fill_table(self.tbl_grid, self._grid, ["index", "x", "y", "z", "yaw"])
        self._fill_table(self.tbl_cp, self._cps, ["index", "x0", "z0", "x1", "z1", "distance"])
        self._fill_table(self.tbl_markers, self._markers, ["index", "flags", "distance"])
        self._fill_ai_table()
        self._block_tables(False)

    def _fill_ai_table(self):
        self.tbl_ai.blockSignals(True)
        li = self.cmb_ai_table.currentIndex()
        line = next((L for L in self._ai if int(L.get("line", -1)) == li), None)
        pts = line.get("points", []) if line else []
        self._fill_table(self.tbl_ai, pts, ["index", "x", "z", "flags", "segment", "radius_m", "heading"])
        self.tbl_ai.blockSignals(False)

    def _table_to_grid(self):
        self._push_undo()
        out = []
        for r in range(self.tbl_grid.rowCount()):
            out.append({
                "index": int(float(self.tbl_grid.item(r, 0).text())),
                "x": float(self.tbl_grid.item(r, 1).text()),
                "y": float(self.tbl_grid.item(r, 2).text()),
                "z": float(self.tbl_grid.item(r, 3).text()),
                "yaw": float(self.tbl_grid.item(r, 4).text()),
            })
        self._grid = out
        self._refresh_map()
        self._set_dirty(True)

    def _table_to_cp(self):
        self._push_undo()
        by_i = {int(c["index"]): c for c in self._cps}
        out = []
        keys = ["index", "x0", "z0", "x1", "z1", "distance"]
        for r in range(self.tbl_cp.rowCount()):
            idx = int(float(self.tbl_cp.item(r, 0).text()))
            base = dict(by_i.get(idx, {}))
            for c, k in enumerate(keys):
                text = self.tbl_cp.item(r, c).text()
                base[k] = int(float(text)) if k == "index" else float(text)
            out.append(base)
        self._cps = out
        self._refresh_map()
        self._set_dirty(True)

    def _table_to_markers(self):
        self._push_undo()
        out = []
        for r in range(self.tbl_markers.rowCount()):
            out.append({
                "index": int(float(self.tbl_markers.item(r, 0).text())),
                "flags": int(float(self.tbl_markers.item(r, 1).text())),
                "distance": float(self.tbl_markers.item(r, 2).text()),
            })
        self._markers = out
        self._set_dirty(True)

    def _table_to_ai(self):
        self._push_undo()
        li = self.cmb_ai_table.currentIndex()
        for L in self._ai:
            if int(L.get("line", -1)) != li:
                continue
            pts = []
            for r in range(self.tbl_ai.rowCount()):
                pts.append({
                    "index": int(float(self.tbl_ai.item(r, 0).text())),
                    "x": float(self.tbl_ai.item(r, 1).text()),
                    "z": float(self.tbl_ai.item(r, 2).text()),
                    "flags": int(float(self.tbl_ai.item(r, 3).text())),
                    "segment": int(float(self.tbl_ai.item(r, 4).text())),
                    "radius_m": float(self.tbl_ai.item(r, 5).text()),
                    "heading": float(self.tbl_ai.item(r, 6).text()),
                })
            L["points"] = pts
            L["count"] = len(pts)
            break
        self._refresh_map()
        self._set_dirty(True)

    def _refresh_overview(self):
        wd = self._work()
        lines = [f"Work folder: {wd}", ""]
        if not wd.is_dir():
            lines.append("Unpack a course to populate this panel.")
        else:
            man = wd / "manifest.json"
            if man.is_file():
                m = json.loads(man.read_text(encoding="utf-8"))
                lines += [f"Source: {m.get('source')}", f"Format: {m.get('format')}  size={m.get('size')}", "", "Slots:"]
                for s in m.get("slots", []):
                    lines.append(f"  [{s.get('slot'):2}] {s.get('tag') or '-':4}  {s.get('size', 0):8} B  {s.get('hint', '')}")
            summary = wd / "road" / "summary.json"
            if summary.is_file():
                s = json.loads(summary.read_text(encoding="utf-8"))
                lines.append("\nRoad (GTRW):")
                for k, v in s.items():
                    if k != "materials":
                        lines.append(f"  {k}: {v}")
            ai = wd / "ai" / "summary.json"
            if ai.is_file():
                a = json.loads(ai.read_text(encoding="utf-8"))
                lines.append(f"\nAI build: {a.get('build')}")
                for L in a.get("lines", []):
                    lines.append(f"  line {L.get('line')}: {L.get('count')} pts  closed={L.get('closed')}")
        self.txt_overview.setPlainText("\n".join(lines))

    def _load_mats(self):
        path = self._work() / "road" / "materials.json"
        if not path.is_file():
            self.tbl_mat.setRowCount(0)
            return
        rows = json.loads(path.read_text(encoding="utf-8"))
        self._fill_table(self.tbl_mat, rows, ["material", "triangles"])

    # --- browse / actions ---

    def _browse_course(self):
        start = self.settings.value("lastCourseDir", "")
        p, _ = QFileDialog.getOpenFileName(self, "Course file", str(start))
        if not p:
            return
        self.ed_course.setText(p)
        self.settings.setValue("lastCourseDir", str(Path(p).parent))
        self._add_recent(p)
        src = Path(p)
        if not self.ed_work.text().strip():
            self.ed_work.setText(str(src.parent / f"{src.name}_edit"))
        if not self.ed_out.text().strip():
            self.ed_out.setText(str(src.parent / f"{src.name}_mod"))

    def _browse_work(self):
        p = QFileDialog.getExistingDirectory(self, "Work folder", self.ed_work.text())
        if p:
            self.ed_work.setText(p)
            self._reload()

    def _browse_out(self):
        p, _ = QFileDialog.getSaveFileName(self, "Output course", self.ed_out.text())
        if p:
            self.ed_out.setText(p)

    def _reload(self):
        wd = self._work()
        if not wd.is_dir():
            return
        try:
            self._grid = lib.load_grid(wd)
            self._cps = lib.load_checkpoints(wd)
            self._markers = lib.load_markers(wd)
            self._ai = lib.load_ai_lines(wd)
            walls_path = wd / "road" / "walls.json"
            self._walls = json.loads(walls_path.read_text(encoding="utf-8")) if walls_path.is_file() else []
            self._fill_all_tables()
            self._load_mats()
            self._refresh_map()
            self._refresh_overview()
            self._set_dirty(False)
            QTimer.singleShot(0, self.map.fit_all)
            self._log(
                f"reloaded grid={len(self._grid)} cp={len(self._cps)} "
                f"markers={len(self._markers)} ai={len(self._ai)} walls={len(self._walls)}"
            )
        except Exception as e:
            self._err("Reload failed", e)

    def _unpack(self):
        src = Path(self.ed_course.text().strip())
        dst = self._work()
        if not src.is_file():
            QMessageBox.warning(self, APP_TITLE, "Choose a course file.")
            return
        try:
            msg = lib.unpack_course(src, dst)
            self._add_recent(str(src))
            self._log(msg)
            self._reload()
            QMessageBox.information(self, APP_TITLE, msg)
        except Exception as e:
            self._err("Unpack failed", e)

    def _save_json(self):
        wd = self._work()
        try:
            lib.save_grid(wd, self._grid)
            lib.save_checkpoints(wd, self._cps)
            lib.save_markers(wd, self._markers)
            lib.save_ai_lines(wd, self._ai)
            self._set_dirty(False)
            self._log("saved JSON")
        except Exception as e:
            self._err("Save failed", e)

    def _patch_gtrw(self):
        try:
            self._save_json()
            msg = lib.patch_gtrw_from_json(self._work())
            self._log(msg)
            QMessageBox.information(self, APP_TITLE, msg)
        except Exception as e:
            self._err("Patch GTRW failed", e)

    def _patch_ai(self):
        try:
            self._save_json()
            msg = lib.patch_ai_from_json(self._work())
            self._log(msg)
            QMessageBox.information(self, APP_TITLE, msg)
        except Exception as e:
            self._err("Patch AI failed", e)

    def _pack(self):
        wd = self._work()
        out = Path(self.ed_out.text().strip())
        try:
            self._save_json()
            if (wd / "road" / "GTRW.bin").is_file():
                lib.patch_gtrw_from_json(wd)
            if (wd / "ai" / "AI.bin").is_file():
                lib.patch_ai_from_json(wd)
            msg = lib.pack_course(wd, out)
            self._log(msg)
            QMessageBox.information(self, APP_TITLE, msg)
        except Exception as e:
            self._err("Pack failed", e)

    def _export_blender(self):
        wd = self._work()
        if not wd.is_dir():
            QMessageBox.warning(self, APP_TITLE, "Unpack first.")
            return
        out = QFileDialog.getExistingDirectory(self, "Blender export folder")
        if not out:
            return
        try:
            msg = export_for_blender(wd, Path(out), z_up=True)
            self._log(msg)
            QMessageBox.information(self, APP_TITLE, msg)
        except Exception as e:
            self._err("Blender export failed", e)

    def _import_obj(self):
        obj, _ = QFileDialog.getOpenFileName(self, "Road OBJ", filter="OBJ (*.obj)")
        if not obj:
            return
        try:
            msg = import_obj_into_gtrw(self._work(), Path(obj), from_z_up=True)
            self._log(msg)
            QMessageBox.information(self, APP_TITLE, msg)
        except Exception as e:
            self._err("OBJ import failed", e)

    def _export_scenery(self):
        out = QFileDialog.getExistingDirectory(self, "Scenery export folder")
        if not out:
            return
        try:
            msg = export_gtm1_scenery(self._work(), Path(out), z_up=True)
            self._log(msg)
            QMessageBox.information(self, APP_TITLE, msg)
        except Exception as e:
            self._err("Scenery export failed", e)

    def _zip_work(self):
        path, _ = QFileDialog.getSaveFileName(self, "Zip work", filter="ZIP (*.zip)")
        if not path:
            return
        try:
            self._save_json()
            msg = lib.zip_work_folder(self._work(), Path(path))
            self._log(msg)
            QMessageBox.information(self, APP_TITLE, msg)
        except Exception as e:
            self._err("Zip failed", e)

    def _batch(self):
        if self._batch_thread is not None and self._batch_thread.isRunning():
            QMessageBox.warning(self, APP_TITLE, "Batch already running.")
            return
        src_dir = QFileDialog.getExistingDirectory(self, "Folder of course files")
        if not src_dir:
            return
        out_root = QFileDialog.getExistingDirectory(self, "Output root")
        if not out_root:
            return
        do_bl = (
            QMessageBox.question(self, APP_TITLE, "Also export Blender folders?")
            == QMessageBox.StandardButton.Yes
        )
        courses = sorted(p for p in Path(src_dir).iterdir() if p.is_file())
        if not courses:
            QMessageBox.information(self, APP_TITLE, "No files in that folder.")
            return

        self._batch_progress = QProgressDialog("Batch processing…", "Cancel", 0, len(courses), self)
        self._batch_progress.setWindowTitle(APP_TITLE)
        self._batch_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._batch_progress.setMinimumDuration(0)
        self._batch_progress.setValue(0)

        self._batch_thread = BatchWorker(courses, Path(out_root), do_bl, self)
        self._batch_thread.progress.connect(self._on_batch_progress)
        self._batch_thread.log_line.connect(self._log)
        self._batch_thread.finished_ok.connect(self._on_batch_finished)
        self._batch_progress.canceled.connect(self._batch_thread.cancel)
        self._batch_thread.start()

    def _on_batch_progress(self, current: int, total: int, name: str):
        if not self._batch_progress:
            return
        self._batch_progress.setMaximum(max(total, 1))
        self._batch_progress.setValue(current)
        self._batch_progress.setLabelText(
            f"Processing {current + 1}/{total}: {name}" if current < total else "Finishing…"
        )

    def _on_batch_finished(self, ok: int, fail: int):
        if self._batch_progress:
            self._batch_progress.setValue(self._batch_progress.maximum())
            self._batch_progress.close()
            self._batch_progress = None
        self._batch_thread = None
        self._log(f"Batch finished: {ok} ok, {fail} failed")
        QMessageBox.information(self, APP_TITLE, f"Batch: {ok} ok, {fail} failed")

    def _shortcuts_help(self):
        QMessageBox.information(
            self, "Shortcuts",
            "Ctrl+O  Open course\n"
            "Ctrl+U  Unpack\n"
            "Ctrl+S  Save JSON\n"
            "Ctrl+P  Pack\n"
            "Ctrl+E  Export Blender\n"
            "Ctrl+I  Import OBJ\n"
            "Ctrl+B  Batch\n"
            "Ctrl+Z / Ctrl+Y  Undo / Redo\n"
            "Ctrl+0  Fit map\n"
            "F5  Reload work\n\n"
            "Map: wheel zoom · drag empty space pan · left-drag handles",
        )

    def _about(self):
        QMessageBox.about(
            self, APP_TITLE,
            f"<h3>{APP_TITLE}</h3>"
            f"<p>Version {APP_VERSION}</p>"
            "<p>Professional workspace for GT3 course unpack / edit / Blender export / pack.</p>"
            "<p>Companion tool for <b>GT3-revisited</b>.</p>",
        )


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName(APP_ORG)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    apply_dark_theme(app)
    win = CourseToolWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
