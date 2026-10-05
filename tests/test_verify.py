"""The export check, run on stages authored here with usd-core. No Maya needed.

Each test writes the stage Maya USD would write for a small snapshot, then
breaks one thing and checks that `verify_stage` notices.
"""
import math

import pytest

pytest.importorskip("pxr")
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade  # noqa: E402

from usd_preflight.model import IDENTITY, Mesh, Scene  # noqa: E402
from usd_preflight.report import ERROR, WARNING  # noqa: E402
from usd_preflight.verify import expected_from_scene, verify_stage  # noqa: E402


def turned(degrees, tx, ty, tz):
    """A Maya world matrix (row vectors): rotate about Y, then translate."""
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return [c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, tx, ty, tz, 1]


def snapshot():
    crate = Mesh("|props|crate", "|props|crate|crateShape", face_vertex_counts=[4] * 6,
                 shading_groups=["woodSG"], bbox_min=[0, 0, 0], bbox_max=[100, 50, 60],
                 world_matrix=turned(30, 100, 25, -40))
    lid = Mesh("|props|lid", "|props|lid|lidShape", face_vertex_counts=[4] * 6,
               shading_groups=["initialShadingGroup"], bbox_min=[-50, -2.5, -30], bbox_max=[50, 2.5, 30],
               world_matrix=[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 52.5, 0, 1])
    return Scene(file="crate.ma", up_axis="y", linear_unit="cm", meshes=[crate, lid])


def write_stage(path, scene, scale=1.0, up_axis="Y", bind=True, skip=(), default_prim=True, edit=None):
    """Author what the exporter would: one Mesh prim per Maya mesh, same
    transform, centimetres. `scale` multiplies the points, as a unit mistake would."""
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageUpAxis(stage, up_axis)
    UsdGeom.SetStageMetersPerUnit(stage, 0.01)
    material = UsdShade.Material.Define(stage, "/Looks/wood")
    for mesh in scene.meshes:
        if mesh.path in skip:
            continue
        prim_path = mesh.path.replace("|", "/")
        prim = UsdGeom.Mesh.Define(stage, prim_path)
        low = [c * scale for c in mesh.bbox_min]
        high = [c * scale for c in mesh.bbox_max]
        prim.CreatePointsAttr([Gf.Vec3f(*low), Gf.Vec3f(*high)])
        prim.CreateExtentAttr([Gf.Vec3f(*low), Gf.Vec3f(*high)])
        # GfMatrix4d uses row vectors too, so Maya's 16 floats go in as they are.
        m = mesh.world_matrix
        prim.AddTransformOp().Set(Gf.Matrix4d(*m))
        if bind and "woodSG" in mesh.shading_groups:
            UsdShade.MaterialBindingAPI.Apply(prim.GetPrim()).Bind(material)
    if default_prim:
        stage.SetDefaultPrim(stage.GetPrimAtPath("/props"))
    if edit:
        edit(stage)
    stage.GetRootLayer().Save()
    return str(path)


def checks(issues):
    return {i.check: i for i in issues}


def test_expected_bounds_are_in_metres_and_world_space():
    scene = Scene(meshes=[Mesh("|a", "|a|aShape", face_vertex_counts=[4],
                               bbox_min=[-1, -1, -1], bbox_max=[1, 1, 1],
                               world_matrix=[2, 0, 0, 0, 0, 2, 0, 0, 0, 0, 2, 0, 100, 0, 0, 1])])
    expected = expected_from_scene(scene)
    assert expected.bounds_min == pytest.approx([0.98, -0.02, -0.02])
    assert expected.bounds_max == pytest.approx([1.02, 0.02, 0.02])
    assert expected.up_axis == "Y" and expected.mesh_count == 1 and expected.meshes_with_material == 0


def test_a_faithful_export_passes(tmp_path):
    scene = snapshot()
    path = write_stage(tmp_path / "crate.usda", scene)
    assert verify_stage(path, expected_from_scene(scene)) == []


def test_metres_per_unit_is_taken_into_account(tmp_path):
    """The same geometry written in metres is still the same geometry."""
    scene = snapshot()

    def to_metres(stage):
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        for prim in stage.Traverse():
            if prim.IsA(UsdGeom.Mesh):
                op = UsdGeom.Xformable(prim).GetOrderedXformOps()[0]
                matrix = Gf.Matrix4d(op.Get())
                matrix.SetTranslateOnly(matrix.ExtractTranslation() * 0.01)
                op.Set(matrix)

    path = write_stage(tmp_path / "crate.usda", scene, scale=0.01, edit=to_metres)
    assert verify_stage(path, expected_from_scene(scene)) == []


def test_a_unit_mistake_fails_the_bounds_check(tmp_path):
    scene = snapshot()
    path = write_stage(tmp_path / "crate.usda", scene, scale=0.01)      # points shrunk, units not updated
    issue = checks(verify_stage(path, expected_from_scene(scene)))["export.bounds"]
    assert issue.severity == ERROR


