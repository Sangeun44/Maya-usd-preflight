"""The Maya half, run inside real Maya (mayapy).

The example scenes plant one known problem per object. These tests check that
reading the scene finds exactly those problems, on those nodes, and nothing
else; that the plug-in command works; and that a clean scene exports to a USD
file that matches it.
"""
import json
import os

import pytest
from maya import cmds

import make_scenes
from usd_preflight.checks import run_checks
from usd_preflight.collect import collect


def pairs(report):
    return sorted({(i.check, i.node) for i in report.issues})


@pytest.fixture
def project(tmp_path):
    return str(tmp_path / "project")


@pytest.fixture
def broken(project, tmp_path):
    make_scenes.build_broken(project, str(tmp_path / "elsewhere"))


def test_module_file_put_the_package_on_the_path():
    import usd_preflight
    scripts = os.path.join(os.path.dirname(os.path.abspath(make_scenes.__file__)), "..", "scripts")
    assert os.path.samefile(os.path.dirname(os.path.dirname(usd_preflight.__file__)), scripts)


def test_clean_scene_has_no_issues(project):
    make_scenes.build_clean(project)
    scene = collect()
    assert sorted(m.path for m in scene.meshes) == ["|props|crate", "|props|lid"]
    assert len(scene.joints) == 3
    assert os.path.samefile(scene.workspace, project)
    # Maya turns the relative path it was given into an absolute one, since the file exists.
    assert os.path.samefile(scene.materials[0].textures[0].path,
                            os.path.join(project, "sourceimages", "crate_albedo.png"))
    report = run_checks(scene)
    assert report.issues == [], report.format_text()


def test_broken_scene_reports_exactly_the_planted_problems(broken):
    report = run_checks(collect())
    assert pairs(report) == sorted([
        ("joint.orientation", "|arm_root"),
        ("joint.rotate_axis", "|arm_root|arm_mid"),
        ("joint.scale", "|arm_root"),
        ("joint.segment_scale", "|arm_root|arm_mid"),
        ("material.default_only", "|props|mirrored"),
        ("material.unassigned_faces", "|props|crate"),
        ("mesh.missing_uvs", "|props|barrel"),
        ("mesh.missing_uvs", "|props|tee"),
        ("mesh.negative_scale", "|props|mirrored"),
        ("mesh.ngons", "|props|barrel"),
        ("mesh.nonmanifold", "|props|tee"),
        ("mesh.nonuniform_scale", "|props|squashed"),
        ("mesh.zero_area_faces", "|props|sliver"),
        ("name.namespace_clash", "|props|crate"),
        ("name.namespace_clash", "|props|ref:crate"),
        ("texture.missing", "wood_albedo"),
        ("texture.outside_project", "paint_albedo"),
    ]), report.format_text()


def test_issues_point_at_components_maya_can_select(broken):
    by_check = {(i.check, i.node): i for i in run_checks(collect()).issues}
    assert by_check[("material.unassigned_faces", "|props|crate")].indices == [0]
    assert by_check[("mesh.zero_area_faces", "|props|sliver")].indices == [1]
    assert len(by_check[("mesh.ngons", "|props|barrel")].indices) == 2
    edge = by_check[("mesh.nonmanifold", "|props|tee")]
    assert edge.component == "e" and len(edge.indices) == 1
    for issue in by_check.values():
        targets = issue.selection()
        if issue.node:
            cmds.select(targets, replace=True)          # raises if Maya cannot resolve them
            assert cmds.ls(selection=True)


def test_mesh_with_no_material_at_all(project):
    cmds.file(new=True, force=True)
    bare = cmds.polyCube(name="bare")[0]
    cmds.sets(bare, edit=True, remove="initialShadingGroup")
    mesh = collect().meshes[0]
    assert mesh.unassigned_faces == list(range(6)) and mesh.shading_groups == []
    issues = [i for i in run_checks(collect()).issues if i.check == "material.unassigned_faces"]
    assert [i.message for i in issues] == ["mesh has no material assigned"]


def test_selection_scope(broken):
    cmds.select("|props|barrel", replace=True)
    scene = collect(selection=True)
    assert [m.path for m in scene.meshes] == ["|props|barrel"]
    assert scene.joints == []
    cmds.select("|arm_root", replace=True)
    scene = collect(selection=True)
    assert scene.meshes == [] and len(scene.joints) == 3
    cmds.select(clear=True)
    assert collect(selection=True).meshes == []


