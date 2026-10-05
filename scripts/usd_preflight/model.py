"""A neutral snapshot of the parts of a Maya scene that matter for a USD export.

Nothing in this file imports Maya. `collect.py` fills these classes in from a
live scene; `checks.py` reads them. Keeping the two apart means the checks run
(and are tested) anywhere, and a snapshot saved to JSON can be re-checked later
without opening the scene again.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Optional

IDENTITY = [1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0]

# Maya's linear unit names, in metres.
METERS_PER_UNIT = {"mm": 0.001, "cm": 0.01, "m": 1.0, "km": 1000.0,
                   "in": 0.0254, "ft": 0.3048, "yd": 0.9144, "mi": 1609.344}


@dataclass
class Mesh:
    path: str                      # full DAG path of the transform, e.g. |props|crate
    shape: str                     # full DAG path of the mesh shape
    face_vertex_counts: list[int] = field(default_factory=list)
    face_areas: list[float] = field(default_factory=list)   # object space, cm^2
    nonmanifold_edges: list[int] = field(default_factory=list)
    nonmanifold_vertices: list[int] = field(default_factory=list)
    lamina_faces: list[int] = field(default_factory=list)
    faces_without_uvs: list[int] = field(default_factory=list)
    unassigned_faces: list[int] = field(default_factory=list)
    shading_groups: list[str] = field(default_factory=list)
    world_matrix: list[float] = field(default_factory=lambda: list(IDENTITY))
    # Bounding box of the shape in its own space, in cm (Maya's internal unit).
    bbox_min: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    bbox_max: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    visible: bool = True
    skinned: bool = False


@dataclass
class Texture:
    node: str
    path: str
    tiled: bool = False            # UDIM or another tiling mode


@dataclass
class Material:
    shading_group: str
    surface_shader: Optional[str] = None
    textures: list[Texture] = field(default_factory=list)


@dataclass
class Joint:
    path: str
    parent: Optional[str] = None   # full path of the parent joint, if it has one
    translate: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotate_axis: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    scale: list[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])
    segment_scale_compensate: bool = True


@dataclass
class Scene:
    file: str = ""
    up_axis: str = "y"
    linear_unit: str = "cm"
    workspace: str = ""
    meshes: list[Mesh] = field(default_factory=list)
    materials: list[Material] = field(default_factory=list)
    joints: list[Joint] = field(default_factory=list)
    # Every DAG path that would become a prim: the meshes, the joints and
    # all of their ancestors.
    nodes: list[str] = field(default_factory=list)

    def to_json(self, indent: Optional[int] = None) -> str:
        return json.dumps(asdict(self), indent=indent)

    @classmethod
    def from_json(cls, text: str) -> "Scene":
        data = json.loads(text)
        data["meshes"] = [_build(Mesh, m) for m in data.get("meshes", [])]
        data["joints"] = [_build(Joint, j) for j in data.get("joints", [])]
        data["materials"] = [
            _build(Material, dict(m, textures=[_build(Texture, t) for t in m.get("textures", [])]))
            for m in data.get("materials", [])
        ]
        return _build(cls, data)


def _build(cls: Any, data: dict) -> Any:
    """Construct a dataclass, ignoring keys a newer version may have added."""
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in known})


def ancestors(path: str) -> list[str]:
    """`|a|b|c` -> [`|a`, `|a|b`, `|a|b|c`]."""
    parts = [p for p in path.split("|") if p]
    return ["|" + "|".join(parts[: i + 1]) for i in range(len(parts))]
