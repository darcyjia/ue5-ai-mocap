"""UE 端：导入 FBX → IK Rig → 重定向到 MetaHuman → 度量 → 专用关卡 + 关卡序列。
命令行（ue_commandlet.py）和编辑器插件共用 run_job(job)。

每段素材一个专用关卡 L_<素材>：把完整的 MetaHuman 蓝图真正放进关卡，再以 possessable 绑定
Body 组件。这样头、衣服、头发都在（模板式 spawnable 拿不到蓝图组件），也不碰用户正在编辑的关卡。

关键教训（都已踩过）：
- 重定向姿态只对齐手臂/手指；auto_align_all_bones 会让 MetaHuman 驼背 ~30°、低头 ~55°。
- UE 只按比例缩放骨盆的垂直运动，水平原样传递 → 统一的 scale_horizontal 让步幅匹配目标角色腿长。
- 同名资产删除后立刻 create_asset 会返回 None → 已存在就加载后重新配置，不删。
- 命令行无渲染：不能导出带网格的 FBX；也不能加面部控制板轨道（Control Rig 编辑器要 Slate，会断言崩溃）→ 表情只在编辑器插件里加。
- 对已存在的骨骼网格再导入同一个 FBX，UE 走 atomic reimport：只重导网格，**不重导动画**，
  会一直用第一次导入的旧动作 → 源资产按 FBX 指纹放进新目录 src/p<k>_<指纹>，用完删掉旧目录。"""
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


def fbx_dest(cd, k, fbx):
    st = os.stat(fbx)
    return f"{cd}/src/p{k}_{st.st_size:x}{st.st_mtime_ns // 1000000 % (1 << 32):08x}"


def cleanup_sources(cd, keep, log):
    """删掉不再使用的源资产目录（旧指纹的 src/p*_*，以及早期版本放在 <素材>/p<k> 的）。"""
    old = [d for d in EAL.list_assets(f"{cd}/src", recursive=True, include_folder=True) if d.endswith("/")]
    old = sorted({d.rstrip("/") for d in old} - set(keep))
    old += [f"{cd}/p{k}" for k in range(len(keep)) if EAL.does_directory_exist(f"{cd}/p{k}")]
    for d in old:
        try:
            EAL.delete_directory(d)
            log("deleted old source", d)
        except Exception as ex:
            log("could not delete", d, ex)


def audio_dest(cd, wav):
    st = os.stat(wav)
    return f"{cd}/src/audio_{st.st_size:x}{st.st_mtime_ns // 1000000 % (1 << 32):08x}"


def import_audio(wav, dest):
    """视频原声 → SoundWave。和 FBX 一样按指纹放新目录，避免再导入时沿用旧资产。"""
    if EAL.does_directory_exist(dest):
        s = [unreal.load_asset(x) for x in EAL.list_assets(dest, recursive=False)]
        s = next((x for x in s if isinstance(x, unreal.SoundWave)), None)
        if s:
            return s
    t = unreal.AssetImportTask()
    for k, v in dict(filename=wav, destination_path=dest, destination_name="audio", automated=True,
                     replace_existing=True, save=True).items():
        t.set_editor_property(k, v)
    _at().import_asset_tasks([t])
    return next((a for a in (unreal.load_asset(x) for x in EAL.list_assets(dest, recursive=False))
                 if isinstance(a, unreal.SoundWave)), None)


def import_fbx(fbx, dest, fps):
    existing = [unreal.load_asset(x) for x in EAL.list_assets(dest, recursive=False)]         if EAL.does_directory_exist(dest) else []
    mesh = next((x for x in existing if isinstance(x, unreal.SkeletalMesh)), None)
    anim = next((x for x in existing if isinstance(x, unreal.AnimSequence)), None)
    if mesh and anim:                     # 同一个 FBX 已导入过
        return mesh, anim
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


def face_component(actor):
    comps = actor.get_components_by_class(unreal.SkeletalMeshComponent)
    return (next((c for c in comps if c.get_name().lower() == "face"), None)
            or next((c for c in comps if "face" in c.get_name().lower()), None))


def _key_points(vals, eps=1e-3):
    """只保留拐点（线性插值误差超过 eps 的点），恒定曲线只留首帧。"""
    n = len(vals)
    if n == 0:
        return []
    if max(vals) - min(vals) < eps:
        return [0]
    keep, a = [0], 0
    for i in range(2, n):
        # a → i 连线上，中间各点的误差
        va, vi = vals[a], vals[i]
        bad = any(abs(vals[j] - (va + (vi - va) * (j - a) / (i - a))) > eps for j in range(a + 1, i))
        if bad:
            keep.append(i - 1)
            a = i - 1
    keep.append(n - 1)
    return keep


