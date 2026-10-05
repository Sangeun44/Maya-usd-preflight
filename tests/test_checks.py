"""The checks, run on hand-built snapshots. No Maya needed."""
import json
import math

import pytest

from usd_preflight.__main__ import main as cli
from usd_preflight.checks import CHECKS, Settings, aim_axis, run_checks, strip_namespaces, texture_files
from usd_preflight.model import IDENTITY, Joint, Material, Mesh, Scene, Texture, ancestors
from usd_preflight.report import ERROR, WARNING


def cube(path="|props|crate", **changes):
    """A healthy six-quad mesh; pass fields to break it."""
    mesh = Mesh(path=path, shape=path + "|" + path.rsplit("|", 1)[-1] + "Shape",
                face_vertex_counts=[4] * 6, face_areas=[100.0] * 6,
                shading_groups=["woodSG"], bbox_min=[-5, -5, -5], bbox_max=[5, 5, 5])
    for name, value in changes.items():
        setattr(mesh, name, value)
    return mesh


def scene_of(*meshes, joints=(), materials=(), **changes):
    scene = Scene(file="/show/crate.ma", meshes=list(meshes), joints=list(joints),
                  materials=list(materials))
    nodes = set()
    for item in scene.meshes + scene.joints:
        nodes.update(ancestors(item.path))
    scene.nodes = sorted(nodes)
    for name, value in changes.items():
        setattr(scene, name, value)
    return scene


def found(scene, settings=None):
    """{check id: [issues]} for a scene."""
    result = {}
    for issue in run_checks(scene, settings).issues:
        result.setdefault(issue.check, []).append(issue)
    return result


def scaled(sx, sy, sz):
    matrix = list(IDENTITY)
    matrix[0], matrix[5], matrix[10] = sx, sy, sz
    return matrix


def test_clean_scene_has_no_issues():
    chain = [Joint("|root"), Joint("|root|mid", parent="|root", translate=[10, 0, 0]),
             Joint("|root|mid|end", parent="|root|mid", translate=[10, 0, 0])]
    report = run_checks(scene_of(cube(), cube("|props|lid"), joints=chain))
    assert report.issues == []
    assert report.ok


def test_empty_scene():
    assert "scene.empty" in found(Scene())


def test_every_check_has_a_unique_id_and_valid_severity():
    ids = [c.id for c in CHECKS]
    assert len(ids) == len(set(ids))
    assert {c.severity for c in CHECKS} <= {ERROR, WARNING}


# ----------------------------------------------------------------- mesh

def test_nonmanifold_edges_and_vertices_are_selectable():
    issues = found(scene_of(cube(nonmanifold_edges=[3, 7], nonmanifold_vertices=[2])))["mesh.nonmanifold"]
    assert [i.severity for i in issues] == [ERROR, ERROR]
    assert issues[0].selection() == ["|props|crate.e[3]", "|props|crate.e[7]"]
    assert issues[1].selection() == ["|props|crate.vtx[2]"]
    assert issues[0].message.startswith("2 non-manifold edges")
    assert issues[1].message == "1 non-manifold vertex"


def test_lamina_faces():
    assert found(scene_of(cube(lamina_faces=[0, 1])))["mesh.lamina_faces"][0].indices == [0, 1]


def test_zero_area_faces_use_the_tolerance():
    mesh = cube(face_areas=[100.0, 0.0, 1e-9, 1e-3, 100.0, 100.0])
    assert found(scene_of(mesh))["mesh.zero_area_faces"][0].indices == [1, 2]
    loose = Settings(zero_area_tolerance=0.01)
    assert found(scene_of(mesh), loose)["mesh.zero_area_faces"][0].indices == [1, 2, 3]


def test_ngons_respect_max_sides():
    mesh = cube(face_vertex_counts=[4, 4, 5, 8, 3, 4])
    assert found(scene_of(mesh))["mesh.ngons"][0].indices == [2, 3]
    assert found(scene_of(mesh), Settings(max_face_sides=3))["mesh.ngons"][0].indices == [0, 1, 2, 3, 5]
    assert "mesh.ngons" not in found(scene_of(mesh), Settings(max_face_sides=8))


def test_missing_uvs_whole_mesh_or_some_faces():
    whole = found(scene_of(cube(faces_without_uvs=list(range(6)))))["mesh.missing_uvs"][0]
    assert whole.message == "mesh has no UVs" and whole.selection() == ["|props|crate"]
    some = found(scene_of(cube(faces_without_uvs=[4])))["mesh.missing_uvs"][0]
    assert some.selection() == ["|props|crate.f[4]"]


def test_empty_mesh_reports_only_that():
    result = found(scene_of(cube(face_vertex_counts=[], face_areas=[])))
    assert set(result) == {"mesh.empty"}


def test_negative_scale_is_found_from_the_world_matrix():
    assert "mesh.negative_scale" in found(scene_of(cube(world_matrix=scaled(-1, 1, 1))))
    # Two negative axes are a rotation, not a mirror.
    assert "mesh.negative_scale" not in found(scene_of(cube(world_matrix=scaled(-1, -1, 1))))


