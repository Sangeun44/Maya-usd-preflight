"""Build the two example scenes: one clean, one broken on purpose.

    mayapy examples/make_scenes.py examples/scenes

The tests in tests/maya build the same scenes and check that every problem
planted in the broken one is found, and that nothing is reported in the
clean one.
"""
from __future__ import annotations

import os
import struct
import sys
import zlib

import maya.api.OpenMaya as om
from maya import cmds


def write_png(path: str, rgb=(176, 122, 74), size: int = 8) -> str:
    """A small flat-colour PNG, written by hand so the example needs no image library."""
    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    row = b"\x00" + bytes(rgb) * size
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(row * size))
                     + chunk(b"IEND", b""))
    return path


def set_project(directory: str) -> None:
    os.makedirs(os.path.join(directory, "sourceimages"), exist_ok=True)
    cmds.workspace(directory, openWorkspace=True)
    cmds.workspace(saveWorkspace=True)      # writes workspace.mel, which marks the folder as a project


def material(name: str, texture: str = "") -> str:
    """A standardSurface with an optional file texture; returns its shading group."""
    shader = cmds.shadingNode("standardSurface", asShader=True, name=name)
    group = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=name + "SG")
    cmds.connectAttr(shader + ".outColor", group + ".surfaceShader")
    if texture:
        node = cmds.shadingNode("file", asTexture=True, name=name + "_albedo")
        cmds.setAttr(node + ".fileTextureName", texture, type="string")
        cmds.connectAttr(node + ".outColor", shader + ".baseColor")
    return group


def box(name: str, parent: str = "", size=(100.0, 50.0, 60.0), at=(0.0, 25.0, 0.0)) -> str:
    node = cmds.polyCube(name=name, width=size[0], height=size[1], depth=size[2])[0]
    cmds.move(at[0], at[1], at[2], node)
    cmds.delete(node, constructionHistory=True)
    if parent:
        node = cmds.parent(node, parent)[0]
    return cmds.ls(node, long=True)[0]


def build_clean(project: str) -> None:
    cmds.file(new=True, force=True)
    set_project(project)
    write_png(os.path.join(project, "sourceimages", "crate_albedo.png"))
    props = cmds.group(empty=True, name="props")
    crate = box("crate", props)
    lid = box("lid", props, size=(100.0, 5.0, 60.0), at=(0.0, 52.5, 0.0))
    wood = material("wood", "sourceimages/crate_albedo.png")
    cmds.sets(crate, lid, edit=True, forceElement=wood)

    cmds.select(cmds.group(empty=True, name="rig"))
    cmds.joint(name="hinge_root", position=(-50, 50, 0))
    cmds.joint(name="hinge_mid", position=(0, 50, 0))
    cmds.joint(name="hinge_end", position=(50, 50, 0))
    cmds.select(clear=True)


def build_broken(project: str, outside: str) -> None:
    """Everything the checks look for, one object per problem."""
    cmds.file(new=True, force=True)
    set_project(project)
    props = cmds.group(empty=True, name="props")

    # texture.missing: the path points at a file that is not there.
    wood = material("wood", "sourceimages/missing_albedo.png")
    # texture.outside_project: the file exists, but only on this machine.
    paint = material("paint", write_png(os.path.join(outside, "paint_albedo.png"), rgb=(60, 90, 160)))

    # material.unassigned_faces: one face of the crate has no material.
    crate = box("crate", props)
    cmds.sets(crate, edit=True, remove="initialShadingGroup")
    cmds.sets(crate + ".f[1:5]", edit=True, forceElement=wood)

    # name.namespace_clash: ref:crate and crate become the same prim.
    cmds.namespace(add="ref")
    twin = box("ref:crate", props, at=(150.0, 25.0, 0.0))
    cmds.sets(twin, edit=True, forceElement=paint)

    # mesh.nonmanifold: three faces meeting along one edge. No UVs either.
    points = [om.MPoint(*p) for p in ((0, 0, 0), (0, 10, 0), (10, 0, 0), (10, 10, 0),
                                      (-10, 0, 0), (-10, 10, 0), (0, 0, 10), (0, 10, 10))]
    tee = om.MFnMesh().create(points, [4, 4, 4], [0, 2, 3, 1, 0, 1, 5, 4, 0, 6, 7, 1])
    tee = cmds.parent(cmds.rename(om.MFnDagNode(tee).fullPathName(), "tee"), props)[0]
    cmds.sets(tee, edit=True, forceElement=paint)

    # mesh.zero_area_faces: every vertex of one face moved to the same point.
    sliver = cmds.polyPlane(name="sliver", width=20, height=10, subdivisionsX=2, subdivisionsY=1)[0]
    corners = cmds.ls(cmds.polyListComponentConversion(sliver + ".f[1]", toVertex=True), flatten=True)
    for vertex in corners:
        cmds.xform(vertex, worldSpace=True, translation=(5, 0, 0))
    cmds.delete(sliver, constructionHistory=True)
    sliver = cmds.parent(sliver, props)[0]
    cmds.sets(sliver, edit=True, forceElement=paint)

    # mesh.ngons and mesh.missing_uvs: eight-sided caps, UVs deleted.
    barrel = cmds.polyCylinder(name="barrel", radius=20, height=60, subdivisionsX=8,
                               subdivisionsY=1, subdivisionsCaps=0)[0]
    cmds.polyMapDel(barrel + ".f[*]")
    cmds.delete(barrel, constructionHistory=True)
    barrel = cmds.parent(barrel, props)[0]
    cmds.move(-150, 30, 0, barrel)
    cmds.sets(barrel, edit=True, forceElement=paint)

    # mesh.negative_scale, and material.default_only (still on lambert1).
    mirrored = box("mirrored", props, at=(0.0, 25.0, 150.0))
    cmds.setAttr(mirrored + ".scaleX", -1)

    # mesh.nonuniform_scale
    squashed = box("squashed", props, at=(150.0, 25.0, 150.0))
    cmds.setAttr(squashed + ".scale", 1, 0.5, 1, type="double3")
    cmds.sets(squashed, edit=True, forceElement=paint)

    # Joints. The chain runs diagonally but the joints keep world axes, so no
    # axis points down the first bone (joint.orientation). The root is scaled
    # (joint.scale) with Segment Scale Compensate left on below it
    # (joint.segment_scale), and the middle joint uses Rotate Axis (joint.rotate_axis).
    cmds.select(clear=True)
    root = cmds.joint(name="arm_root", position=(0, 100, 0))
    mid = cmds.joint(name="arm_mid", position=(30, 130, 0))
    cmds.joint(name="arm_end", position=(60, 130, 0))
    cmds.setAttr(root + ".scale", 2, 2, 2, type="double3")
    cmds.setAttr(mid + ".rotateAxisX", 30)
    cmds.select(clear=True)


def main(out_dir: str) -> None:
    import maya.standalone
    maya.standalone.initialize(name="python")
    out_dir = os.path.abspath(out_dir)
    for name, build in (("clean_crate", lambda: build_clean(out_dir)),
                        ("broken_crate", lambda: build_broken(out_dir, out_dir + "_elsewhere"))):
        build()
        cmds.file(rename=os.path.join(out_dir, name + ".ma"))
        cmds.file(save=True, type="mayaAscii")
        print("wrote", os.path.join(out_dir, name + ".ma"))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "examples/scenes")
    sys.stdout.flush()
    os._exit(0)
