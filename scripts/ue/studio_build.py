"""摄影棚关卡（非 World Partition，可当素材关卡模板 / LevelInstance 用）：灰背景 + 白地板 + 人像布光 + 固定曝光。

    studio_build.py <关卡> [--preset portrait|drama|hard] [--ev 4.5] [--cyc R,H,缺口起,缺口止] [--cyc-mesh cyc.fbx] [--wash 坎德拉]

例：
    studio_build.py /Game/Studio/L_Studio                                    一面背景墙的人像棚
    studio_build.py /Game/Studio/L_Studio270_Hard --preset hard --cyc 2200,2000,200,290 --cyc-mesh SM_Cyc270_R22H20.fbx --wash 1200

坐标约定：原点 = 打斗中心，角色关卡把它作为 LevelInstance 放在打斗中心、不旋转。
--cyc：环形无缝背景（cyclorama），半径 R、墙高 H（厘米），缺口角度区间（UE 偏航角，度）留给机位永远不看的方向，
       墙脚用 1/4 圆弧过渡到地板（看不到墙角线）。半径/缺口按运镜算：机位都在墙内、任何画面的视线都落在墙或地板上。
--cyc-mesh：用 scripts/blender/make_cyc.py 生成的平滑环形网格（含墙脚圆弧和顶盖）代替方块拼的墙，墙脚不会有棱，仰拍不见黑。
--wash：环形棚墙离人物远，主光照不到，用几盏朝外的大柔光把墙洗成暗灰（不是纯黑）。
预设：portrait 人像（主 900 / 辅 220 / 轮廓 700 / 背景 500，EV 4.5）
      drama    戏剧（辅 60 / 轮廓 1600 / 背景 180）
      hard     硬调（主光正侧 90° 1200 / 无辅光 / 轮廓后移 3000 / 无背景光，EV 4.8）
在编辑器里跑（scripts/tools/ue_remote.py）；关卡已存在就清空后就地重建（引用它的角色关卡不受影响）。"""
import math
import sys

import unreal

EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
FACE = unreal.Vector(0, 0, 150)     # 灯对准的高度（胸口到脸）
V = unreal.Vector

# 标签: (位置, 强度 cd, 宽, 高, 投影, 挡光板角度)；强度 0 = 不放这盏灯
PRESETS = {
    "portrait": dict(ev=4.5, lights={
        "Key": (V(-260, -280, 260), 900.0, 150, 150, True, 60.0),        # 主光：左前上方 45°
        "Fill": (V(300, -360, 170), 220.0, 200, 200, False, 0.0),        # 辅光：右前，约 1/4
        "RimL": (V(-240, 260, 230), 700.0, 40, 180, True, 40.0),         # 轮廓光：身后两侧条形柔光
        "RimR": (V(240, 260, 230), 700.0, 40, 180, True, 40.0),
        "Background": (V(0, 380, 40), 500.0, 100, 100, False, 70.0)}),   # 打背景墙
    "drama": dict(ev=4.5, lights={
        "Key": (V(-260, -280, 260), 900.0, 150, 150, True, 60.0),
        "Fill": (V(300, -360, 170), 60.0, 200, 200, False, 0.0),
        "RimL": (V(-240, 260, 230), 1600.0, 40, 180, True, 40.0),
        "RimR": (V(240, 260, 230), 1600.0, 40, 180, True, 40.0),
        "Background": (V(0, 380, 40), 180.0, 100, 100, False, 70.0)}),
    "hard": dict(ev=4.8, lights={
        "Key": (V(-380, -20, 240), 1200.0, 120, 120, True, 80.0),        # 正侧 90°，挡光板收窄
        "RimL": (V(-200, 380, 260), 3000.0, 30, 200, True, 45.0),        # 轮廓光后移、加强
        "RimR": (V(200, 380, 260), 3000.0, 30, 200, True, 45.0)}),
}


def args():
    a = sys.argv[1:]
    o = {"level": a[0] if a and not a[0].startswith("--") else "/Game/Studio/L_Studio",
         "preset": "portrait", "ev": None, "cyc": None, "cyc_mesh": None, "wash": 0.0}
    for i, x in enumerate(a):
        if x == "--preset":
            o["preset"] = a[i + 1]
        elif x == "--ev":
            o["ev"] = float(a[i + 1])
        elif x == "--cyc":
            o["cyc"] = [float(v) for v in a[i + 1].split(",")]
        elif x == "--cyc-mesh":
            o["cyc_mesh"] = a[i + 1]
        elif x == "--wash":
            o["wash"] = float(a[i + 1])
    return o


