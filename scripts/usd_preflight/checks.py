"""The checks. Each one reads a `Scene` snapshot and yields `Issue`s.

Nothing here imports Maya, so the whole file runs under plain Python.
To add a check, write a function and decorate it with `@check`.
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, fields
from typing import Callable, Iterator, Optional

from .model import Scene
from .report import ERROR, SEVERITIES, WARNING, Issue, Report


@dataclass
class Settings:
    up_axis: Optional[str] = None        # "y" or "z"; None accepts either
    linear_unit: Optional[str] = None    # "cm", "m", ...; None accepts any
    max_face_sides: int = 4
    zero_area_tolerance: float = 1e-8    # cm^2
    scale_tolerance: float = 1e-4
    joint_angle_tolerance: float = 5.0   # degrees a bone may lean off its aim axis
    disable: list[str] = field(default_factory=list)
    severity: dict[str, str] = field(default_factory=dict)   # check id -> severity

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError("unknown profile setting(s): %s" % ", ".join(unknown))
        settings = cls(**data)
        ids = {c.id for c in CHECKS}
        bad = sorted((set(settings.disable) | set(settings.severity)) - ids)
        if bad:
            raise ValueError("profile names unknown check(s): %s" % ", ".join(bad))
        wrong = sorted(set(settings.severity.values()) - set(SEVERITIES))
        if wrong:
            raise ValueError("severity must be one of %s, not %s" % (SEVERITIES, wrong))
        return settings

    @classmethod
    def load(cls, path: Optional[str]) -> "Settings":
        if not path:
            return cls()
        with open(path) as handle:
            return cls.from_dict(json.load(handle))


@dataclass(frozen=True)
class Check:
    id: str
    severity: str
    title: str
    func: Callable[[Scene, Settings], Iterator[Issue]]


CHECKS: list[Check] = []


def check(check_id: str, severity: str, title: str):
    def register(func):
        CHECKS.append(Check(check_id, severity, title, func))
        return func
    return register


def run_checks(scene: Scene, settings: Optional[Settings] = None) -> Report:
    settings = settings or Settings()
    report = Report(scene=scene.file, up_axis=scene.up_axis, linear_unit=scene.linear_unit)
    for item in CHECKS:
        if item.id in settings.disable:
            continue
        severity = settings.severity.get(item.id, item.severity)
        for issue in item.func(scene, settings):
            issue.check = item.id
            issue.severity = severity
            report.issues.append(issue)
    return report


def _issue(node: str, message: str, component: Optional[str] = None,
           indices: Optional[list[int]] = None) -> Issue:
    # check id and severity are filled in by run_checks
    return Issue("", "", node, message, component, list(indices or []))


def _n(count: int, noun: str, plural: Optional[str] = None) -> str:
    return "%d %s" % (count, noun if count == 1 else plural or noun + "s")


# ---------------------------------------------------------------- scene

@check("scene.empty", ERROR, "Nothing to export")
def scene_empty(scene, settings):
    if not scene.meshes and not scene.joints:
        yield _issue("", "no meshes or joints found")


@check("scene.up_axis", ERROR, "Up axis differs from the profile")
def scene_up_axis(scene, settings):
    if settings.up_axis and scene.up_axis.lower() != settings.up_axis.lower():
        yield _issue("", "scene is %s up, the profile expects %s up"
                     % (scene.up_axis.upper(), settings.up_axis.upper()))


@check("scene.units", ERROR, "Linear unit differs from the profile")
def scene_units(scene, settings):
    if settings.linear_unit and scene.linear_unit != settings.linear_unit:
        yield _issue("", "scene works in %s, the profile expects %s"
                     % (scene.linear_unit, settings.linear_unit))


# ----------------------------------------------------------------- mesh

@check("mesh.empty", ERROR, "Mesh has no faces")
def mesh_empty(scene, settings):
    for mesh in scene.meshes:
        if not mesh.face_vertex_counts:
            yield _issue(mesh.path, "mesh has no faces")


@check("mesh.nonmanifold", ERROR, "Non-manifold geometry")
def mesh_nonmanifold(scene, settings):
    for mesh in scene.meshes:
        if mesh.nonmanifold_edges:
            yield _issue(mesh.path, "%s (shared by more than two faces)"
                         % _n(len(mesh.nonmanifold_edges), "non-manifold edge"), "e", mesh.nonmanifold_edges)
        if mesh.nonmanifold_vertices:
            yield _issue(mesh.path, _n(len(mesh.nonmanifold_vertices), "non-manifold vertex",
                                       "non-manifold vertices"), "vtx", mesh.nonmanifold_vertices)


@check("mesh.lamina_faces", ERROR, "Faces stacked on top of each other")
def mesh_lamina(scene, settings):
    for mesh in scene.meshes:
        if mesh.lamina_faces:
            yield _issue(mesh.path, "%s sharing all of their edges with another face"
                         % _n(len(mesh.lamina_faces), "face"), "f", mesh.lamina_faces)


@check("mesh.zero_area_faces", ERROR, "Faces with no area")
def mesh_zero_area(scene, settings):
    for mesh in scene.meshes:
        bad = [i for i, area in enumerate(mesh.face_areas) if area <= settings.zero_area_tolerance]
        if bad:
            yield _issue(mesh.path, "%s with zero area" % _n(len(bad), "face"), "f", bad)


@check("mesh.ngons", WARNING, "Faces with too many sides")
def mesh_ngons(scene, settings):
    for mesh in scene.meshes:
        bad = [i for i, count in enumerate(mesh.face_vertex_counts) if count > settings.max_face_sides]
        if bad:
            yield _issue(mesh.path, "%s with more than %d sides; each importer triangulates these its own way"
                         % (_n(len(bad), "face"), settings.max_face_sides), "f", bad)


@check("mesh.missing_uvs", WARNING, "Faces without UVs")
def mesh_missing_uvs(scene, settings):
    for mesh in scene.meshes:
        if not mesh.face_vertex_counts or not mesh.faces_without_uvs:
            continue
        if len(mesh.faces_without_uvs) == len(mesh.face_vertex_counts):
            yield _issue(mesh.path, "mesh has no UVs")
        else:
            yield _issue(mesh.path, "%s without UVs" % _n(len(mesh.faces_without_uvs), "face"),
                         "f", mesh.faces_without_uvs)


def _axes(matrix: list[float]) -> list[list[float]]:
    """The X, Y and Z axes of a Maya matrix (16 floats, row vectors)."""
    return [matrix[0:3], matrix[4:7], matrix[8:11]]


def _determinant(a: list[list[float]]) -> float:
    return (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
            - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
            + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))


def _length(v: list[float]) -> float:
    return math.sqrt(sum(c * c for c in v))


@check("mesh.negative_scale", ERROR, "Mirrored by a negative scale")
def mesh_negative_scale(scene, settings):
    for mesh in scene.meshes:
        if _determinant(_axes(mesh.world_matrix)) < 0:
            yield _issue(mesh.path, "world transform is mirrored (negative scale), which flips the "
                                    "face winding; freeze the scale and fix the normals")


@check("mesh.nonuniform_scale", WARNING, "Non-uniform scale or shear")
def mesh_nonuniform_scale(scene, settings):
    for mesh in scene.meshes:
        axes = _axes(mesh.world_matrix)
        lengths = [_length(a) for a in axes]
        if min(lengths) <= 0:
            yield _issue(mesh.path, "world transform has a zero scale")
            continue
        tolerance = settings.scale_tolerance
        sheared = any(
            abs(sum(p * q for p, q in zip(axes[i], axes[j]))) / (lengths[i] * lengths[j]) > tolerance
            for i, j in ((0, 1), (0, 2), (1, 2)))
        if sheared:
            yield _issue(mesh.path, "world transform is sheared; physics engines cannot represent this")
        elif max(lengths) - min(lengths) > tolerance * max(lengths):
            yield _issue(mesh.path, "world scale is non-uniform (%.3g, %.3g, %.3g); "
                                    "collision shapes will not match" % tuple(lengths))


# ------------------------------------------------------------- materials

DEFAULT_SHADING_GROUPS = {"initialShadingGroup", "initialParticleSE"}


@check("material.unassigned_faces", ERROR, "Faces with no material")
def material_unassigned(scene, settings):
    for mesh in scene.meshes:
        if not mesh.face_vertex_counts or not mesh.unassigned_faces:
            continue
        if len(mesh.unassigned_faces) == len(mesh.face_vertex_counts):
            yield _issue(mesh.path, "mesh has no material assigned")
        else:
            yield _issue(mesh.path, "%s with no material assigned"
                         % _n(len(mesh.unassigned_faces), "face"), "f", mesh.unassigned_faces)


@check("material.default_only", WARNING, "Only the default material")
def material_default_only(scene, settings):
    for mesh in scene.meshes:
        if mesh.shading_groups and set(mesh.shading_groups) <= DEFAULT_SHADING_GROUPS:
            yield _issue(mesh.path, "still uses Maya's default material (lambert1)")


def is_absolute(path: str) -> bool:
    """True for POSIX, drive-letter and UNC paths, whichever OS this runs on."""
    return bool(os.path.isabs(path) or re.match(r"^[A-Za-z]:[\\/]", path) or path.startswith(("//", "\\\\")))


def texture_files(path: str, tiled: bool = False, workspace: str = "") -> list[str]:
    """The files on disk a texture path refers to. Relative paths resolve
    against the Maya project; tiled paths match one file per tile."""
    full = path if is_absolute(path) or not workspace else os.path.join(workspace, path)
    if not tiled:
        return [full] if os.path.isfile(full) else []
    match = re.search(r"<udim>", full, re.IGNORECASE) or re.search(r"(?<!\d)\d{4}(?=\.[^./\\]+$)", full)
    if not match:
        return [full] if os.path.isfile(full) else []
    pattern = glob.escape(full[:match.start()]) + "[0-9]" * 4 + glob.escape(full[match.end():])
    return sorted(glob.glob(pattern))


def _textures(scene):
    seen = set()
    for material in scene.materials:
        for texture in material.textures:
            if texture.node not in seen:
                seen.add(texture.node)
                yield texture


@check("texture.missing", ERROR, "Texture file not found")
def texture_missing(scene, settings):
    for texture in _textures(scene):
        if not texture.path:
            yield _issue(texture.node, "file node has no texture path")
        elif not texture_files(texture.path, texture.tiled, scene.workspace):
            yield _issue(texture.node, "texture not found: %s" % texture.path)


@check("texture.outside_project", WARNING, "Texture outside the project")
def texture_outside_project(scene, settings):
    if not scene.workspace:
        return
    root = os.path.normcase(os.path.normpath(scene.workspace))
    for texture in _textures(scene):
        if not texture.path or not is_absolute(texture.path):
            continue
        path = os.path.normcase(os.path.normpath(texture.path))
        if path != root and not path.startswith(root + os.sep):
            yield _issue(texture.node, "absolute path outside the project, so the export only "
                                       "works on this machine: %s" % texture.path)


# ---------------------------------------------------------------- naming

def strip_namespaces(path: str) -> str:
    return "|".join(part.rsplit(":", 1)[-1] for part in path.split("|"))


@check("name.namespace_clash", ERROR, "Names collide once namespaces are stripped")
def name_namespace_clash(scene, settings):
    groups = defaultdict(list)
    for node in scene.nodes:
        groups[strip_namespaces(node)].append(node)
    for stripped, nodes in sorted(groups.items()):
        nodes = sorted(set(nodes))
        if len(nodes) > 1:
            for node in nodes:
                yield _issue(node, "becomes %s in USD, the same prim as %s"
                             % (stripped.replace("|", "/"), ", ".join(n for n in nodes if n != node)))


# ---------------------------------------------------------------- joints

@check("joint.rotate_axis", WARNING, "Joint uses Rotate Axis")
def joint_rotate_axis(scene, settings):
    for joint in scene.joints:
        if any(abs(a) > 1e-3 for a in joint.rotate_axis):
            yield _issue(joint.path, "Rotate Axis is (%.3g, %.3g, %.3g); USD stores one matrix per joint, "
                                     "so this is baked in and the joint's axes change in other tools"
                         % tuple(joint.rotate_axis))


def _is_unit_scale(scale: list[float], tolerance: float) -> bool:
    return all(abs(s - 1.0) <= tolerance for s in scale)


@check("joint.segment_scale", ERROR, "Segment Scale Compensate under a scaled joint")
def joint_segment_scale(scene, settings):
    by_path = {j.path: j for j in scene.joints}
    for joint in scene.joints:
        parent = by_path.get(joint.parent or "")
        if parent and joint.segment_scale_compensate and not _is_unit_scale(parent.scale, settings.scale_tolerance):
            yield _issue(joint.path, "Segment Scale Compensate is on and the parent joint is scaled "
                                     "(%.3g, %.3g, %.3g); USD has no equivalent, so this joint and its "
                                     "children will change size" % tuple(parent.scale))


@check("joint.scale", WARNING, "Scaled joint")
def joint_scale(scene, settings):
    for joint in scene.joints:
        if not _is_unit_scale(joint.scale, settings.scale_tolerance):
            yield _issue(joint.path, "joint scale is (%.3g, %.3g, %.3g), not 1" % tuple(joint.scale))


def aim_axis(offset: list[float], tolerance_degrees: float) -> Optional[str]:
    """Which local axis a bone runs along, given the child's offset in the
    parent joint's space: "x", "y" or "z". None if it leans off every axis
    by more than the tolerance."""
    length = _length(offset)
    if length < 1e-9:
        return None
    components = [abs(c) / length for c in offset]
    best = max(range(3), key=lambda i: components[i])
    if components[best] < math.cos(math.radians(tolerance_degrees)):
        return None
    return "xyz"[best]


@check("joint.orientation", WARNING, "Joint not oriented along its bone")
def joint_orientation(scene, settings):
    children = defaultdict(list)
    for joint in scene.joints:
        if joint.parent:
            children[joint.parent].append(joint)
    axes = {}
    for joint in scene.joints:
        kids = [k for k in children.get(joint.path, []) if _length(k.translate) > 1e-9]
        if len(kids) != 1:
            continue       # end joints and branch points have no single bone direction
        axis = aim_axis(kids[0].translate, settings.joint_angle_tolerance)
        if axis is None:
            yield _issue(joint.path, "no local axis points down the bone; tools that derive bone "
                                     "direction from the joint's axes will orient it differently")
        else:
            axes[joint.path] = axis
    if axes:
        usual = Counter(axes.values()).most_common(1)[0][0]
        for path, axis in sorted(axes.items()):
            if axis != usual:
                yield _issue(path, "bone runs along %s, the rest of the skeleton uses %s"
                             % (axis.upper(), usual.upper()))
