"""Read the live Maya scene into a `model.Scene` snapshot.

This is the only place that asks Maya about geometry, shading and joints.
Mesh data comes from the Python API 2.0 (iterators and MFnMesh); the rest
from maya.cmds.
"""
from __future__ import annotations

import re

import maya.api.OpenMaya as om
from maya import cmds

from .model import Joint, Material, Mesh, Scene, Texture, ancestors

_INDEX = re.compile(r"\[(\d+)\]$")


def collect(selection: bool = False) -> Scene:
    """Snapshot the whole scene, or only what is under the current selection."""
    shapes, joints = _find(selection)
    scene = Scene(
        file=cmds.file(query=True, sceneName=True) or "",
        up_axis=cmds.upAxis(query=True, axis=True),
        linear_unit=cmds.currentUnit(query=True, linear=True),
        workspace=cmds.workspace(query=True, rootDirectory=True) or "",
    )
    scene.meshes = [_mesh(shape) for shape in shapes]
    scene.joints = [_joint(joint) for joint in joints]

    groups = []
    for mesh in scene.meshes:
        for group in mesh.shading_groups:
            if group not in groups:
                groups.append(group)
    scene.materials = [_material(group) for group in groups]

    nodes = []
    for path in [m.path for m in scene.meshes] + [j.path for j in scene.joints]:
        nodes.extend(ancestors(path))
    scene.nodes = sorted(set(nodes))
    return scene


def _find(selection: bool):
    if not selection:
        shapes = cmds.ls(type="mesh", long=True, noIntermediate=True, allPaths=True) or []
        joints = cmds.ls(type="joint", long=True) or []
        return _unique(shapes), _unique(joints)
    roots = cmds.ls(selection=True, long=True, objectsOnly=True) or []
    if not roots:
        return [], []
    below = cmds.listRelatives(roots, allDescendents=True, fullPath=True) or []
    everything = _unique(roots + below)
    shapes = cmds.ls(everything, type="mesh", long=True, noIntermediate=True) or []
    joints = cmds.ls(everything, type="joint", long=True) or []
    return _unique(shapes), _unique(joints)


def _unique(items):
    seen = set()
    return [i for i in items if not (i in seen or seen.add(i))]


def _dag_path(name: str) -> om.MDagPath:
    selection = om.MSelectionList()
    selection.add(name)
    return selection.getDagPath(0)


def _indices(components) -> list[int]:
    """`['pCube1.e[3:5]']` -> [3, 4, 5]."""
    if not components:
        return []
    flat = cmds.ls(components, flatten=True) or []
    return sorted(int(m.group(1)) for m in (_INDEX.search(c) for c in flat) if m)


def _mesh(shape: str) -> Mesh:
    dag = _dag_path(shape)
    fn = om.MFnMesh(dag)
    transform = om.MDagPath(dag)
    transform.pop()
    mesh = Mesh(path=transform.fullPathName(), shape=dag.fullPathName())

    faces = om.MItMeshPolygon(dag)
    while not faces.isDone():
        mesh.face_vertex_counts.append(faces.polygonVertexCount())
        mesh.face_areas.append(faces.getArea())
        if not faces.hasUVs():
            mesh.faces_without_uvs.append(faces.index())
        faces.next()

    mesh.nonmanifold_edges = _indices(cmds.polyInfo(shape, nonManifoldEdges=True))
    mesh.nonmanifold_vertices = _indices(cmds.polyInfo(shape, nonManifoldVertices=True))
    mesh.lamina_faces = _indices(cmds.polyInfo(shape, laminaFaces=True))

    # One entry per face: an index into `shaders`, or -1 for a face with none.
    try:
        shaders, face_shader = fn.getConnectedShaders(dag.instanceNumber())
    except RuntimeError:
        shaders, face_shader = [], [-1] * fn.numPolygons
    mesh.shading_groups = [om.MFnDependencyNode(s).name() for s in shaders]
    mesh.unassigned_faces = [i for i, index in enumerate(face_shader) if index < 0]

    matrix = dag.inclusiveMatrix()
    mesh.world_matrix = [matrix.getElement(row, column) for row in range(4) for column in range(4)]
    box = om.MFnDagNode(dag).boundingBox
    mesh.bbox_min = [box.min.x, box.min.y, box.min.z]
    mesh.bbox_max = [box.max.x, box.max.y, box.max.z]
    mesh.visible = dag.isVisible()
    mesh.skinned = bool(cmds.ls(cmds.listHistory(shape) or [], type="skinCluster"))
    return mesh


def _material(shading_group: str) -> Material:
    shaders = cmds.listConnections(shading_group + ".surfaceShader", source=True, destination=False) or []
    material = Material(shading_group=shading_group, surface_shader=shaders[0] if shaders else None)
    if shaders:
        for node in _unique(cmds.ls(cmds.listHistory(shaders[0]) or [], type="file") or []):
            material.textures.append(Texture(
                node=node,
                path=cmds.getAttr(node + ".fileTextureName") or "",
                tiled=cmds.getAttr(node + ".uvTilingMode") != 0,
            ))
    return material


def _joint(path: str) -> Joint:
    parents = cmds.listRelatives(path, parent=True, fullPath=True) or []
    parent = parents[0] if parents and cmds.nodeType(parents[0]) == "joint" else None
    return Joint(
        path=path,
        parent=parent,
        translate=list(cmds.getAttr(path + ".translate")[0]),
        rotate_axis=list(cmds.getAttr(path + ".rotateAxis")[0]),
        scale=list(cmds.getAttr(path + ".scale")[0]),
        segment_scale_compensate=bool(cmds.getAttr(path + ".segmentScaleCompensate")),
    )
