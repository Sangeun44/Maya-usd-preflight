"""Export with Maya USD, then check the file that was written."""
from __future__ import annotations

from typing import Optional

from maya import cmds

from .collect import collect
from .model import Scene
from .report import Issue
from .verify import expected_from_scene, verify_stage

PLUGIN = "mayaUsdPlugin"


def export(path: str, selection: bool = False, scene: Optional[Scene] = None) -> list[Issue]:
    """Write `path` and return what `verify_stage` finds wrong with it.

    `scene` is the snapshot the checks ran on; pass it so the file is compared
    with exactly what was checked.
    """
    if not cmds.pluginInfo(PLUGIN, query=True, loaded=True):
        cmds.loadPlugin(PLUGIN, quiet=True)
    scene = scene or collect(selection=selection)
    cmds.mayaUSDExport(
        file=path,
        selection=selection,
        exportUVs=True,
        exportSkels="auto",
        exportSkin="auto",
        shadingMode="useRegistry",
        convertMaterialsTo=["UsdPreviewSurface"],
        # USD prim names cannot contain ':'. The name.namespace_clash check
        # makes sure stripping them does not merge two nodes.
        stripNamespaces=True,
        mergeTransformAndShape=True,
        # Export polygons as polygons. The default marks every mesh as a
        # Catmull-Clark subdivision surface, which renders smoothed.
        defaultMeshScheme="none",
    )
    return verify_stage(path, expected_from_scene(scene))
