"""在 UE 编辑器里用 MetaHuman Creator 的脚本接口生成演员（UE 5.8 MetaHumanCharacterEditorSubsystem）。

    mh_actors.py <步骤> <角色设定.json>
    步骤：probe（看体型参数范围）/ create（建角色、体型、肤色、毛发、服装）/ cloud（云端绑定 + 下载贴图）/ build（组装成蓝图）/ all

在编辑器里跑（云端步骤要 Epic 登录，第一次会弹登录）。可以用 scripts/tools/ue_remote.py 从外部发过来。
服装：自带衣柜只有一套 T 恤长裤，所以不加衣服——关掉上身内衣 = 赤膊赤脚，下身内衣贴图换成设定里的颜色 = 短裤。"""
import json
import os
import struct
import sys
import time
import zlib

import unreal

SUB = unreal.get_editor_subsystem(unreal.MetaHumanCharacterEditorSubsystem)
GROOM_DIR = {"Hair": "Hair", "Eyebrows": "Eyebrows", "Eyelashes": "Eyelashes", "Beard": "Beards",
             "Mustache": "Mustaches", "Peachfuzz": "Peachfuzz"}
LOG = None


def log(*a):
    s = time.strftime("[%H:%M:%S] ") + " ".join(str(x) for x in a)
    print(s)
    if LOG:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(s + "\n")


class Editing:
    """打开角色的编辑状态，退出时释放。"""
    def __init__(self, ch):
        self.ch = ch

    def __enter__(self):
        if not SUB.try_add_object_to_edit(self.ch):
            raise RuntimeError(f"{self.ch.get_name()} 正被其他编辑器打开，请先关掉 MetaHuman Creator 标签页")
        return self.ch

    def __exit__(self, *exc):
        if SUB.is_object_added_for_editing(self.ch):
            SUB.remove_object_to_edit(self.ch)


def asset_path(spec, a):
    return f"{spec['content_dir']}/{a['name']}/{a['name']}"


def load_or_create(spec, a):
    path = asset_path(spec, a)
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        return unreal.load_asset(path)
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    ch = tools.create_asset(asset_name=a["name"], package_path=path.rsplit("/", 1)[0],
                            asset_class=unreal.MetaHumanCharacter, factory=unreal.MetaHumanCharacterFactoryNew())
    log(f"新建角色 {path}")
    return ch


def constraints(ch):
    return SUB.get_body_constraints(ch, False)


def cdict(c):
    out = {"name": str(c.name)}
    for k in ("is_active", "target_measurement", "actual_measurement", "min_measurement", "max_measurement"):
        try:
            v = c.get_editor_property(k)
            out[k] = bool(v) if k == "is_active" else round(float(v), 2)
        except Exception:
            pass
    return out


# ---------- 体型 ----------
def apply_body(ch, body):
    """body: {约束名: 数值}。数值 ≤ 1 视为在 [min,max] 里的比例，> 1 视为实际测量值（厘米）。
    注意：遍历 get_body_constraints() 得到的是副本，要把改过的副本收集成新列表再传回去。"""
    out, done = [], []
    for c in constraints(ch):
        name = str(c.name)
        if name in body:
            v = float(body[name])
            lo, hi = float(c.get_editor_property("min_measurement")), float(c.get_editor_property("max_measurement"))
            t = lo + v * (hi - lo) if v <= 1.0 else v
            c.set_editor_property("is_active", True)
            c.set_editor_property("target_measurement", t)
            done.append(f"{name}={t:.1f}")
        out.append(c)
    SUB.set_body_constraints(ch, out)
    SUB.commit_body_state(ch)
    missing = set(body) - {str(c.name) for c in out}
    log("  体型：" + "，".join(done) + (f"（找不到：{sorted(missing)}）" if missing else ""))


# ---------- 皮肤 + 短裤颜色 ----------
def _png(path, rgb, size=64):
    row = b"\x00" + bytes(rgb) * size
    raw = row * size
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)  # noqa: E731
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(data)


def shorts_texture(spec, rgb, tag):
    dst = f"{spec['content_dir']}/Common"
    name = f"T_Shorts_{tag}_BC"
    if unreal.EditorAssetLibrary.does_asset_exist(f"{dst}/{name}"):
        return unreal.load_asset(f"{dst}/{name}")
    png = os.path.join(unreal.Paths.project_intermediate_dir(), f"{name}.png")
    _png(png, [int(round(x * 255)) for x in rgb])
    t = unreal.AssetImportTask()
    t.set_editor_property("filename", png)
    t.set_editor_property("destination_path", dst)
    t.set_editor_property("destination_name", name)
    t.set_editor_property("automated", True)
    t.set_editor_property("save", True)
    t.set_editor_property("replace_existing", True)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([t])
    tex = unreal.load_asset(f"{dst}/{name}")
    log(f"  短裤贴图 {dst}/{name}")
    return tex