def test_a_lost_transform_fails_the_bounds_check(tmp_path):
    scene = snapshot()

    def drop_transform(stage):
        UsdGeom.Xformable(stage.GetPrimAtPath("/props/crate")).ClearXformOpOrder()

    path = write_stage(tmp_path / "crate.usda", scene, edit=drop_transform)
    assert checks(verify_stage(path, expected_from_scene(scene)))["export.bounds"].severity == ERROR


def test_bounds_mismatch_is_a_warning_when_the_scene_is_skinned(tmp_path):
    scene = snapshot()
    scene.meshes[0].skinned = True
    path = write_stage(tmp_path / "crate.usda", scene, scale=1.2)
    assert checks(verify_stage(path, expected_from_scene(scene)))["export.bounds"].severity == WARNING


def test_wrong_up_axis(tmp_path):
    scene = snapshot()
    path = write_stage(tmp_path / "crate.usda", scene, up_axis="Z")
    assert "Z up" in checks(verify_stage(path, expected_from_scene(scene)))["export.up_axis"].message


def test_a_missing_mesh(tmp_path):
    scene = snapshot()
    path = write_stage(tmp_path / "crate.usda", scene, skip=["|props|lid"])
    found = checks(verify_stage(path, expected_from_scene(scene)))
    assert "1 meshes" in found["export.mesh_count"].message
    assert "export.bounds" in found


def test_a_lost_material(tmp_path):
    scene = snapshot()
    path = write_stage(tmp_path / "crate.usda", scene, bind=False)
    assert set(checks(verify_stage(path, expected_from_scene(scene)))) == {"export.materials"}


def test_a_material_bound_per_face_counts(tmp_path):
    """Per-face assignments are exported as bindings on GeomSubsets, not on the mesh."""
    scene = snapshot()

    def bind_subset(stage):
        mesh = UsdGeom.Mesh.Get(stage, "/props/crate")
        subset = UsdGeom.Subset.CreateGeomSubset(mesh, "wood", "face", [0, 1, 2], "materialBind")
        UsdShade.MaterialBindingAPI.Apply(subset.GetPrim()).Bind(UsdShade.Material.Get(stage, "/Looks/wood"))

    path = write_stage(tmp_path / "crate.usda", scene, bind=False, edit=bind_subset)
    assert verify_stage(path, expected_from_scene(scene)) == []


def test_hidden_geometry_is_left_out_of_the_bounds_on_both_sides(tmp_path):
    scene = snapshot()
    scene.meshes[1].visible = False

    def hide(stage):
        UsdGeom.Imageable(stage.GetPrimAtPath("/props/lid")).MakeInvisible()

    path = write_stage(tmp_path / "crate.usda", scene, edit=hide)
    assert verify_stage(path, expected_from_scene(scene)) == []


def test_no_default_prim(tmp_path):
    scene = snapshot()
    path = write_stage(tmp_path / "crate.usda", scene, default_prim=False)
    assert set(checks(verify_stage(path, expected_from_scene(scene)))) == {"export.default_prim"}


def test_instanced_meshes_are_counted_once_per_placement(tmp_path):
    scene = snapshot()
    scene.meshes = [scene.meshes[1]]
    scene.meshes[0].path = "|props|lid"
    second = Mesh("|props|lid2", "|props|lid2|lidShape", face_vertex_counts=[4] * 6,
                  shading_groups=["initialShadingGroup"], bbox_min=[-50, -2.5, -30], bbox_max=[50, 2.5, 30],
                  world_matrix=[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 200, 52.5, 0, 1])
    scene.meshes.append(second)

    stage = Usd.Stage.CreateNew(str(tmp_path / "lids.usda"))
    UsdGeom.SetStageUpAxis(stage, "Y")
    UsdGeom.SetStageMetersPerUnit(stage, 0.01)
    proto = stage.CreateClassPrim("/_proto")
    mesh = UsdGeom.Mesh.Define(stage, "/_proto/geo")
    mesh.CreateExtentAttr([Gf.Vec3f(-50, -2.5, -30), Gf.Vec3f(50, 2.5, 30)])
    for name, x in (("lid", 0), ("lid2", 200)):
        xform = UsdGeom.Xform.Define(stage, "/props/" + name)
        xform.AddTranslateOp().Set(Gf.Vec3d(x, 52.5, 0))
        xform.GetPrim().GetReferences().AddInternalReference(Sdf.Path("/_proto"))
        xform.GetPrim().SetInstanceable(True)
    stage.SetDefaultPrim(stage.GetPrimAtPath("/props"))
    stage.GetRootLayer().Save()
    assert proto and verify_stage(str(tmp_path / "lids.usda"), expected_from_scene(scene)) == []


def test_a_file_that_is_not_usd(tmp_path):
    path = tmp_path / "broken.usda"
    path.write_text("this is not a usd file")
    found = checks(verify_stage(str(path), expected_from_scene(snapshot())))
    assert set(found) == {"export.open"} and found["export.open"].severity == ERROR