def add_face_track(seq, binding, face, data, log):
    """表情：在 Face 组件上挂它的面部控制板（MetaHuman 的 Face_ControlBoard_CtrlRig），把曲线直接写进轨道通道
    （set_local_control_rig_* 需要序列在 Sequencer 里打开且绑定到它，实测不打开时 0 个关键帧）。
    二维控件的通道名是 控件名.X / .Y。只写拐点、线性插值。"""
    lib = unreal.ControlRigSequencerLibrary
    rig_bp = face.get_skeletal_mesh_asset().get_editor_property("default_animating_rig")
    if rig_bp is None:
        log("face: no default animating rig, skipped")
        return 0
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    track = lib.find_or_create_control_rig_track(world, seq, rig_bp.generated_class(), binding)
    secs = track.get_sections() if track else []
    if not secs:
        log("face: control rig track has no section, skipped")
        return 0
    chans = {str(c.channel_name): c for c in secs[0].get_all_channels()}
    curves = dict(data["float"])
    for name, vv in data["vec2"].items():
        curves[name + ".X"] = [a for a, _ in vv]
        curves[name + ".Y"] = [b for _, b in vv]
    lin = unreal.MovieSceneKeyInterpolation.LINEAR
    written, keys, missing = 0, 0, []
    for name, vals in curves.items():
        ch = chans.get(name)
        if ch is None:
            missing.append(name)
            continue
        for i in _key_points(vals):
            ch.add_key(time=unreal.FrameNumber(i), new_value=float(vals[i]), interpolation=lin)
            keys += 1
        written += 1
    if missing:
        log("face: channels not found", missing[:8])
    log(f"face: {written} channels, {keys} keys")
    return written


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


def build_sequence(job, people, nf, sound=None, log=_log):
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
        fdata = None if job.get("headless") else (job.get("face") or [None] * len(people))[people.index(p)]
        face = face_component(p["actor"]) if fdata else None
        if face is not None:
            if not job.get("headless"):          # 控制板轨道要求序列在 Sequencer 里打开
                unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(seq)
            fb = seq.add_possessable(face)
            nch = add_face_track(seq, fb, face, json.load(open(fdata, encoding="utf-8")), log)
            log(f"face p{people.index(p)}: {nch} channels")
    if sound:                                       # 原声从第 0 帧开始，不变速（动画与视频逐帧对应）
        at = (getattr(seq, "add_track", None) or getattr(seq, "add_master_track"))(unreal.MovieSceneAudioTrack)
        at.set_display_name("原声")
        asec = at.add_section()
        asec.set_sound(sound)
        asec.set_range(0, nf)
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


def export_meshes(people, job, log):
    """给 Blender 预演用：把每个角色的骨骼网格（Body / Face / 衣服）导出成 FBX，按蓝图名缓存，已有就跳过。
    只在编辑器里做（命令行无渲染，导出骨骼网格会 MeshObject 断言崩溃）。写 export_dir/meshes_p<k>.json 清单。"""
    root = job.get("mesh_dir")
    if not root:
        return
    for k, p in enumerate(people):
        bp = (p["cfg"].get("mh_bp") or "").rsplit("/", 1)[-1] or f"p{k}"
        d = os.path.join(root, bp)
        os.makedirs(d, exist_ok=True)
        files = {}
        for comp in p["actor"].get_components_by_class(unreal.SkeletalMeshComponent):
            mesh = comp.get_skeletal_mesh_asset()
            if mesh is None:
                continue
            name = comp.get_name().replace("_GEN_VARIABLE", "")
            key = "body" if name.lower() == "body" else "face" if "face" in name.lower() else mesh.get_name()
            fn = os.path.join(d, f"{key}.fbx")
            if not os.path.exists(fn):
                t = unreal.AssetExportTask()
                for kk, vv in dict(object=mesh, filename=fn, exporter=unreal.SkeletalMeshExporterFBX(),
                                   options=unreal.FbxExportOption(), automated=True, replace_identical=True,
                                   prompt=False).items():
                    t.set_editor_property(kk, vv)
                ok = unreal.Exporter.run_asset_export_task(t)
                log("mesh export", bp, key, "ok" if ok else "FAILED")
            if os.path.exists(fn):
                files[key] = fn
        with open(os.path.join(job["export_dir"], f"meshes_p{k}.json"), "w", encoding="utf-8") as f:
            json.dump({"bp": bp, "anim": os.path.join(job["export_dir"], f"MH_p{k}.fbx"), "meshes": files}, f,
                      ensure_ascii=False, indent=1)


def run_job(job, log=_log, step=lambda msg: None):
    """完整执行一次 UE 阶段，结果写到 job['result'] 并返回。step(msg) 用于进度提示。"""
    cd, rd = job["content_dir"], job["retarget_dir"]
    step("导入 FBX")
    people = []
    for k, fbx in enumerate(job["fbx"]):
        mesh, anim = import_fbx(fbx, fbx_dest(cd, k, fbx), job["fps"])
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
    sound = import_audio(job["audio"], audio_dest(cd, job["audio"])) if job.get("audio") else None
    log("audio", sound.get_path_name() if sound else None)
    seq = build_sequence(job, people, res["frames"], sound, log)
    if job.get("headless") and any(job.get("face") or []):
        log("face: skipped in command-line mode; use the editor plugin (AI 动捕) to add facial animation")
    res["audio"] = sound.get_path_name() if sound else None
    les.save_current_level()
    res["sequence"] = seq.get_path_name()
    res["level"] = f"{cd}/L_{job['clip']}"
    step("导出动画")
    export_anims(people, job["export_dir"])
    if not job.get("headless"):
        step("导出 MetaHuman 网格（Blender 预演用）")
        export_meshes(people, job, log)
    unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
    keep = [fbx_dest(cd, k, f) for k, f in enumerate(job["fbx"])]
    cleanup_sources(cd, keep + ([audio_dest(cd, job["audio"])] if job.get("audio") else []), log)
    res["ok"] = True
    with open(job["result"], "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    log("DONE")
    return res
