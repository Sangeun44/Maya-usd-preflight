"""Check an exported USD file against the Maya scene it came from.

The exporter reporting success does not mean the file is right. This opens
the stage with the USD API and compares it with numbers taken from the Maya
snapshot before the export: where the geometry is, how many meshes there
are, which way is up, and how many meshes still have a material.

Needs `pxr` (inside Maya it comes with the Maya USD plug-in), but not Maya.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Optional

from .checks import DEFAULT_SHADING_GROUPS
from .model import Scene
from .report import ERROR, WARNING, Issue

CM = 0.01  # Maya's internal unit, in metres


@dataclass
class Expected:
    up_axis: str
    mesh_count: int
    meshes_with_material: int
    bounds_min: Optional[list[float]]     # metres, world space; None if nothing is visible
    bounds_max: Optional[list[float]]
    has_skinned: bool = False


def _corners(low, high):
    return itertools.product(*zip(low, high))


def _grow(low, high, point):
    if low is None:
        return list(point), list(point)
    return [min(a, b) for a, b in zip(low, point)], [max(a, b) for a, b in zip(high, point)]


def expected_from_scene(scene: Scene) -> Expected:
    low = high = None
    for mesh in scene.meshes:
        if not mesh.visible or not mesh.face_vertex_counts:
            continue
        m = mesh.world_matrix
        for x, y, z in _corners(mesh.bbox_min, mesh.bbox_max):
            # Maya matrices use row vectors: p' = p * M
            point = [(x * m[i] + y * m[4 + i] + z * m[8 + i] + m[12 + i]) * CM for i in range(3)]
            low, high = _grow(low, high, point)
    return Expected(
        up_axis=scene.up_axis.upper(),
        mesh_count=len(scene.meshes),
        meshes_with_material=sum(
            1 for m in scene.meshes if set(m.shading_groups) - DEFAULT_SHADING_GROUPS),
        bounds_min=low,
        bounds_max=high,
        has_skinned=any(m.skinned for m in scene.meshes),
    )


def verify_stage(path: str, expected: Expected, tolerance: float = 1e-4) -> list[Issue]:
    from pxr import Gf, Usd, UsdGeom, UsdShade

    try:
        stage = Usd.Stage.Open(path)
    except Exception:                    # USD raises its own error type for unreadable files
        stage = None
    if not stage:
        return [Issue("export.open", ERROR, "", "could not open %s as a USD stage" % path)]

    issues = []
    if not stage.GetDefaultPrim():
        issues.append(Issue("export.default_prim", WARNING, "",
                            "stage has no defaultPrim, so it cannot be referenced without naming a prim"))

    up_axis = str(UsdGeom.GetStageUpAxis(stage)).upper()
    if up_axis != expected.up_axis:
        issues.append(Issue("export.up_axis", ERROR, "",
                            "stage is %s up, the Maya scene is %s up" % (up_axis, expected.up_axis)))

    meters_per_unit = UsdGeom.GetStageMetersPerUnit(stage)
    transforms = UsdGeom.XformCache()
    low = high = None
    mesh_count = bound = 0
    for prim in stage.Traverse(Usd.TraverseInstanceProxies()):
        if not prim.IsA(UsdGeom.Mesh):
            continue
        mesh_count += 1
        owners = [prim] + [subset.GetPrim() for subset in UsdGeom.Subset.GetAllGeomSubsets(UsdGeom.Imageable(prim))]
        if any(UsdShade.MaterialBindingAPI(p).ComputeBoundMaterial()[0] for p in owners):
            bound += 1
        if UsdGeom.Imageable(prim).ComputeVisibility() == UsdGeom.Tokens.invisible:
            continue
        mesh = UsdGeom.Mesh(prim)
        extent = mesh.GetExtentAttr().Get()
        if not extent:
            points = mesh.GetPointsAttr().Get()
            extent = UsdGeom.PointBased.ComputeExtent(points) if points else None
        if not extent:
            continue
        matrix = transforms.GetLocalToWorldTransform(prim)
        for corner in _corners(extent[0], extent[1]):
            point = matrix.Transform(Gf.Vec3d(*corner)) * meters_per_unit
            low, high = _grow(low, high, point)

    if mesh_count != expected.mesh_count:
        issues.append(Issue("export.mesh_count", WARNING, "",
                            "stage has %d meshes, the Maya scene has %d" % (mesh_count, expected.mesh_count)))
    if bound < expected.meshes_with_material:
        issues.append(Issue("export.materials", WARNING, "",
                            "%d of %d meshes with a material in Maya have none in the stage"
                            % (expected.meshes_with_material - bound, expected.meshes_with_material)))

    if expected.bounds_min is None or low is None:
        if (expected.bounds_min is None) != (low is None):
            issues.append(Issue("export.bounds", ERROR, "",
                                "visible geometry on one side only: Maya %s, stage %s"
                                % ("none" if expected.bounds_min is None else "some",
                                   "none" if low is None else "some")))
        return issues

    size = max(h - l for l, h in zip(expected.bounds_min, expected.bounds_max))
    allowed = tolerance * size + 1e-6
    worst = max(abs(a - b) for a, b in zip(list(low) + list(high),
                                           expected.bounds_min + expected.bounds_max))
    if worst > allowed:
        # A skinned mesh is exported in its bind pose, so a posed character
        # legitimately differs from what the viewport shows.
        severity = WARNING if expected.has_skinned else ERROR
        issues.append(Issue("export.bounds", severity, "",
                            "stage bounds differ from the Maya scene by %.4g m (allowed %.2g m): "
                            "Maya %s to %s, stage %s to %s"
                            % (worst, allowed, _fmt(expected.bounds_min), _fmt(expected.bounds_max),
                               _fmt(low), _fmt(high))))
    return issues


def _fmt(point) -> str:
    return "(%.4f, %.4f, %.4f)" % tuple(point)
