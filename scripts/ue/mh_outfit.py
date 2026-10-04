"""给已有 MetaHuman 换服装、按需重新组装、改服装材质颜色。

    mh_outfit.py <角色资产>... [--item 衣柜素材路径] [--white] [--build auto|yes|no] [--out /Game/MetaHumans]
    例：mh_outfit.py /Game/A/NewMetaHumanCharacter /Game/A/greencharacter --white

默认服装是 MetaHumanCrowdContent 的白短裤（Outfits/Bottoms/OA_Shorts/WI_OA_Shorts，标准服装管线；
CrowdWardrobeItems 下的同名素材走 Crowd 专用管线，电影级组装会跳过）。上身不穿 = 只选这一件下装。
--build no（默认）：只换选择，不组装——请在 MetaHuman Creator 里点 Assemble。脚本组装（build_meta_human）用的是
       默认管线设置，不会读你在 Creator 里设的烘焙分辨率（实测 8K 被降回 2K）。确定用默认设置时才 --build auto/yes。
--white：把组装产物里短裤材质的颜色参数改成米白。在编辑器里跑（scripts/tools/ue_remote.py）。"""
import sys
import time

import unreal

SUB = unreal.get_editor_subsystem(unreal.MetaHumanCharacterEditorSubsystem)
SHORTS = "/MetaHumanCrowdContent/Outfits/Bottoms/OA_Shorts/WI_OA_Shorts"
WHITE = (0.85, 0.84, 0.80)
COLOR_PARAMS = ("diffuse_color_1", "diffuse_color_2", "B_diffuse_color_1", "C_color")


def args():
    a = sys.argv[1:]
    o = {"chars": [], "item": SHORTS, "white": False, "build": "no", "out": "/Game/MetaHumans"}
    i = 0
    while i < len(a):
        if a[i] in ("--item", "--build", "--out"):
            o[a[i][2:]] = a[i + 1]
            i += 2
        elif a[i] == "--white":
            o["white"] = True
            i += 1
        else:
            o["chars"].append(a[i])
            i += 1
    return o


def select_outfit(ch, item):
    """Outfits 槽只选这一件，返回是否有变化。同名素材可能来自不同插件，按完整路径比。"""
    coll = ch.get_editor_property("internal_collection")
    inst = coll.get_editor_property("default_instance")
    cur = [d.selection.selected_item for d in inst.get_slot_selection_data() if str(d.selection.slot_name) == "Outfits"]
    if len(cur) == 1 and f'"{item}.' in cur[0].export_text():
        return False
    wi = unreal.load_asset(item)
    if wi is None:
        raise RuntimeError(f"找不到 {item}（MetaHumanCrowdContent 插件启用了吗？）")
    key = coll.try_add_item_from_wardrobe_item("Outfits", wi)
    inst.set_single_slot_selection(slot_name="Outfits", item_key=key)
    unreal.EditorAssetLibrary.save_loaded_asset(ch, only_if_is_dirty=False)
    return True


def build(ch, out):
    if not SUB.try_add_object_to_edit(ch):
        raise RuntimeError(f"{ch.get_name()} 正在 MetaHuman Creator 里打开，先关掉那个标签页")
    try:
        if not SUB.can_build_meta_human(ch, True):
            raise RuntimeError(f"{ch.get_name()} 现在不能组装（看 Message Log）")
        bp = unreal.MetaHumanCharacterEditorBuildParameters()
        bp.pipeline_type = unreal.MetaHumanDefaultPipelineType.CINEMATIC
        bp.pipeline_quality = unreal.MetaHumanQualityLevel.CINEMATIC
        bp.absolute_build_path = out
        bp.common_folder_path = f"{out}/Common"
        bp.enable_wardrobe_item_validation = False
        t0 = time.time()
        SUB.build_meta_human(character=ch, params=bp)
        print(f"  组装完成 {time.time() - t0:.0f}s")
    finally:
        if SUB.is_object_added_for_editing(ch):
            SUB.remove_object_to_edit(ch)


def recolor(folder, rgb):
    mel = unreal.MaterialEditingLibrary
    hit = []
    for path in unreal.EditorAssetLibrary.list_assets(folder, True, False):
        mi = unreal.load_asset(path)
        if not isinstance(mi, unreal.MaterialInstanceConstant):
            continue
        names = {str(n) for n in mel.get_vector_parameter_names(mi)}
        todo = [k for k in COLOR_PARAMS if k in names]
        if todo:
            for k in todo:
                mel.set_material_instance_vector_parameter_value(mi, k, unreal.LinearColor(*rgb, 1.0))
            mel.update_material_instance(mi)
            unreal.EditorAssetLibrary.save_loaded_asset(mi, False)
            hit.append(mi.get_name())
    return hit


o = args()
for c in o["chars"]:
    ch = unreal.load_asset(c)
    name = ch.get_name()
    changed = select_outfit(ch, o["item"])
    print(f"{name}：服装 {o['item'].rsplit('/', 1)[-1]}（{'已更换' if changed else '本来就是'}）")
    if o["build"] == "yes" or (o["build"] == "auto" and changed):
        build(ch, o["out"])
        unreal.EditorLoadingAndSavingUtils.save_dirty_packages(False, True)   # 组装产物默认不落盘
    elif changed:
        print("  服装已换，请在 MetaHuman Creator 里打开这个角色点 Assemble（保留你的烘焙设置），之后再跑 --white")
    if o["white"]:
        folder = f"{o['out']}/{name}"
        print(f"  改白：{recolor(folder, WHITE) or '没找到服装材质（还没组装？）'}")
print("done")
