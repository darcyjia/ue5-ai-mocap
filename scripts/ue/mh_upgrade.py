"""把已有 MetaHuman 角色升级：源贴图重新按 8K 下载，然后用电影级管线、最高质量重新组装（蓝图和网格原地覆盖）。

    mh_upgrade.py <角色资产>... [--res 8k|4k|2k] [--build /Game/MetaHumans] [--steps tex,build]
    例：mh_upgrade.py /Game/A/NewMetaHumanCharacter /Game/A/greencharacter --res 8k

在编辑器里跑（scripts/tools/ue_remote.py），要 Epic 登录（云端下载贴图）。先备份 Content/MetaHumans 和角色资产。
脸部绑定不动（已经是 JOINTS_AND_BLEND_SHAPES 就没必要重绑）；网格拓扑是 MetaHuman 固定的，LOD0 就是最高模。"""
import sys
import time

import unreal

SUB = unreal.get_editor_subsystem(unreal.MetaHumanCharacterEditorSubsystem)
RES = {"2k": unreal.RequestTextureResolution.RES2K, "4k": unreal.RequestTextureResolution.RES4K,
       "8k": unreal.RequestTextureResolution.RES8K}
FIELDS = ("face_albedo", "face_normal", "face_cavity", "face_animated_maps",
          "body_albedo", "body_normal", "body_cavity", "body_masks")


def args():
    a = sys.argv[1:]
    o = {"chars": [], "res": "8k", "build": "/Game/MetaHumans", "steps": "tex,build"}
    i = 0
    while i < len(a):
        if a[i] in ("--res", "--build", "--steps"):
            o[a[i][2:]] = a[i + 1]
            i += 2
        else:
            o["chars"].append(a[i])
            i += 1
    return o


def upgrade(path, o):
    ch = unreal.load_asset(path)
    if ch is None:
        raise RuntimeError(f"找不到 {path}")
    name = ch.get_name()
    if not SUB.try_add_object_to_edit(ch):
        raise RuntimeError(f"{name} 正被 MetaHuman Creator 打开，先关掉那个标签页")
    try:
        if "tex" in o["steps"]:
            s = ch.get_editor_property("skin_settings")
            r = s.get_editor_property("desired_texture_sources_resolutions")
            for f in FIELDS:
                r.set_editor_property(f, RES[o["res"]])
            s.set_editor_property("desired_texture_sources_resolutions", r)
            SUB.commit_skin_settings(ch, s)
            tp = unreal.MetaHumanCharacterTextureRequestParams()
            tp.blocking, tp.report_progress = True, True
            t0 = time.time()
            SUB.request_texture_sources(ch, tp)
            print(f"{name}：{o['res']} 源贴图下载完成 {time.time() - t0:.0f}s，高清 {ch.get_editor_property('has_high_resolution_textures')}")
            unreal.EditorAssetLibrary.save_loaded_asset(ch, only_if_is_dirty=False)
        if "build" in o["steps"]:
            if not SUB.can_build_meta_human(ch, True):
                raise RuntimeError(f"{name} 现在不能组装（看 Message Log）")
            bp = unreal.MetaHumanCharacterEditorBuildParameters()
            bp.pipeline_type = unreal.MetaHumanDefaultPipelineType.CINEMATIC
            bp.pipeline_quality = unreal.MetaHumanQualityLevel.CINEMATIC
            bp.absolute_build_path = o["build"]
            bp.common_folder_path = f"{o['build']}/Common"
            bp.enable_wardrobe_item_validation = False
            t0 = time.time()
            SUB.build_meta_human(character=ch, params=bp)
            print(f"{name}：电影级组装完成 {time.time() - t0:.0f}s → {o['build']}/{name}/BP_{name}")
    finally:
        if SUB.is_object_added_for_editing(ch):
            SUB.remove_object_to_edit(ch)


o = args()
for c in o["chars"]:
    upgrade(c, o)
unreal.EditorLoadingAndSavingUtils.save_dirty_packages(False, True)
print("done")
