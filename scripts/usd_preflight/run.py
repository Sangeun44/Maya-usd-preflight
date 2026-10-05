"""The one call the command, the panel and batch mode all go through."""
from __future__ import annotations

from typing import Optional

from .checks import Settings, run_checks
from .collect import collect
from .export import export
from .report import Report


def preflight(selection: bool = False, profile: Optional[str] = None,
              export_path: Optional[str] = None, force: bool = False) -> Report:
    """Snapshot the scene, run the checks and, if `export_path` is given and
    nothing failed (or `force` is set), export and check the file too."""
    scene = collect(selection=selection)
    report = run_checks(scene, Settings.load(profile))
    if export_path and (report.ok or force):
        report.issues.extend(export(export_path, selection=selection, scene=scene))
        report.exported = export_path
    return report
