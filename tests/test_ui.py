"""The panel, driven without Maya: it only talks to the three callbacks."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from usd_preflight.report import ERROR, WARNING, Issue, Report  # noqa: E402
from usd_preflight.ui import PreflightPanel  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def report(with_error=True):
    issues = [Issue("mesh.ngons", WARNING, "|props|barrel", "2 faces with more than 4 sides", "f", [8, 9])]
    if with_error:
        issues.append(Issue("mesh.nonmanifold", ERROR, "|props|tee", "1 non-manifold edge (shared by more than two faces)", "e", [0]))
        issues.append(Issue("texture.missing", ERROR, "wood_albedo", "texture not found: missing.png"))
    return Report(scene="/show/crate.ma", up_axis="y", linear_unit="cm", issues=issues)


class Calls:
    def __init__(self, result):
        self.result, self.ran, self.selected = result, [], []

    def panel(self):
        return PreflightPanel(run=self.run, select=self.selected.append, export=lambda *a: self.result)

    def run(self, selection):
        self.ran.append(selection)
        return self.result


def test_run_fills_the_tree_errors_first(app):
    calls = Calls(report())
    panel = calls.panel()
    panel.scope.setCurrentIndex(1)
    panel.run_button.click()
    assert calls.ran == [True]
    titles = [panel.tree.topLevelItem(i).text(0) for i in range(panel.tree.topLevelItemCount())]
    assert titles == ["Non-manifold geometry (1)", "Texture file not found (1)", "Faces with too many sides (1)"]
    assert panel.tree.topLevelItem(0).child(0).text(1) == "tee"
    assert panel.summary.text() == "2 errors, 1 warning"


def test_clicking_an_issue_selects_its_components(app):
    calls = Calls(report())
    panel = calls.panel()
    panel.run()
    panel.tree.setCurrentItem(panel.tree.topLevelItem(2).child(0))
    assert calls.selected[-1] == ["|props|barrel.f[8]", "|props|barrel.f[9]"]
    panel.tree.setCurrentItem(panel.tree.topLevelItem(1))      # a whole group
    assert calls.selected[-1] == ["wood_albedo"]


def test_export_is_blocked_by_errors_unless_forced(app):
    panel = Calls(report()).panel()
    assert not panel.export_button.isEnabled()                 # nothing has been checked yet
    panel.run()
    assert not panel.export_button.isEnabled()
    panel.force.setChecked(True)
    assert panel.export_button.isEnabled()

    clean = Calls(report(with_error=False)).panel()
    clean.run()
    assert clean.export_button.isEnabled()                     # warnings do not block
    assert clean.summary.text() == "0 errors, 1 warning"
