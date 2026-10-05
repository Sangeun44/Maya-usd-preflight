"""Render the panel to an image without Maya, from a saved snapshot.

    python examples/render_panel.py out/broken_crate.snapshot.json docs/panel.png

Used for the README image. Needs PySide6; the colours imitate Maya's dark theme.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

from PySide6 import QtGui, QtWidgets  # noqa: E402

from usd_preflight.checks import run_checks  # noqa: E402
from usd_preflight.model import Scene  # noqa: E402
from usd_preflight.ui import PreflightPanel  # noqa: E402


def main(snapshot_path: str, image_path: str) -> None:
    app = QtWidgets.QApplication([])
    app.setStyle("Fusion")
    palette = QtGui.QPalette()
    for role, colour in ((QtGui.QPalette.Window, "#444444"), (QtGui.QPalette.Base, "#2b2b2b"),
                         (QtGui.QPalette.AlternateBase, "#303030"), (QtGui.QPalette.Button, "#5d5d5d"),
                         (QtGui.QPalette.Text, "#c8c8c8"), (QtGui.QPalette.WindowText, "#c8c8c8"),
                         (QtGui.QPalette.ButtonText, "#eeeeee"), (QtGui.QPalette.Highlight, "#5285a6")):
        palette.setColor(role, QtGui.QColor(colour))
    app.setPalette(palette)

    with open(snapshot_path) as handle:
        report = run_checks(Scene.from_json(handle.read()))
    panel = PreflightPanel(run=lambda selection: report, select=lambda targets: None,
                           export=lambda path, selection, force: report)
    panel.resize(900, 620)
    panel.run()
    panel.show()
    app.processEvents()
    panel.grab().save(image_path)
    print("wrote", image_path)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
