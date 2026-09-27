"""UE 5.8 命令行（-run=pythonscript）里执行：导入 FBX → IK Rig → 重定向到 MetaHuman → 度量 → 关卡序列。
任务参数在环境变量 AIMOCAP_JOB 指向的 JSON 里。
关键教训（都已踩过）：
- 重定向姿态只对齐手臂/手指；auto_align_all_bones 会让 MetaHuman 驼背 ~30°、低头 ~55°。
- UE 只按比例缩放骨盆的垂直运动，水平原样传递 → 用统一的 scale_horizontal 让步幅匹配目标角色腿长。
- 同名资产删除后立刻 create_asset 会返回 None → 已存在就加载后重新配置，不删。
- 命令行无渲染：不能导出带预览网格的 FBX、不能挂蓝图 SCS 组件 → 序列里用 SkeletalMeshActor+身体网格。"""
import json
import math
import os

import unreal

JOB = json.load(open(os.environ["AIMOCAP_JOB"], encoding="utf-8"))
EAL = unreal.EditorAssetLibrary
AT = unreal.AssetToolsHelpers.get_asset_tools()
AL = unreal.AnimationLibrary
S, T = unreal.RetargetSourceOrTarget.SOURCE, unreal.RetargetSourceOrTarget.TARGET
CD, RD = JOB["content_dir"], JOB["retarget_dir"]
RESULT = {"persons": [], "ok": False}


def P(*a):
    unreal.log("@@ " + " ".join(str(x) for x in a))


def load_or_create(path, cls, factory):
    if EAL.does_asset_exist(path):
        return unreal.load_asset(path), False
    d, n = path.rsplit("/", 1)
    return AT.create_asset(n, d, cls, factory), True


# ---------------- 1 导入 FBX（旧版导入器，参数可控） ----------------
unreal.SystemLibrary.execute_console_command(None, "Interchange.FeatureFlags.Import.FBX False")


def import_fbx(fbx, dest):
    ui = unreal.FbxImportUI()
    for k, v in dict(import_mesh=True, import_as_skeletal=True, import_animations=True, import_materials=False,
                     import_textures=False, create_physics_asset=False,
                     mesh_type_to_import=unreal.FBXImportType.FBXIT_SKELETAL_MESH).items():
        ui.set_editor_property(k, v)
    ad = ui.anim_sequence_import_data
    ad.set_editor_property("use_default_sample_rate", False)
    ad.set_editor_property("custom_sample_rate", JOB["fps"])
    ad.set_editor_property("animation_length", unreal.FBXAnimationLengthImportType.FBXALIT_EXPORTED_TIME)
    t = unreal.AssetImportTask()
    for k, v in dict(filename=fbx, destination_path=dest, automated=True, replace_existing=True, save=True,
                     options=ui).items():
        t.set_editor_property(k, v)
    AT.import_asset_tasks([t])


people = []
for k, fbx in enumerate(JOB["fbx"]):
    dest = f"{CD}/p{k}"
    import_fbx(fbx, dest)
    assets = [unreal.load_asset(x) for x in EAL.list_assets(dest, recursive=False)]
    mesh = next(x for x in assets if isinstance(x, unreal.SkeletalMesh))
    anim = next(x for x in assets if isinstance(x, unreal.AnimSequence))
    people.append(dict(mesh=mesh, anim=anim, cfg=JOB["persons"][k]))
    P(f"p{k} imported", anim.get_path_name(), "frames", AL.get_num_frames(anim))

# ---------------- 2 IK Rig ----------------
CHAINS = [("Spine", "spine_01", "spine_03", None), ("Neck", "neck_01", "neck_01", None), ("Head", "head", "head", None)]
for Sd, s in (("Left", "l"), ("Right", "r")):
    CHAINS += [(f"{Sd}Leg", f"thigh_{s}", f"foot_{s}", f"{Sd}FootIK"), (f"{Sd}Foot", f"ball_{s}", f"ball_{s}", None),
               (f"{Sd}Clavicle", f"clavicle_{s}", f"clavicle_{s}", None), (f"{Sd}Arm", f"upperarm_{s}", f"hand_{s}", f"{Sd}HandIK")]
    for f in ("Thumb", "Index", "Middle", "Ring", "Pinky"):
        CHAINS.append((f"{Sd}{f}", f"{f.lower()}_01_{s}", f"{f.lower()}_03_{s}", None))