def test_oriented_joints_pass(project):
    """The same diagonal chain as the broken scene, once Orient Joint has been run."""
    cmds.file(new=True, force=True)
    root = cmds.joint(name="arm_root", position=(0, 100, 0))
    cmds.joint(name="arm_mid", position=(30, 130, 0))
    cmds.joint(name="arm_end", position=(60, 130, 0))
    assert [i.check for i in run_checks(collect()).issues] == ["joint.orientation"]
    cmds.joint(root, edit=True, orientJoint="xyz", secondaryAxisOrient="yup", children=True)
    assert run_checks(collect()).issues == []


def test_lamina_faces(project):
    """Extrude with no offset, then merge vertices: the usual way these appear."""
    cmds.file(new=True, force=True)
    plane = cmds.polyPlane(name="stacked", subdivisionsX=1, subdivisionsY=1)[0]
    cmds.polyExtrudeFacet(plane + ".f[0]", localTranslateZ=0)
    cmds.polyMergeVertex(plane, distance=0.001)
    cmds.delete(plane, constructionHistory=True)
    if not cmds.polyInfo(plane, laminaFaces=True):
        pytest.skip("this Maya version cleaned up the stacked faces")
    report = run_checks(collect())
    assert ("mesh.lamina_faces", "|stacked") in pairs(report), report.format_text()


def test_plugin_command(broken, tmp_path):
    cmds.loadPlugin("usdPreflight.py")
    try:
        assert cmds.pluginInfo("usdPreflight", query=True, version=True) == "0.1.0"
        expected = run_checks(collect())
        assert cmds.usdPreflight() == [len(expected.errors), len(expected.warnings)]

        report_path = tmp_path / "report.json"
        cmds.usdPreflight(report=str(report_path))
        data = json.loads(report_path.read_text())
        assert data["up_axis"] == "y"
        assert sorted({(i["check"], i["node"]) for i in data["issues"]}) == pairs(expected)

        cmds.select("|props|squashed", replace=True)
        assert cmds.usdPreflight(selection=True) == [0, 1]
        profile = tmp_path / "strict.json"
        profile.write_text(json.dumps({"severity": {"mesh.nonuniform_scale": "error"}}))
        assert cmds.usdPreflight(selection=True, profile=str(profile)) == [1, 0]
    finally:
        cmds.unloadPlugin("usdPreflight")
    assert not cmds.pluginInfo("usdPreflight", query=True, loaded=True)


@pytest.fixture
def maya_usd():
    try:
        cmds.loadPlugin("mayaUsdPlugin", quiet=True)
    except RuntimeError as error:
        pytest.skip("Maya USD plug-in is not available here: %s" % error)


def test_clean_scene_exports_and_the_file_matches(maya_usd, project, tmp_path):
    from pxr import Usd, UsdGeom
    from usd_preflight.run import preflight

    make_scenes.build_clean(project)
    target = str(tmp_path / "crate.usda")
    report = preflight(export_path=target)
    assert report.exported == target and os.path.isfile(target)
    assert report.issues == [], report.format_text()

    stage = Usd.Stage.Open(target)
    meshes = [p for p in stage.Traverse() if p.IsA(UsdGeom.Mesh)]
    assert sorted(p.GetName() for p in meshes) == ["crate", "lid"]
    # Polygons, not subdivision surfaces.
    assert all(UsdGeom.Mesh(p).GetSubdivisionSchemeAttr().Get() == "none" for p in meshes)


def test_export_check_catches_a_scene_changed_after_the_snapshot(maya_usd, project, tmp_path):
    """Stand-in for an exporter bug: the file no longer matches what was checked."""
    from usd_preflight.export import export

    make_scenes.build_clean(project)
    snapshot = collect()
    cmds.move(500, 0, 0, "|props|crate", relative=True)
    issues = export(str(tmp_path / "moved.usda"), scene=snapshot)
    assert "export.bounds" in [i.check for i in issues]


def test_broken_scene_is_not_exported_unless_forced(maya_usd, broken, tmp_path):
    from usd_preflight.run import preflight

    target = str(tmp_path / "broken.usda")
    report = preflight(export_path=target)
    assert not report.exported and not os.path.exists(target)