def apply_skin(spec, ch, a):
    s = ch.get_editor_property("skin_settings")
    skin = s.get_editor_property("skin")
    sk = a.get("skin", {})
    if "u" in sk:
        skin.set_editor_property("u", sk["u"])
    if "v" in sk:
        skin.set_editor_property("v", sk["v"])
    skin.set_editor_property("show_top_underwear", bool(a.get("top_underwear", False)))
    s.set_editor_property("skin", skin)
    rgb = a.get("shorts_color", spec.get("shorts_color"))
    if rgb:
        tex = shorts_texture(spec, rgb, "".join(f"{int(x * 255):02X}" for x in rgb))
        ov = s.get_editor_property("texture_material_overrides")
        ov.set_editor_property("enable_texture_overrides", True)
        ts = ov.get_editor_property("texture_overrides")
        body = dict(ts.get_editor_property("body"))
        body[unreal.BodyTextureType.BODY_UNDERWEAR_BASECOLOR] = tex
        ts.set_editor_property("body", body)
        ov.set_editor_property("texture_overrides", ts)
        s.set_editor_property("texture_material_overrides", ov)
    ch.set_editor_property("preview_material_type", unreal.MetaHumanCharacterSkinPreviewMaterial.EDITABLE)
    SUB.commit_skin_settings(ch, s)
    log(f"  皮肤：u={skin.get_editor_property('u'):.2f} v={skin.get_editor_property('v'):.2f}，"
        f"上身内衣 {'开' if a.get('top_underwear') else '关（赤膊）'}，短裤颜色 {rgb}")


# ---------- 毛发 + 服装 ----------
def same_item(key, path):
    """已选素材是不是这个路径（同名素材可能在不同插件里，不能只比名字）。"""
    return key is not None and f'"{path}.' in key.export_text()


def apply_grooms(ch, a):
    coll = ch.get_editor_property("internal_collection")
    inst = coll.get_editor_property("default_instance")
    keys = {}
    current = {}   # 重复运行时复用已经加过的素材，不叠加
    for d in inst.get_slot_selection_data():
        current.setdefault(str(d.selection.slot_name), d.selection.selected_item)
    for slot in GROOM_DIR:
        item = a.get("grooms", {}).get(slot)
        if not item:
            inst.set_single_slot_selection(slot_name=slot, item_key=unreal.MetaHumanPaletteItemKey())
            continue
        key = current.get(slot)
        path = f"/MetaHumanCharacter/Optional/Grooms/Bindings/{GROOM_DIR[slot]}/{item}"
        if not same_item(key, path):
            wi = unreal.load_asset(f"{path}.{item}")
            if not wi:
                log(f"  [警告] 找不到 {slot} 素材 {item}")
                continue
            key = coll.try_add_item_from_wardrobe_item(slot, wi)
        inst.set_single_slot_selection(slot_name=slot, item_key=key)
        keys[slot] = key
    # 服装：outfit = {"item": 衣柜素材完整路径, "colors": {参数名: [r,g,b]}}
    outfit = a.get("outfit")
    okey = None
    if outfit:
        okey = current.get("Outfits")
        if not same_item(okey, outfit["item"]):
            wi = unreal.load_asset(outfit["item"])
            if not wi:
                raise RuntimeError(f"找不到服装 {outfit['item']}（对应插件启用了吗？）")
            okey = coll.try_add_item_from_wardrobe_item("Outfits", wi)
        inst.set_single_slot_selection(slot_name="Outfits", item_key=okey)
    else:
        inst.set_single_slot_selection(slot_name="Outfits", item_key=unreal.MetaHumanPaletteItemKey())
    SUB.assemble_for_preview(character=ch)
    mel = a.get("hair_melanin")
    if mel is not None:
        for slot, key in keys.items():
            for p in inst.get_instance_parameters(item_path=unreal.MetaHumanPaletteItemPath(item_key=key)):
                if p.name == "Melanin":
                    p.set_float(value=float(mel))
    log("  毛发：" + ("，".join(f"{k}={a['grooms'][k]}" for k in keys) or "无") + (f"，黑色素 {mel}" if mel is not None else ""))
    if okey is not None:
        params = inst.get_instance_parameters(item_path=unreal.MetaHumanPaletteItemPath(item_key=okey))
        colors = outfit.get("colors", {})
        for p in params:
            if str(p.name) in colors:
                p.set_color(value=unreal.LinearColor(*colors[str(p.name)], 1.0))
        log(f"  服装：{okey.to_asset_name_string()}，设色 {list(colors)}；可调参数 {[str(p.name) for p in params]}")


def save(ch):
    unreal.EditorAssetLibrary.save_loaded_asset(ch, only_if_is_dirty=False)