_mh_rigs = {}


def mh_rig(mesh_path):
    """每个 MetaHuman 身体网格一个自动生成的 IK Rig（链名：Spine/Neck/Head/LeftLeg/…）。"""
    if mesh_path in _mh_rigs:
        return _mh_rigs[mesh_path]
    mesh = unreal.load_asset(mesh_path)
    rig, created = load_or_create(f"{RD}/IK_MH_{mesh.get_name()}", unreal.IKRigDefinition, unreal.IKRigDefinitionFactory())
    c = unreal.IKRigController.get_controller(rig)
    if created or not c.get_retarget_chains():
        c.set_skeletal_mesh(mesh)
        c.apply_auto_generated_retarget_definition()
        c.apply_auto_fbik()
        EAL.save_loaded_asset(rig)
    _mh_rigs[mesh_path] = (mesh, rig)
    return mesh, rig


for k, p in enumerate(people):
    rig, created = load_or_create(f"{CD}/IK_SMPLX_p{k}", unreal.IKRigDefinition, unreal.IKRigDefinitionFactory())
    c = unreal.IKRigController.get_controller(rig)
    c.set_skeletal_mesh(p["mesh"])
    if created or not c.get_retarget_chains():
        c.set_retarget_root("pelvis")
        for name, a, b, goal in CHAINS:          # 与 MetaHuman 完全同名，按 EXACT 映射
            if goal:
                c.add_new_goal(goal, b)
            c.add_retarget_chain(name, a, b, goal or "")
    EAL.save_loaded_asset(rig)
    p["rig"] = rig
    p["tmesh"], p["trig"] = mh_rig(p["cfg"]["mh_mesh"])


def ref_z(rig, bone):
    return unreal.IKRigController.get_controller(rig).get_ref_pose_transform_of_bone(bone).translation.z


for p in people:
    p["ratio"] = ref_z(p["trig"], "pelvis") / ref_z(p["rig"], "pelvis")
kh = sum(p["ratio"] for p in people) / len(people) if JOB["uniform_horizontal_scale"] else 1.0
if JOB.get("force_horizontal_scale"):
    kh = float(JOB["force_horizontal_scale"])
P("pelvis height ratios", [round(p["ratio"], 3) for p in people], "horizontal scale", round(kh, 3))

# ---------------- 3 重定向器 + 批量重定向 ----------------
ARM = []
for s in ("l", "r"):
    ARM += [f"clavicle_{s}", f"upperarm_{s}", f"lowerarm_{s}", f"hand_{s}"]
    for f in ("thumb", "index", "middle", "ring", "pinky"):
        ARM += [f"{f}_0{i}_{s}" for i in (1, 2, 3)]
    ARM += [f"{f}_metacarpal_{s}" for f in ("index", "middle", "ring", "pinky")]

for k, p in enumerate(people):
    rtg, created = load_or_create(f"{CD}/RTG_p{k}", unreal.IKRetargeter, unreal.IKRetargetFactory())
    r = unreal.IKRetargeterController.get_controller(rtg)
    r.set_ik_rig(S, p["rig"])
    r.set_ik_rig(T, p["trig"])
    if created or r.get_num_retarget_ops() == 0:
        r.add_default_ops()
    r.assign_ik_rig_to_all_ops(S, p["rig"])
    r.assign_ik_rig_to_all_ops(T, p["trig"])
    r.set_preview_mesh(S, p["mesh"])
    r.set_preview_mesh(T, p["tmesh"])
    r.auto_map_chains(unreal.AutoMapChainType.EXACT, True)
    r.reset_retarget_pose(r.get_current_retarget_pose_name(T), [], T)
    r.auto_align_bones(ARM, unreal.RetargetAutoAlignMethod.CHAIN_TO_CHAIN, T)      # 只对齐手臂！
    for i in range(r.get_num_retarget_ops()):
        if str(r.get_op_name(i)) == "Pelvis Motion":
            oc = r.get_op_controller(i)
            st = oc.get_settings()
            st.set_editor_property("scale_horizontal", float(kh))
            oc.set_settings(st)
    EAL.save_loaded_asset(rtg)
    out = unreal.IKRetargetBatchOperation.duplicate_and_retarget(
        [EAL.find_asset_data(p["anim"].get_path_name())], p["mesh"], p["tmesh"], rtg, "", "", "MH_", "", CD,
        False, False, True)
    p["mh_anim"] = unreal.load_asset(str(out[0].package_name))
    P(f"p{k} retargeted", p["mh_anim"].get_path_name())


