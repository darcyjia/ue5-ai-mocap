"""人像摄影棚关卡（非 World Partition，可当素材关卡模板 / LevelInstance 用）：灰背景墙 + 白地板 + 人像四灯 + 固定曝光。

    studio_build.py [关卡=/Game/Studio/L_Studio] [EV=4.5]

坐标约定：原点 = 打斗中心，机位在 -Y 一侧看向 +Y，背景墙在 +Y。
灯：主光（左前上方大柔光箱）、辅光（右前，约主光 1/4）、两侧身后轮廓光（条形柔光）、背景光（打墙，做中间亮四周暗）。
在编辑器里跑（scripts/tools/ue_remote.py）；关卡已存在就整个重建。"""
import sys

import unreal

EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
LVL = sys.argv[1] if len(sys.argv) > 1 else "/Game/Studio/L_Studio"
EV = float(sys.argv[2]) if len(sys.argv) > 2 else 4.5   # 实测：主光 900cd 在约 4m 处，EV 4.5 时 18% 灰背景正好是中灰
DIR = LVL.rsplit("/", 1)[0]
FACE = unreal.Vector(0, 0, 150)     # 灯对准的高度（胸口到脸）


def material(name, grey, rough):
    path = f"{DIR}/{name}"
    if EAL.does_asset_exist(path):
        return unreal.load_asset(path)
    mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, DIR, unreal.Material, unreal.MaterialFactoryNew())
    c = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -300, 0)
    c.set_editor_property("constant", unreal.LinearColor(grey, grey, grey, 1))
    MEL.connect_material_property(c, "", unreal.MaterialProperty.MP_BASE_COLOR)
    r = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant, -300, 200)
    r.set_editor_property("r", rough)
    MEL.connect_material_property(r, "", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.recompile_material(mat)
    EAL.save_loaded_asset(mat, False)
    return mat


def block(label, loc, scale, mat):
    a = eas.spawn_actor_from_class(unreal.StaticMeshActor, loc, unreal.Rotator(0, 0, 0))
    a.set_actor_label(label)
    a.static_mesh_component.set_static_mesh(unreal.load_asset("/Engine/BasicShapes/Cube"))
    a.static_mesh_component.set_material(0, mat)
    a.set_actor_scale3d(scale)
    return a


def rect(label, loc, target, cd, w, h, shadows=True, barn=0.0):
    rot = unreal.MathLibrary.find_look_at_rotation(loc, target)
    a = eas.spawn_actor_from_class(unreal.RectLight, loc, rot)
    a.set_actor_label(label)
    c = a.get_component_by_class(unreal.RectLightComponent)
    c.set_editor_property("mobility", unreal.ComponentMobility.MOVABLE)
    c.set_editor_property("intensity_units", unreal.LightUnits.CANDELAS)
    c.set_editor_property("intensity", cd)
    c.set_editor_property("source_width", w)
    c.set_editor_property("source_height", h)
    c.set_editor_property("attenuation_radius", 3000.0)
    c.set_editor_property("cast_shadows", shadows)
    c.set_editor_property("use_temperature", True)
    c.set_editor_property("temperature", 5600.0)
    if barn:
        c.set_editor_property("barn_door_angle", barn)
        c.set_editor_property("barn_door_length", 25.0)
    return a


def main():
    unreal.SystemLibrary.collect_garbage()
    if EAL.does_asset_exist(LVL):
        les.load_level("/Engine/Maps/Templates/Template_Default")
        unreal.SystemLibrary.collect_garbage()
        EAL.delete_asset(LVL)
    les.new_level(LVL)
    grey = material("M_StudioGrey", 0.18, 0.9)      # 18% 中灰背景纸
    white = material("M_StudioWhite", 0.8, 0.6)     # 白地板
    block("Floor", unreal.Vector(0, 0, -5), unreal.Vector(30, 30, 0.1), white)                 # 30m×30m，顶面在 z=0
    block("Backdrop", unreal.Vector(0, 700, 500), unreal.Vector(30, 0.1, 10), grey)            # 背景墙 30m 宽 10m 高
    rect("Key", unreal.Vector(-260, -280, 260), FACE, 900.0, 150, 150, True, 60.0)             # 主光：左前上方 45°
    rect("Fill", unreal.Vector(300, -360, 170), FACE, 220.0, 200, 200, False)                  # 辅光：右前，约 1/4，不投影
    rect("RimL", unreal.Vector(-240, 260, 230), FACE, 700.0, 40, 180, True, 40.0)              # 轮廓光：身后两侧条形柔光
    rect("RimR", unreal.Vector(240, 260, 230), FACE, 700.0, 40, 180, True, 40.0)
    rect("Background", unreal.Vector(0, 380, 40), unreal.Vector(0, 700, 250), 500.0, 100, 100, False, 70.0)  # 打墙
    pp = eas.spawn_actor_from_class(unreal.PostProcessVolume, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
    pp.set_actor_label("StudioPost")
    pp.set_editor_property("unbound", True)
    s = pp.settings
    for k, v in (("auto_exposure_method", unreal.AutoExposureMethod.AEM_BASIC),
                 ("auto_exposure_apply_physical_camera_exposure", False),
                 ("auto_exposure_min_brightness", EV), ("auto_exposure_max_brightness", EV),
                 ("auto_exposure_bias", 0.0),
                 ("local_exposure_highlight_contrast_scale", 0.7),
                 ("vignette_intensity", 0.25)):
        s.set_editor_property(k, v)
        s.set_editor_property("override_" + k, True)
    pp.settings = s
    les.save_current_level()
    print(f"摄影棚 {LVL}：灰背景 + 白地板 + 主/辅/双轮廓/背景 五盏灯，固定曝光 EV {EV}")


main()