def material(d, name, grey, rough, two_sided=False):
    path = f"{d}/{name}"
    if EAL.does_asset_exist(path):
        return unreal.load_asset(path)
    mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, d, unreal.Material, unreal.MaterialFactoryNew())
    mat.set_editor_property("two_sided", two_sided)
    c = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -300, 0)
    c.set_editor_property("constant", unreal.LinearColor(grey, grey, grey, 1))
    MEL.connect_material_property(c, "", unreal.MaterialProperty.MP_BASE_COLOR)
    r = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant, -300, 200)
    r.set_editor_property("r", rough)
    MEL.connect_material_property(r, "", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.recompile_material(mat)
    EAL.save_loaded_asset(mat, False)
    return mat


def block(label, loc, scale, mat, rot=None):
    a = eas.spawn_actor_from_class(unreal.StaticMeshActor, loc, rot or unreal.Rotator(0, 0, 0))
    a.set_actor_label(label)
    a.static_mesh_component.set_static_mesh(unreal.load_asset("/Engine/BasicShapes/Cube"))
    a.static_mesh_component.set_material(0, mat)
    a.set_actor_scale3d(scale)
    return a


def rect(label, loc, target, cd, w, h, shadows=True, barn=0.0, radius=3000.0):
    a = eas.spawn_actor_from_class(unreal.RectLight, loc, unreal.MathLibrary.find_look_at_rotation(loc, target))
    a.set_actor_label(label)
    c = a.get_component_by_class(unreal.RectLightComponent)
    c.set_editor_property("mobility", unreal.ComponentMobility.MOVABLE)
    c.set_editor_property("intensity_units", unreal.LightUnits.CANDELAS)
    c.set_editor_property("intensity", cd)
    c.set_editor_property("source_width", float(w))
    c.set_editor_property("source_height", float(h))
    c.set_editor_property("attenuation_radius", radius)
    c.set_editor_property("cast_shadows", shadows)
    c.set_editor_property("use_temperature", True)
    c.set_editor_property("temperature", 5600.0)
    if barn:
        c.set_editor_property("barn_door_angle", barn)
        c.set_editor_property("barn_door_length", 30.0)
    return a


def cyclorama(R, H, g0, g1, grey, cove=300.0, seg=5.0, steps=6):
    """270° 之类的环形墙：竖直墙段 + 墙脚 1/4 圆弧过渡段，每段是一块薄方块，朝向圆心。"""
    span = (g0 - g1) % 360 or 360            # 从缺口止到缺口起（绕过缺口）的角度
    n = int(math.ceil(span / seg))
    step = span / n
    for i in range(n):
        a = math.radians(g1 + (i + 0.5) * step)
        ca, sa = math.cos(a), math.sin(a)
        tangent = V(-sa, ca, 0)
        # 竖直部分：z 从 cove 到 H
        normal = V(-ca, -sa, 0)
        w = 2 * R * math.sin(math.radians(step) / 2) * 1.08
        block(f"Cyc_{i:02d}", V(R * ca, R * sa, (cove + H) / 2), V(w / 100, 0.1, (H - cove) / 100), grey,
              unreal.MathLibrary.make_rot_from_xy(tangent, normal))
        # 墙脚圆弧：圆心在 (R-cove, z=cove)
        for k in range(steps):
            phi = (k + 0.5) / steps * math.pi / 2          # 0 = 地板方向，90° = 墙方向
            rr = R - cove + cove * math.sin(phi)
            z = cove - cove * math.cos(phi)
            nrm = V(-ca * math.sin(phi), -sa * math.sin(phi), math.cos(phi))
            wk = 2 * rr * math.sin(math.radians(step) / 2) * 1.08
            hk = cove * (math.pi / 2) / steps * 1.15
            block(f"Cove_{i:02d}_{k}", V(rr * ca, rr * sa, z), V(wk / 100, 0.1, hk / 100), grey,
                  unreal.MathLibrary.make_rot_from_xy(tangent, nrm))


def import_mesh(fbx, d):
    name = fbx.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    t = unreal.AssetImportTask()
    ui = unreal.FbxImportUI()
    ui.set_editor_property("import_mesh", True)
    ui.set_editor_property("import_as_skeletal", False)
    ui.set_editor_property("import_materials", False)
    ui.set_editor_property("import_textures", False)
    ui.static_mesh_import_data.set_editor_property("combine_meshes", True)
    for k, v in dict(filename=fbx, destination_path=d, destination_name=name, automated=True, save=True,
                     replace_existing=True, options=ui).items():
        t.set_editor_property(k, v)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([t])
    return unreal.load_asset(f"{d}/{name}")


def main():
    o = args()
    lvl, p = o["level"], PRESETS[o["preset"]]
    ev = o["ev"] if o["ev"] is not None else p["ev"]
    d = lvl.rsplit("/", 1)[0]
    unreal.SystemLibrary.collect_garbage()
    if EAL.does_asset_exist(lvl):          # 就地重建：关卡可能正被角色关卡的 LevelInstance 引用，删不掉
        les.load_level(lvl)
        for a in eas.get_all_level_actors():
            if not isinstance(a, unreal.WorldSettings) and a.get_class().get_name() != "Brush":   # 体积（如后期盒子）也是 Brush 子类，要删
                eas.destroy_actor(a)
    else:
        les.new_level(lvl)
    grey = material(d, "M_StudioGrey", 0.18, 0.9)      # 18% 中灰背景纸
    white = material(d, "M_StudioWhite", 0.8, 0.6)     # 白地板
    if o["cyc"]:
        R, H, g0, g1 = o["cyc"]
        size = (R + 1000) * 2 / 100
        floor = material(d, "M_StudioFloor", 0.6, 0.6)   # 环形棚灯离地近，地板 0.8 会过曝
        block("Floor", V(0, 0, -5), V(size, size, 0.1), floor)
        if o["cyc_mesh"]:
            sm = import_mesh(o["cyc_mesh"], d)
            cyc = eas.spawn_actor_from_class(unreal.StaticMeshActor, V(0, 0, 0), unreal.Rotator(0, 0, 0))
            cyc.set_actor_label("Cyclorama")
            cyc.static_mesh_component.set_static_mesh(sm)
            cyc.static_mesh_component.set_material(0, material(d, "M_StudioCyc", 0.18, 0.9, True))   # 双面：不依赖网格法线朝向
        else:
            cyclorama(R, H, g0, g1, grey)
        if o["wash"]:
            # 洗墙灯：放在半径一半处、朝外打墙，只照能被拍到的那一侧（缺口对面 ±90°）
            mid = math.radians((g0 + g1) / 2 + 180)
            for k, off in enumerate((-80, -40, 0, 40, 80)):
                a = mid + math.radians(off)
                src = V(R * 0.5 * math.cos(a), R * 0.5 * math.sin(a), 600)     # 低位朝上打会在墙顶留光斑，这个位置墙面最匀
                dst = V(R * math.cos(a), R * math.sin(a), 500)
                rect(f"Wash_{k}", src, dst, o["wash"], 400, 400, False, 0.0, R * 2)
    else:
        block("Floor", V(0, 0, -5), V(30, 30, 0.1), white)                 # 30m×30m，顶面在 z=0
        block("Backdrop", V(0, 700, 500), V(30, 0.1, 10), grey)            # 背景墙 30m 宽 10m 高
    for lab, (loc, cd, w, h, sh, barn) in p["lights"].items():
        if cd > 0:
            rect(lab, loc, FACE if lab != "Background" else V(0, 700, 250), cd, w, h, sh, barn)
    pp = eas.spawn_actor_from_class(unreal.PostProcessVolume, V(0, 0, 0), unreal.Rotator(0, 0, 0))
    pp.set_actor_label("StudioPost")
    pp.set_editor_property("unbound", True)
    pp.set_editor_property("priority", 10.0)           # 盖过角色关卡里原有的后期盒子（比如物理相机曝光）
    s = pp.settings
    for k, v in (("auto_exposure_method", unreal.AutoExposureMethod.AEM_BASIC),
                 ("auto_exposure_apply_physical_camera_exposure", False),
                 ("auto_exposure_min_brightness", ev), ("auto_exposure_max_brightness", ev),
                 ("auto_exposure_bias", 0.0),
                 ("local_exposure_highlight_contrast_scale", 0.7),
                 ("vignette_intensity", 0.25)):
        s.set_editor_property(k, v)
        s.set_editor_property("override_" + k, True)
    pp.settings = s
    les.save_current_level()
    shape = f"环形 {o['cyc'][0] / 100:.0f}m×{o['cyc'][1] / 100:.0f}m 缺口 {o['cyc'][2]:.0f}°–{o['cyc'][3]:.0f}°" if o["cyc"] else "单面墙"
    print(f"摄影棚 {lvl}：{shape}，布光 {o['preset']}，EV {ev}" + (f"，洗墙 {o['wash']:.0f}cd" if o["wash"] else ""))


main()
