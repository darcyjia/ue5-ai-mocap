"""UE 端：导入 FBX → IK Rig → 重定向到 MetaHuman → 度量 → 专用关卡 + 关卡序列。
命令行（ue_commandlet.py）和编辑器插件共用 run_job(job)。

每段素材一个专用关卡 L_<素材>：把完整的 MetaHuman 蓝图真正放进关卡，再以 possessable 绑定
Body 组件。这样头、衣服、头发都在（模板式 spawnable 拿不到蓝图组件），也不碰用户正在编辑的关卡。

关键教训（都已踩过）：
- 重定向姿态只对齐手臂/手指；auto_align_all_bones 会让 MetaHuman 驼背 ~30°、低头 ~55°。
- UE 只按比例缩放骨盆的垂直运动，水平原样传递 → 统一的 scale_horizontal 让步幅匹配目标角色腿长。
- 同名资产删除后立刻 create_asset 会返回 None → 已存在就加载后重新配置，不删。
- 命令行无渲染：不能导出带网格的 FBX。"""
import json
import math
import os

import unreal

EAL = unreal.EditorAssetLibrary
AL = unreal.AnimationLibrary
S, T = unreal.RetargetSourceOrTarget.SOURCE, unreal.RetargetSourceOrTarget.TARGET
TAG = "AIMocap"

CHAINS = [("Spine", "spine_01", "spine_03", None), ("Neck", "neck_01", "neck_01", None), ("Head", "head", "head", None)]
for _Sd, _s in (("Left", "l"), ("Right", "r")):
    CHAINS += [(f"{_Sd}Leg", f"thigh_{_s}", f"foot_{_s}", f"{_Sd}FootIK"), (f"{_Sd}Foot", f"ball_{_s}", f"ball_{_s}", None),
               (f"{_Sd}Clavicle", f"clavicle_{_s}", f"clavicle_{_s}", None),
               (f"{_Sd}Arm", f"upperarm_{_s}", f"hand_{_s}", f"{_Sd}HandIK")]
    for _f in ("Thumb", "Index", "Middle", "Ring", "Pinky"):
        CHAINS.append((f"{_Sd}{_f}", f"{_f.lower()}_01_{_s}", f"{_f.lower()}_03_{_s}", None))
ARM = []
for _s in ("l", "r"):
    ARM += [f"clavicle_{_s}", f"upperarm_{_s}", f"lowerarm_{_s}", f"hand_{_s}"]
    for _f in ("thumb", "index", "middle", "ring", "pinky"):
        ARM += [f"{_f}_0{i}_{_s}" for i in (1, 2, 3)]
    ARM += [f"{_f}_metacarpal_{_s}" for _f in ("index", "middle", "ring", "pinky")]


def _log(*a):
    unreal.log("@@ " + " ".join(str(x) for x in a))


def _at():
    return unreal.AssetToolsHelpers.get_asset_tools()


def load_or_create(path, cls, factory):
    if EAL.does_asset_exist(path):
        return unreal.load_asset(path), False
    d, n = path.rsplit("/", 1)
    return _at().create_asset(n, d, cls, factory), True


def import_fbx(fbx, dest, fps):
    unreal.SystemLibrary.execute_console_command(None, "Interchange.FeatureFlags.Import.FBX False")
    ui = unreal.FbxImportUI()
    for k, v in dict(import_mesh=True, import_as_skeletal=True, import_animations=True, import_materials=False,
                     import_textures=False, create_physics_asset=False,
                     mesh_type_to_import=unreal.FBXImportType.FBXIT_SKELETAL_MESH).items():
        ui.set_editor_property(k, v)
    ad = ui.anim_sequence_import_data
    ad.set_editor_property("use_default_sample_rate", False)
    ad.set_editor_property("custom_sample_rate", fps)
    ad.set_editor_property("animation_length", unreal.FBXAnimationLengthImportType.FBXALIT_EXPORTED_TIME)
    t = unreal.AssetImportTask()
    for k, v in dict(filename=fbx, destination_path=dest, automated=True, replace_existing=True, save=True,
                     options=ui).items():
        t.set_editor_property(k, v)
    _at().import_asset_tasks([t])
    assets = [unreal.load_asset(x) for x in EAL.list_assets(dest, recursive=False)]
    return (next(x for x in assets if isinstance(x, unreal.SkeletalMesh)),
            next(x for x in assets if isinstance(x, unreal.AnimSequence)))


