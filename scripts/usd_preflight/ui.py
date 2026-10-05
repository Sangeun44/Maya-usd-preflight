"""The panel artists use: run the checks, click an issue to select what is
wrong, export when the scene is clean.

`PreflightPanel` is plain Qt and is handed three callbacks, so it can be
built and tested without Maya. `show()` wires those callbacks to Maya.
"""
from __future__ import annotations

from typing import Callable, Optional

try:                                    # Maya 2025 and later
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:                     # Maya 2022 to 2024
    from PySide2 import QtCore, QtGui, QtWidgets

from .checks import CHECKS
from .report import ERROR, Report

COLOURS = {"error": "#e06c5a", "warning": "#e0b25a", "ok": "#7fbf7f"}
TITLES = {c.id: c.title for c in CHECKS}
TITLES.update({
    "export.open": "Exported file does not open",
    "export.default_prim": "Exported stage has no default prim",
    "export.up_axis": "Exported up axis differs",
    "export.mesh_count": "Exported mesh count differs",
    "export.materials": "Materials lost in the export",
    "export.bounds": "Exported geometry is not where Maya has it",
})
ISSUE_ROLE = QtCore.Qt.UserRole + 1


class PreflightPanel(QtWidgets.QWidget):
    def __init__(self,
                 run: Callable[[bool], Report],
                 select: Callable[[list], None],
                 export: Callable[[str, bool, bool], Report],
                 parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self._run, self._select, self._export = run, select, export
        self.report: Optional[Report] = None
        self.setWindowTitle("USD Preflight")
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Window)
        self.resize(760, 460)

        self.scope = QtWidgets.QComboBox()
        self.scope.addItems(["Whole scene", "Selection"])
        self.run_button = QtWidgets.QPushButton("Run Checks")
        self.summary = QtWidgets.QLabel("Not run yet")

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["Issue", "Node", "Detail"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tree.setColumnWidth(0, 300)
        self.tree.setColumnWidth(1, 130)

        self.force = QtWidgets.QCheckBox("Export even with errors")
        self.export_button = QtWidgets.QPushButton("Export USD...")
        self.export_button.setEnabled(False)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.scope)
        top.addWidget(self.run_button)
        top.addWidget(self.summary, 1)
        bottom = QtWidgets.QHBoxLayout()
        bottom.addWidget(QtWidgets.QLabel("Click an issue to select it in the scene."), 1)
        bottom.addWidget(self.force)
        bottom.addWidget(self.export_button)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.tree, 1)
        layout.addLayout(bottom)

        self.run_button.clicked.connect(self.run)
        self.export_button.clicked.connect(self.export)
        self.force.toggled.connect(self._update_export_button)
        self.tree.itemSelectionChanged.connect(self._select_in_scene)

    # ------------------------------------------------------------ actions

    def selection_only(self) -> bool:
        return self.scope.currentIndex() == 1

    def run(self):
        self.set_report(self._run(self.selection_only()))

    def export(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export USD", "", "USD (*.usd *.usda *.usdc)")
        if path:
            self.set_report(self._export(path, self.selection_only(), self.force.isChecked()))

    def set_report(self, report: Report):
        self.report = report
        self.tree.blockSignals(True)
        self.tree.clear()
        groups = {}
        for issue in report.issues:
            groups.setdefault(issue.check, []).append(issue)
        ordered = sorted(groups.items(), key=lambda kv: (kv[1][0].severity != ERROR, kv[0]))
        for check_id, issues in ordered:
            colour = QtGui.QBrush(QtGui.QColor(COLOURS[issues[0].severity]))
            group = QtWidgets.QTreeWidgetItem(
                ["%s (%d)" % (TITLES.get(check_id, check_id), len(issues)), "", check_id])
            group.setForeground(0, colour)
            group.setData(0, ISSUE_ROLE, issues)
            self.tree.addTopLevelItem(group)
            for issue in issues:
                child = QtWidgets.QTreeWidgetItem(
                    [issue.severity.capitalize(), issue.node.rsplit("|", 1)[-1] or "(scene)", issue.message])
                child.setForeground(0, colour)
                child.setToolTip(1, issue.node)
                child.setToolTip(2, issue.message)
                child.setData(0, ISSUE_ROLE, [issue])
                group.addChild(child)
            group.setExpanded(True)
        self.tree.blockSignals(False)

        state = "error" if report.errors else "warning" if report.warnings else "ok"
        text = report.summary() if report.issues else "No issues"
        if report.exported:
            text += "  |  exported %s" % report.exported
        self.summary.setText(text)
        self.summary.setStyleSheet("color: %s; font-weight: bold;" % COLOURS[state])
        self._update_export_button()

    def _update_export_button(self, *_):
        ready = self.report is not None and (self.report.ok or self.force.isChecked())
        self.export_button.setEnabled(ready)

    def _select_in_scene(self):
        targets = []
        for item in self.tree.selectedItems():
            for issue in item.data(0, ISSUE_ROLE) or []:
                targets.extend(issue.selection())
        self._select(targets)


# ------------------------------------------------------------------ Maya

_panel = None


def show() -> PreflightPanel:
    """Open the panel inside Maya."""
    global _panel
    from maya import OpenMayaUI, cmds

    try:
        from shiboken6 import wrapInstance
    except ImportError:
        from shiboken2 import wrapInstance

    from .run import preflight

    def select(targets):
        existing = [t for t in targets if cmds.objExists(t)]
        if existing:
            cmds.select(existing, replace=True)
        else:
            cmds.select(clear=True)

    # Clicking an issue changes Maya's selection, so remember what was
    # selected when the checks ran and export that, not the clicked issue.
    checked = {"roots": []}

    def run(selection):
        checked["roots"] = cmds.ls(selection=True, long=True) or []
        return preflight(selection=selection)

    def export(path, selection, force):
        if selection:
            select(checked["roots"])
        return preflight(selection=selection, export_path=path, force=force)

    if _panel is not None:
        _panel.close()
        _panel.deleteLater()
    main_window = wrapInstance(int(OpenMayaUI.MQtUtil.mainWindow()), QtWidgets.QWidget)
    _panel = PreflightPanel(run=run, select=select, export=export, parent=main_window)
    _panel.show()
    return _panel
