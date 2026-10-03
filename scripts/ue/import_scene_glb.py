"""把一个 glb 场景（如 Sketchfab 下载的擂台）导进 UE，做成一个可当素材关卡模板的普通关卡（非 World Partition）。

    import_scene_glb.py <glb> <资产目录> <关卡路径> [缩放=1.0]          命令行 commandlet，一次做完
    import_scene_glb.py start <glb> <资产目录> <关卡路径>              编辑器里（异步）：先发起导入
    import_scene_glb.py finish <资产目录> <关卡路径> [缩放]            编辑器里：导入完成后缩放、补灯光、保存
    例：import_scene_glb.py G:/UE_Output/world_martial_arts_tournament.glb /Game/Arena/Budokai /Game/Arena/L_Budokai 0.7

Interchange 的 import_scene 会把网格/材质/贴图放进资产目录，同时把场景里的物体摆进当前关卡。
缩放：整个场景按比例缩（根物体的位置和缩放一起乘）。再补上太阳、天光、大气、雾（新关卡是空的）。
在编辑器里跑（scripts/tools/ue_remote.py）或命令行 commandlet 跑都可以；关卡已存在就报错，不覆盖。"""
import sys

import unreal

EAL = unreal.EditorAssetLibrary


LIGHTS = (unreal.DirectionalLight, unreal.SkyLight, unreal.SkyAtmosphere, unreal.ExponentialHeightFog)


def start(glb, dest, level):
    """新建关卡并发起 Interchange 场景导入。编辑器里导入是异步的，要等命令返回、编辑器继续跑才会完成。"""
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if EAL.does_asset_exist(level):
        raise RuntimeError(f"{level} 已存在，不覆盖")
    les.new_level(level)
    params = unreal.ImportAssetParameters()
    params.is_automated = True
    unreal.InterchangeManager.get_interchange_manager_scripted().import_scene(
        dest, unreal.InterchangeManager.create_source_data(glb), params)
    print(f"已开始导入 {glb} → {dest}（关卡 {level}）")


def finish(dest, level, scale=1.0):
    """导入完成后：整体缩放、补灯光、保存。"""
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    if unreal.InterchangeManager.get_interchange_manager_scripted().is_interchange_active():
        raise RuntimeError("导入还没结束，稍后再跑 finish")
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    if not world.get_path_name().startswith(level):
        les.load_level(level)
    acts = [a for a in eas.get_all_level_actors() if not isinstance(a, LIGHTS)]
    if not acts:
        raise RuntimeError("关卡里没有导入的物体：导入失败了，看 Output Log 的 LogInterchange")
    for a in acts:
        if a.get_attach_parent_actor() is None:
            a.set_actor_location(a.get_actor_location() * scale, False, False)
            a.set_actor_scale3d(a.get_actor_scale3d() * scale)
    have = {type(a) for a in eas.get_all_level_actors()}
    if unreal.DirectionalLight not in have:
        sun = eas.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0, 0, 2000), unreal.Rotator(0, -40, 30))
        sun.set_actor_label("Sun")
        sun.get_component_by_class(unreal.DirectionalLightComponent).set_editor_property("atmosphere_sun_light", True)
    if unreal.SkyLight not in have:
        sky = eas.spawn_actor_from_class(unreal.SkyLight, unreal.Vector(0, 0, 500), unreal.Rotator(0, 0, 0))
        sky.set_actor_label("SkyLight")
        sky.light_component.set_editor_property("real_time_capture", True)
    if unreal.SkyAtmosphere not in have:
        eas.spawn_actor_from_class(unreal.SkyAtmosphere, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
    if unreal.ExponentialHeightFog not in have:
        eas.spawn_actor_from_class(unreal.ExponentialHeightFog, unreal.Vector(0, 0, -200), unreal.Rotator(0, 0, 0))
    les.save_current_level()
    EAL.save_directory(dest.rsplit("/", 1)[0], only_if_is_dirty=False, recursive=True)
    meshes = [a for a in acts if isinstance(a, unreal.StaticMeshActor)]
    print(f"场景 {len(acts)} 个物体（网格 {len(meshes)}），资产 {len(EAL.list_assets(dest, recursive=True))} 个，缩放 ×{scale} → {level}")


def main(glb, dest, level, scale=1.0):
    """命令行 commandlet 里一次做完（那里 wait_until_all_tasks_done 会阻塞等完）。"""
    start(glb, dest, level)
    unreal.InterchangeManager.get_interchange_manager_scripted().wait_until_all_tasks_done(True)
    finish(dest, level, scale)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "start":        # 编辑器里：start <glb> <资产目录> <关卡>，等导入完再 finish
        start(a[1], a[2], a[3])
    elif a[0] == "finish":     # finish <资产目录> <关卡> [缩放]
        finish(a[1], a[2], float(a[3]) if len(a) > 3 else 1.0)
    else:                      # commandlet：<glb> <资产目录> <关卡> [缩放]
        main(a[0], a[1], a[2], float(a[3]) if len(a) > 3 else 1.0)