# ---------------- 4 度量（与源动作比较） ----------------
def world(a, chain, f):
    w, pos = None, {}
    for b in chain:
        t = AL.get_bone_pose_for_frame(a, b, f, False)
        w = t if w is None else t.multiply(w)
        pos[b] = w.translation
    return pos


def tilt(v):
    return math.degrees(math.acos(max(-1, min(1, v.z / max(v.length(), 1e-6)))))


def ang(u, v):
    return math.degrees(math.acos(max(-1, min(1, u.dot(v) / max(u.length() * v.length(), 1e-6)))))


SSP = ["root", "pelvis", "spine_01", "spine_02", "spine_03", "neck_01", "head"]
MSP = ["root", "pelvis", "spine_01", "spine_02", "spine_03", "spine_04", "spine_05", "neck_01", "neck_02", "head"]
SAR = ["root", "pelvis", "spine_01", "spine_02", "spine_03", "clavicle_{s}", "upperarm_{s}", "lowerarm_{s}", "hand_{s}"]
MAR = ["root", "pelvis", "spine_01", "spine_02", "spine_03", "spine_04", "spine_05", "clavicle_{s}", "upperarm_{s}", "lowerarm_{s}", "hand_{s}"]
nf = min(AL.get_num_frames(p["mh_anim"]) for p in people)
FR = list(range(0, nf, max(1, nf // 24)))
for k, p in enumerate(people):
    rs_c, rm_c = unreal.IKRigController.get_controller(p["rig"]), unreal.IKRigController.get_controller(p["trig"])
    rs = tilt(rs_c.get_ref_pose_transform_of_bone("head").translation - rs_c.get_ref_pose_transform_of_bone("neck_01").translation)
    rm = tilt(rm_c.get_ref_pose_transform_of_bone("head").translation - rm_c.get_ref_pose_transform_of_bone("neck_01").translation)
    dt, dh, da = [], [], []
    p["src_pelvis"], p["mh_pelvis"] = [], []
    for f in FR:
        s1, m1 = world(p["anim"], SSP, f), world(p["mh_anim"], MSP, f)
        dt.append(tilt(m1["neck_01"] - m1["pelvis"]) - tilt(s1["neck_01"] - s1["pelvis"]))
        dh.append((tilt(m1["head"] - m1["neck_01"]) - rm) - (tilt(s1["head"] - s1["neck_01"]) - rs))
        p["src_pelvis"].append(s1["pelvis"])
        p["mh_pelvis"].append(m1["pelvis"])
        for sd in ("l", "r"):
            sa = world(p["anim"], [b.format(s=sd) for b in SAR], f)
            ma = world(p["mh_anim"], [b.format(s=sd) for b in MAR], f)
            da.append(ang(ma[f"lowerarm_{sd}"] - ma[f"upperarm_{sd}"], sa[f"lowerarm_{sd}"] - sa[f"upperarm_{sd}"]))
            da.append(ang(ma[f"hand_{sd}"] - ma[f"lowerarm_{sd}"], sa[f"hand_{sd}"] - sa[f"lowerarm_{sd}"]))
    m = lambda x: round(sum(x) / len(x), 2)
    mx = lambda x: round(max(x, key=abs), 2)
    rec = {"p": k, "mh_mesh": p["cfg"]["mh_mesh"], "anim": p["mh_anim"].get_path_name(),
           "torso_err_mean": m(dt), "torso_err_max": mx(dt), "head_err_mean": m(dh), "head_err_max": mx(dh),
           "arm_err_mean": m(da), "arm_err_max": mx(da), "pelvis_ratio": round(p["ratio"], 4),
           "pelvis_h_src": round(sum(v.z for v in p["src_pelvis"]) / len(FR), 1),
           "pelvis_h_mh": round(sum(v.z for v in p["mh_pelvis"]) / len(FR), 1)}
    RESULT["persons"].append(rec)
    P(f"p{k} metrics", json.dumps(rec, ensure_ascii=False))
if len(people) >= 2:
    rat = []
    for i in range(len(FR)):
        a, b = people[0], people[1]
        ds = math.hypot(a["src_pelvis"][i].x - b["src_pelvis"][i].x, a["src_pelvis"][i].y - b["src_pelvis"][i].y)
        dm = math.hypot(a["mh_pelvis"][i].x - b["mh_pelvis"][i].x, a["mh_pelvis"][i].y - b["mh_pelvis"][i].y)
        if ds > 1:
            rat.append(dm / ds)
    rat.sort()
    RESULT["spacing_ratio_median"] = round(rat[len(rat) // 2], 4)
    RESULT["spacing_ratio_expected"] = round(kh, 4)
RESULT["horizontal_scale"] = round(kh, 4)

# ---------------- 5 关卡序列 ----------------
seq, created = load_or_create(f"{CD}/LS_{JOB['clip']}", unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
if not created:
    for b in list(seq.get_bindings()):
        b.remove()
    get_t = getattr(seq, "get_tracks", None) or getattr(seq, "get_master_tracks")
    rm_t = getattr(seq, "remove_track", None) or getattr(seq, "remove_master_track")
    for t in list(get_t()):
        rm_t(t)
seq.set_display_rate(unreal.FrameRate(JOB["fps"], 1))
seq.set_playback_start(0)
seq.set_playback_end(nf)
for k, p in enumerate(people):
    b = seq.add_spawnable_from_class(unreal.SkeletalMeshActor)
    b.set_display_name(f"{JOB['persons'][k]['name']}_p{k}")
    b.get_object_template().skeletal_mesh_component.set_skeletal_mesh_asset(p["tmesh"])
    tr = b.add_track(unreal.MovieSceneSkeletalAnimationTrack)
    sec = tr.add_section()
    sec.set_range(0, nf)
    prm = sec.get_editor_property("params")
    prm.set_editor_property("animation", p["mh_anim"])
    sec.set_editor_property("params", prm)
cam = seq.add_spawnable_from_class(unreal.CineCameraActor)
cam.set_display_name("OrigCam")
cc = cam.get_object_template().get_editor_property("camera_component")
fb = cc.get_editor_property("filmback")
fb.set_editor_property("sensor_width", 36.0)
fb.set_editor_property("sensor_height", 36.0 * JOB["res"][1] / JOB["res"][0])
cc.set_editor_property("filmback", fb)
cc.set_editor_property("current_focal_length", float(JOB["lens"]))
fs = cc.get_editor_property("focus_settings")
fs.set_editor_property("focus_method", unreal.CameraFocusMethod.DISABLE)
cc.set_editor_property("focus_settings", fs)
ctr = cam.add_track(unreal.MovieScene3DTransformTrack)
csec = ctr.add_section()
csec.set_range(0, nf)
ch = csec.get_all_channels()
for i, v in enumerate(JOB["cam_ue"]):
    ch[i].set_default(float(v))
cut = (getattr(seq, "add_track", None) or getattr(seq, "add_master_track"))(unreal.MovieSceneCameraCutTrack)
cs = cut.add_section()
cs.set_range(0, nf)
cs.set_camera_binding_id(seq.get_binding_id(cam))
EAL.save_loaded_asset(seq)
RESULT["sequence"] = seq.get_path_name()

# ---------------- 6 导出重定向后的骨架动画（不带网格；供外部检查） ----------------
os.makedirs(JOB["export_dir"], exist_ok=True)
for k, p in enumerate(people):
    t = unreal.AssetExportTask()
    opt = unreal.FbxExportOption()
    opt.set_editor_property("export_preview_mesh", False)
    for kk, vv in dict(object=p["mh_anim"], filename=os.path.join(JOB["export_dir"], f"MH_p{k}.fbx"),
                       exporter=unreal.AnimSequenceExporterFBX(), options=opt, automated=True,
                       replace_identical=True, prompt=False).items():
        t.set_editor_property(kk, vv)
    unreal.Exporter.run_asset_export_task(t)
unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
RESULT["ok"] = True
json.dump(RESULT, open(JOB["result"], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
P("DONE")