def open_clip_level(path):
    """打开（或新建）素材专用关卡，清掉上一次放进去的 AIMocap 角色。"""
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if EAL.does_asset_exist(path):
        les.load_level(path)
    else:
        les.new_level(path)
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for a in eas.get_all_level_actors():
        if a.actor_has_tag(TAG):
            eas.destroy_actor(a)
    return les


def body_component(actor):
    comps = actor.get_components_by_class(unreal.SkeletalMeshComponent)
    return next((c for c in comps if c.get_name().lower() == "body"), None) or \
        next((c for c in comps if "body" in c.get_name().lower()), None)


def spawn_character(person, k):
    """放一个 MetaHuman 蓝图到原点（动画里带世界坐标的根运动），返回 (actor, body 组件, 身体网格)。
    没配 mh_bp 时退回到只用身体网格的 SkeletalMeshActor。"""
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    if person.get("mh_bp"):
        bp = unreal.load_asset(person["mh_bp"])
        actor = eas.spawn_actor_from_class(bp.generated_class(), unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
        body = body_component(actor)
        if body is None:
            raise RuntimeError(f"{person['mh_bp']} 里找不到 Body 骨骼网格组件")
        mesh = body.get_skeletal_mesh_asset()
    else:
        mesh = unreal.load_asset(person["mh_mesh"])
        actor = eas.spawn_actor_from_class(unreal.SkeletalMeshActor, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
        body = actor.skeletal_mesh_component
        body.set_skeletal_mesh_asset(mesh)
    actor.tags = [TAG]
    actor.set_actor_label(f"{person['name']}_p{k}")
    return actor, body, mesh


def mh_rig(mesh, rd, cache):
    key = mesh.get_path_name()
    if key not in cache:
        rig, created = load_or_create(f"{rd}/IK_MH_{mesh.get_name()}", unreal.IKRigDefinition, unreal.IKRigDefinitionFactory())
        c = unreal.IKRigController.get_controller(rig)
        if created or not c.get_retarget_chains():
            c.set_skeletal_mesh(mesh)
            c.apply_auto_generated_retarget_definition()
            c.apply_auto_fbik()
            EAL.save_loaded_asset(rig)
        cache[key] = rig
    return cache[key]


def source_rig(path, mesh):
    rig, created = load_or_create(path, unreal.IKRigDefinition, unreal.IKRigDefinitionFactory())
    c = unreal.IKRigController.get_controller(rig)
    c.set_skeletal_mesh(mesh)
    if created or not c.get_retarget_chains():
        c.set_retarget_root("pelvis")
        for name, a, b, goal in CHAINS:          # 与 MetaHuman 自动 IK Rig 完全同名，EXACT 映射
            if goal:
                c.add_new_goal(goal, b)
            c.add_retarget_chain(name, a, b, goal or "")
    EAL.save_loaded_asset(rig)
    return rig


def ref_z(rig, bone):
    return unreal.IKRigController.get_controller(rig).get_ref_pose_transform_of_bone(bone).translation.z


def retarget(p, cd, k, kh):
    rtg, created = load_or_create(f"{cd}/RTG_p{k}", unreal.IKRetargeter, unreal.IKRetargetFactory())
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
        [EAL.find_asset_data(p["anim"].get_path_name())], p["mesh"], p["tmesh"], rtg, "", "", "MH_", "", cd,
        False, False, True)
    return unreal.load_asset(str(out[0].package_name))


def _world(a, chain, f):
    w, pos = None, {}
    for b in chain:
        t = AL.get_bone_pose_for_frame(a, b, f, False)
        w = t if w is None else t.multiply(w)
        pos[b] = w.translation
    return pos


def _tilt(v):
    return math.degrees(math.acos(max(-1, min(1, v.z / max(v.length(), 1e-6)))))


def _ang(u, v):
    return math.degrees(math.acos(max(-1, min(1, u.dot(v) / max(u.length() * v.length(), 1e-6)))))


def measure(people, kh):
    SSP = ["root", "pelvis", "spine_01", "spine_02", "spine_03", "neck_01", "head"]
    MSP = ["root", "pelvis", "spine_01", "spine_02", "spine_03", "spine_04", "spine_05", "neck_01", "neck_02", "head"]
    SAR = ["root", "pelvis", "spine_01", "spine_02", "spine_03", "clavicle_{s}", "upperarm_{s}", "lowerarm_{s}", "hand_{s}"]
    MAR = ["root", "pelvis", "spine_01", "spine_02", "spine_03", "spine_04", "spine_05", "clavicle_{s}", "upperarm_{s}",
           "lowerarm_{s}", "hand_{s}"]
    nf = min(AL.get_num_frames(p["mh_anim"]) for p in people)
    FR = list(range(0, nf, max(1, nf // 24)))
    res = {"persons": [], "frames": nf, "horizontal_scale": round(kh, 4)}
    for k, p in enumerate(people):
        rs_c, rm_c = unreal.IKRigController.get_controller(p["rig"]), unreal.IKRigController.get_controller(p["trig"])
        rs = _tilt(rs_c.get_ref_pose_transform_of_bone("head").translation - rs_c.get_ref_pose_transform_of_bone("neck_01").translation)
        rm = _tilt(rm_c.get_ref_pose_transform_of_bone("head").translation - rm_c.get_ref_pose_transform_of_bone("neck_01").translation)
        dt, dh, da = [], [], []
        p["src_pelvis"], p["mh_pelvis"] = [], []
        for f in FR:
            s1, m1 = _world(p["anim"], SSP, f), _world(p["mh_anim"], MSP, f)
            dt.append(_tilt(m1["neck_01"] - m1["pelvis"]) - _tilt(s1["neck_01"] - s1["pelvis"]))
            dh.append((_tilt(m1["head"] - m1["neck_01"]) - rm) - (_tilt(s1["head"] - s1["neck_01"]) - rs))
            p["src_pelvis"].append(s1["pelvis"])
            p["mh_pelvis"].append(m1["pelvis"])
            for sd in ("l", "r"):
                sa = _world(p["anim"], [b.format(s=sd) for b in SAR], f)
                ma = _world(p["mh_anim"], [b.format(s=sd) for b in MAR], f)
                da.append(_ang(ma[f"lowerarm_{sd}"] - ma[f"upperarm_{sd}"], sa[f"lowerarm_{sd}"] - sa[f"upperarm_{sd}"]))
                da.append(_ang(ma[f"hand_{sd}"] - ma[f"lowerarm_{sd}"], sa[f"hand_{sd}"] - sa[f"lowerarm_{sd}"]))
        m = lambda x: round(sum(x) / len(x), 2)
        mx = lambda x: round(max(x, key=abs), 2)
        res["persons"].append({"p": k, "character": p["cfg"].get("mh_bp") or p["cfg"].get("mh_mesh"),
                               "anim": p["mh_anim"].get_path_name(), "torso_err_mean": m(dt), "torso_err_max": mx(dt),
                               "head_err_mean": m(dh), "head_err_max": mx(dh), "arm_err_mean": m(da), "arm_err_max": mx(da),
                               "pelvis_ratio": round(p["ratio"], 4)})
    if len(people) >= 2:
        rat = []
        a, b = people[0], people[1]
        for i in range(len(FR)):
            ds = math.hypot(a["src_pelvis"][i].x - b["src_pelvis"][i].x, a["src_pelvis"][i].y - b["src_pelvis"][i].y)
            dm = math.hypot(a["mh_pelvis"][i].x - b["mh_pelvis"][i].x, a["mh_pelvis"][i].y - b["mh_pelvis"][i].y)
            if ds > 1:
                rat.append(dm / ds)
        rat.sort()
        res["spacing_ratio_median"] = round(rat[len(rat) // 2], 4)
        res["spacing_ratio_expected"] = round(kh, 4)
    return res


def build_sequence(job, people, nf):
    seq, created = load_or_create(f"{job['content_dir']}/LS_{job['clip']}", unreal.LevelSequence,
                                  unreal.LevelSequenceFactoryNew())
    if not created:
        for b in list(seq.get_bindings()):
            b.remove()
        get_t = getattr(seq, "get_tracks", None) or getattr(seq, "get_master_tracks")
        rm_t = getattr(seq, "remove_track", None) or getattr(seq, "remove_master_track")
        for t in list(get_t()):
            rm_t(t)
    seq.set_display_rate(unreal.FrameRate(job["fps"], 1))
    seq.set_playback_start(0)
    seq.set_playback_end(nf)
    for p in people:
        seq.add_possessable(p["actor"])
        cb = seq.add_possessable(p["body"])          # 自动挂到角色绑定之下
        tr = cb.add_track(unreal.MovieSceneSkeletalAnimationTrack)
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
    fb.set_editor_property("sensor_height", 36.0 * job["res"][1] / job["res"][0])
    cc.set_editor_property("filmback", fb)
    cc.set_editor_property("current_focal_length", float(job["lens"]))
    fs = cc.get_editor_property("focus_settings")
    fs.set_editor_property("focus_method", unreal.CameraFocusMethod.DISABLE)
    cc.set_editor_property("focus_settings", fs)
    csec = cam.add_track(unreal.MovieScene3DTransformTrack).add_section()
    csec.set_range(0, nf)
    ch = csec.get_all_channels()
    for i, v in enumerate(job["cam_ue"]):
        ch[i].set_default(float(v))
    cut = (getattr(seq, "add_track", None) or getattr(seq, "add_master_track"))(unreal.MovieSceneCameraCutTrack)
    cs = cut.add_section()
    cs.set_range(0, nf)
    cs.set_camera_binding_id(seq.get_binding_id(cam))
    EAL.save_loaded_asset(seq)
    return seq


def export_anims(people, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    for k, p in enumerate(people):
        t = unreal.AssetExportTask()
        opt = unreal.FbxExportOption()
        opt.set_editor_property("export_preview_mesh", False)
        for kk, vv in dict(object=p["mh_anim"], filename=os.path.join(out_dir, f"MH_p{k}.fbx"),
                           exporter=unreal.AnimSequenceExporterFBX(), options=opt, automated=True,
                           replace_identical=True, prompt=False).items():
            t.set_editor_property(kk, vv)
        unreal.Exporter.run_asset_export_task(t)


def run_job(job, log=_log, step=lambda msg: None):
    """完整执行一次 UE 阶段，结果写到 job['result'] 并返回。step(msg) 用于进度提示。"""
    cd, rd = job["content_dir"], job["retarget_dir"]
    step("导入 FBX")
    people = []
    for k, fbx in enumerate(job["fbx"]):
        mesh, anim = import_fbx(fbx, f"{cd}/p{k}", job["fps"])
        people.append(dict(mesh=mesh, anim=anim, cfg=job["persons"][k]))
        log(f"p{k} imported", anim.get_path_name(), "frames", AL.get_num_frames(anim))
    step("准备素材关卡和角色")
    les = open_clip_level(f"{cd}/L_{job['clip']}")
    cache = {}
    for k, p in enumerate(people):
        p["actor"], p["body"], p["tmesh"] = spawn_character(p["cfg"], k)
        p["rig"] = source_rig(f"{cd}/IK_SMPLX_p{k}", p["mesh"])
        p["trig"] = mh_rig(p["tmesh"], rd, cache)
        p["ratio"] = ref_z(p["trig"], "pelvis") / ref_z(p["rig"], "pelvis")
    kh = sum(p["ratio"] for p in people) / len(people) if job.get("uniform_horizontal_scale", True) else 1.0
    if job.get("force_horizontal_scale"):
        kh = float(job["force_horizontal_scale"])
    log("pelvis ratios", [round(p["ratio"], 3) for p in people], "horizontal scale", round(kh, 3))
    for k, p in enumerate(people):
        step(f"重定向 p{k}")
        p["mh_anim"] = retarget(p, cd, k, kh)
        log(f"p{k} retargeted", p["mh_anim"].get_path_name())
    step("度量")
    res = measure(people, kh)
    step("关卡序列")
    seq = build_sequence(job, people, res["frames"])
    les.save_current_level()
    res["sequence"] = seq.get_path_name()
    res["level"] = f"{cd}/L_{job['clip']}"
    step("导出动画")
    export_anims(people, job["export_dir"])
    unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
    res["ok"] = True
    with open(job["result"], "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    log("DONE")
    return res