def test_nonuniform_scale_and_shear():
    assert "mesh.nonuniform_scale" not in found(scene_of(cube(world_matrix=scaled(3, 3, 3))))
    squashed = found(scene_of(cube(world_matrix=scaled(1, 0.5, 1))))["mesh.nonuniform_scale"][0]
    assert "non-uniform" in squashed.message
    sheared = list(IDENTITY)
    sheared[4] = 0.3            # the Y axis leans towards X
    assert "sheared" in found(scene_of(cube(world_matrix=sheared)))["mesh.nonuniform_scale"][0].message


def test_rotation_is_not_mistaken_for_scale():
    c, s = math.cos(0.7), math.sin(0.7)
    rotated = [c, s, 0, 0, -s, c, 0, 0, 0, 0, 1, 0, 5, 6, 7, 1]
    assert found(scene_of(cube(world_matrix=rotated))) == {}


# ------------------------------------------------------------- materials

def test_unassigned_faces():
    some = found(scene_of(cube(unassigned_faces=[0])))["material.unassigned_faces"][0]
    assert some.selection() == ["|props|crate.f[0]"]
    whole = found(scene_of(cube(unassigned_faces=list(range(6)), shading_groups=[])))
    assert whole["material.unassigned_faces"][0].message == "mesh has no material assigned"
    assert "material.default_only" not in whole


def test_default_material_only():
    assert "material.default_only" in found(scene_of(cube(shading_groups=["initialShadingGroup"])))
    mixed = cube(shading_groups=["initialShadingGroup", "woodSG"])
    assert "material.default_only" not in found(scene_of(mixed))


def textured(path, tiled=False):
    return Material("woodSG", "wood", [Texture("wood_albedo", path, tiled)])


def test_missing_texture(tmp_path):
    (tmp_path / "sourceimages").mkdir()
    (tmp_path / "sourceimages" / "wood.png").write_bytes(b"png")
    present = scene_of(cube(), materials=[textured("sourceimages/wood.png")], workspace=str(tmp_path))
    assert found(present) == {}
    missing = scene_of(cube(), materials=[textured("sourceimages/gone.png")], workspace=str(tmp_path))
    issue = found(missing)["texture.missing"][0]
    assert issue.node == "wood_albedo" and "gone.png" in issue.message
    assert "texture.missing" in found(scene_of(cube(), materials=[textured("")]))


def test_a_texture_shared_by_two_materials_is_reported_once(tmp_path):
    shared = Texture("albedo", "sourceimages/gone.png")
    scene = scene_of(cube(), materials=[Material("aSG", "a", [shared]), Material("bSG", "b", [shared])],
                     workspace=str(tmp_path))
    assert len(found(scene)["texture.missing"]) == 1


def test_udim_textures_match_any_tile(tmp_path):
    for tile in (1001, 1002):
        (tmp_path / ("wood.%d.exr" % tile)).write_bytes(b"exr")
    assert len(texture_files("wood.<UDIM>.exr", True, str(tmp_path))) == 2
    assert len(texture_files("wood.1001.exr", True, str(tmp_path))) == 2      # how Maya stores it
    assert texture_files("wood.1001.exr", False, str(tmp_path)) == [str(tmp_path / "wood.1001.exr")]
    assert texture_files("stone.<UDIM>.exr", True, str(tmp_path)) == []


def test_texture_outside_project(tmp_path):
    project, elsewhere = tmp_path / "project", tmp_path / "desktop"
    for folder in (project, elsewhere):
        folder.mkdir()
        (folder / "wood.png").write_bytes(b"png")
    inside = scene_of(cube(), materials=[textured(str(project / "wood.png"))], workspace=str(project))
    assert found(inside) == {}
    outside = scene_of(cube(), materials=[textured(str(elsewhere / "wood.png"))], workspace=str(project))
    assert set(found(outside)) == {"texture.outside_project"}
    # A sibling folder that merely starts with the project's name is still outside.
    lookalike = tmp_path / "project_old"
    lookalike.mkdir()
    (lookalike / "wood.png").write_bytes(b"png")
    near = scene_of(cube(), materials=[textured(str(lookalike / "wood.png"))], workspace=str(project))
    assert "texture.outside_project" in found(near)


# ---------------------------------------------------------------- naming

def test_strip_namespaces():
    assert strip_namespaces("|ref:props|a:b:crate") == "|props|crate"


def test_namespace_clash():
    clash = found(scene_of(cube("|props|crate"), cube("|props|ref:crate")))["name.namespace_clash"]
    assert sorted(i.node for i in clash) == ["|props|crate", "|props|ref:crate"]
    assert "/props/crate" in clash[0].message
    # The same leaf name under different parents is fine in USD.
    assert found(scene_of(cube("|a|crate"), cube("|b|ref:crate"))) == {}


# ---------------------------------------------------------------- joints

def test_aim_axis():
    assert aim_axis([10, 0, 0], 5) == "x"
    assert aim_axis([0, -3, 0], 5) == "y"            # mirrored limbs aim down the negative axis
    assert aim_axis([10, 0.5, 0], 5) == "x"          # 2.9 degrees off
    assert aim_axis([10, 10, 0], 5) is None
    assert aim_axis([0, 0, 0], 5) is None