# ---------- 步骤 ----------
def step_probe(spec):
    a = {"name": "_Probe"}
    ch = load_or_create(spec, a)
    rep = {}
    with Editing(ch):
        rep["default"] = [cdict(c) for c in constraints(ch)]
        for end, v in (("min", 0.0), ("max", 1.0)):
            apply_body(ch, {"Masculine/Feminine": v})
            rep[end] = {d["name"]: d.get("target_measurement") for d in map(cdict, constraints(ch))}
    unreal.EditorAssetLibrary.delete_asset(asset_path(spec, a).rsplit("/", 1)[0])
    out = os.path.join(os.path.dirname(LOG), "mh_probe.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    log(f"体型参数 → {out}")
    keys = ("Height", "Chest", "Bust Span", "Underbust", "Waist", "Hip", "Across Shoulder", "Neck")
    for end in ("min", "max"):
        log(f"  Masculine/Feminine={end}: " + "，".join(f"{k}={rep[end].get(k)}" for k in keys))


def step_create(spec):
    for a in spec["actors"]:
        log(f"== {a['name']}（{a.get('role', '')}）")
        ch = load_or_create(spec, a)
        with Editing(ch):
            apply_body(ch, a.get("body", {}))
            apply_skin(spec, ch, a)
            apply_grooms(ch, a)
        save(ch)
    log("create 完成")


def step_cloud(spec):
    for a in spec["actors"]:
        ch = unreal.load_asset(asset_path(spec, a))
        log(f"== {a['name']}：云端绑定 + 下载贴图")
        with Editing(ch):
            rp = unreal.MetaHumanCharacterAutoRiggingRequestParams()
            rp.blocking, rp.report_progress = True, True
            rp.rig_type = unreal.MetaHumanRigType.JOINTS_AND_BLEND_SHAPES
            t0 = time.time()
            SUB.request_auto_rigging(ch, rp)
            log(f"  绑定完成 {time.time() - t0:.0f}s")
            tp = unreal.MetaHumanCharacterTextureRequestParams()
            tp.blocking, tp.report_progress = True, True
            t0 = time.time()
            SUB.request_texture_sources(ch, tp)
            log(f"  贴图完成 {time.time() - t0:.0f}s，高清贴图 {ch.get_editor_property('has_high_resolution_textures')}")
            log(f"  可以组装：{SUB.can_build_meta_human(ch, True)}")
        save(ch)
    log("cloud 完成")


def recolor_outfit(spec, a):
    """服装颜色：组装产物里带这些参数的材质实例，直接改向量参数（outfit.material_colors：参数名 → [r,g,b]）。"""
    colors = (a.get("outfit") or {}).get("material_colors")
    if not colors:
        return
    mel = unreal.MaterialEditingLibrary
    hit = []
    for path in unreal.EditorAssetLibrary.list_assets(f"{spec['content_dir']}/{a['name']}", True, False):
        mi = unreal.load_asset(path)
        if not isinstance(mi, unreal.MaterialInstanceConstant):
            continue
        names = {str(n) for n in mel.get_vector_parameter_names(mi)}
        todo = [k for k in colors if k in names]
        if not todo:
            continue
        for k in todo:
            mel.set_material_instance_vector_parameter_value(mi, k, unreal.LinearColor(*colors[k], 1.0))
        mel.update_material_instance(mi)
        unreal.EditorAssetLibrary.save_loaded_asset(mi, False)
        hit.append(f"{mi.get_name()}({','.join(todo)})")
    log(f"  服装改色：{hit or '没找到带这些参数的材质'}")


def step_build(spec):
    for a in spec["actors"]:
        ch = unreal.load_asset(asset_path(spec, a))
        log(f"== {a['name']}：组装")
        with Editing(ch):
            if not SUB.can_build_meta_human(ch, True):
                raise RuntimeError(f"{a['name']} 还不能组装：先跑 cloud（绑定 + 贴图）")
            bp = unreal.MetaHumanCharacterEditorBuildParameters()
            bp.pipeline_type = getattr(unreal.MetaHumanDefaultPipelineType, spec.get("pipeline", "CINEMATIC"))
            bp.absolute_build_path = spec["content_dir"]
            bp.common_folder_path = f"{spec['content_dir']}/Common"
            bp.enable_wardrobe_item_validation = False
            t0 = time.time()
            SUB.build_meta_human(character=ch, params=bp)
            log(f"  组装完成 {time.time() - t0:.0f}s → {spec['content_dir']}/{a['name']}/BP_{a['name']}")
        recolor_outfit(spec, a)
    unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
    log("build 完成")


def main(argv):
    global LOG
    step, spec_path = argv[0], argv[1]
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    LOG = os.path.join(os.path.dirname(os.path.abspath(spec_path)), "mh_actors.log")
    steps = ["create", "cloud", "build"] if step == "all" else [step]
    for s in steps:
        log(f"#### {s}")
        globals()[f"step_{s}"](spec)


if __name__ == "__main__":
    main(sys.argv[1:])