def test_joint_not_oriented_along_its_bone():
    chain = [Joint("|root"), Joint("|root|mid", parent="|root", translate=[10, 10, 0]),
             Joint("|root|mid|end", parent="|root|mid", translate=[10, 0, 0])]
    issues = found(scene_of(joints=chain))["joint.orientation"]
    assert [i.node for i in issues] == ["|root"]


def test_joint_with_a_different_aim_axis_from_the_rest():
    chain = [Joint("|a"), Joint("|a|b", parent="|a", translate=[10, 0, 0]),
             Joint("|a|b|c", parent="|a|b", translate=[10, 0, 0]),
             Joint("|a|b|c|d", parent="|a|b|c", translate=[0, 10, 0]),
             Joint("|a|b|c|d|e", parent="|a|b|c|d", translate=[-10, 0, 0])]
    issues = found(scene_of(joints=chain))["joint.orientation"]
    assert [i.node for i in issues] == ["|a|b|c"]
    assert "runs along Y" in issues[0].message and "uses X" in issues[0].message


def test_branch_joints_are_not_judged():
    hand = [Joint("|hand")] + [Joint("|hand|f%d" % i, parent="|hand", translate=[3, i, 1]) for i in range(4)]
    assert found(scene_of(joints=hand)) == {}


def test_segment_scale_compensate_under_a_scaled_parent():
    def chain(parent_scale, compensate):
        return [Joint("|root", scale=parent_scale),
                Joint("|root|mid", parent="|root", translate=[10, 0, 0], segment_scale_compensate=compensate)]

    result = found(scene_of(joints=chain([2, 2, 2], True)))
    assert [i.node for i in result["joint.segment_scale"]] == ["|root|mid"]
    assert [i.node for i in result["joint.scale"]] == ["|root"]
    assert "joint.segment_scale" not in found(scene_of(joints=chain([2, 2, 2], False)))
    assert found(scene_of(joints=chain([1, 1, 1], True))) == {}


def test_rotate_axis():
    chain = [Joint("|root", rotate_axis=[30, 0, 0])]
    assert "joint.rotate_axis" in found(scene_of(joints=chain))


# -------------------------------------------------------------- profiles

def test_profile_expectations_disable_and_severity():
    scene = scene_of(cube(face_vertex_counts=[5] * 6, nonmanifold_edges=[1]))
    settings = Settings.from_dict({"up_axis": "z", "linear_unit": "m", "disable": ["mesh.nonmanifold"],
                                   "severity": {"mesh.ngons": "error"}})
    result = found(scene, settings)
    assert set(result) == {"scene.up_axis", "scene.units", "mesh.ngons"}
    assert result["mesh.ngons"][0].severity == ERROR
    assert "Y up" in result["scene.up_axis"][0].message


@pytest.mark.parametrize("profile", [
    {"max_sides": 4},                                # misspelt setting
    {"disable": ["mesh.ngon"]},                      # misspelt check
    {"severity": {"mesh.ngons": "fatal"}},           # not a severity
])
def test_a_profile_with_a_typo_is_rejected(profile):
    with pytest.raises(ValueError):
        Settings.from_dict(profile)


def test_shipped_profile_loads():
    settings = Settings.load("profiles/sim_ready.json")
    assert settings.up_axis == "z" and settings.severity["mesh.ngons"] == ERROR


# ------------------------------------------------------- report and CLI

def test_report_text_and_json():
    report = run_checks(scene_of(cube(nonmanifold_edges=[1], face_vertex_counts=[5] * 6)))
    assert report.summary() == "1 error, 1 warning"
    lines = report.format_text().splitlines()
    assert lines[0] == "crate.ma: 1 error, 1 warning  (Y up, cm)"
    assert lines[1].split()[:2] == ["ERROR", "mesh.nonmanifold"]       # errors first
    data = json.loads(report.to_json())
    assert data["errors"] == 1 and data["issues"][0]["indices"] == [1]


def test_snapshot_round_trips_through_json():
    scene = scene_of(cube(unassigned_faces=[2]), joints=[Joint("|root", scale=[2, 2, 2])],
                     materials=[textured("a.png", tiled=True)])
    again = Scene.from_json(scene.to_json())
    assert again == scene
    # A snapshot from a newer version, with a field this one does not know, still loads.
    data = json.loads(scene.to_json())
    data["meshes"][0]["future_field"] = 1
    assert Scene.from_json(json.dumps(data)).meshes[0].unassigned_faces == [2]


def test_cli_checks_a_saved_snapshot(tmp_path, capsys):
    path = tmp_path / "crate.snapshot.json"
    path.write_text(scene_of(cube(lamina_faces=[0])).to_json())
    assert cli([str(path)]) == 1
    assert "mesh.lamina_faces" in capsys.readouterr().out
    path.write_text(scene_of(cube()).to_json())
    assert cli([str(path)]) == 0
    assert cli(["--list"]) == 0
    assert "joint.segment_scale" in capsys.readouterr().out
