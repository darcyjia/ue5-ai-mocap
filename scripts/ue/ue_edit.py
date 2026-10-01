"""把 Blender 运镜预演导进 UE：成片序列 LS_<素材>_edit（镜头轨道）+ 每个镜头一个子序列（相机 + 镜头切换 + 表演）。
表演 = LS_<素材> 的副本（去掉原机位相机和原声），各镜头按剪辑表从对应的动画帧开始播；
开场定格 = 循环播放表演的第 1 帧；重复剪辑 = 多个镜头指向同一段动画。原声放在成片序列上，按剪辑表逐段对齐。
相机数据来自 Blender 的 export_cams_ue.py（cameras_ue.json，UE 坐标）。"""
import json
import time

import unreal

EAL = unreal.EditorAssetLibrary
TICK = 1000                                       # 24fps 序列的 tick 分辨率 24000 → 一帧 1000 tick


def _at():
    return unreal.AssetToolsHelpers.get_asset_tools()


def _new_seq(name, folder, n, fps):
    s = _at().create_asset(name, folder, unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
    s.set_display_rate(unreal.FrameRate(fps, 1))
    s.set_playback_start(0)
    s.set_playback_end(n)
    return s


def _root_tracks(s):
    return list((getattr(s, "get_tracks", None) or getattr(s, "get_master_tracks"))())


def _rm_root(s, t):
    (getattr(s, "remove_track", None) or getattr(s, "remove_master_track"))(t)


def _unwrap(a):
    out = [a[0]]
    for x in a[1:]:
        d = (x - out[-1] + 180) % 360 - 180
        out.append(out[-1] + d)
    return out


def make_perf(src, folder, stamp, log):
    """表演序列：复制 LS_<素材>，删掉原机位相机、镜头切换和原声。"""
    perf = _at().duplicate_asset(f"{src.get_name()}_perf_{stamp}", folder, src)
    for t in _root_tracks(perf):
        if isinstance(t, (unreal.MovieSceneCameraCutTrack, unreal.MovieSceneAudioTrack)):
            _rm_root(perf, t)
    for b in list(perf.get_bindings()):
        if str(b.get_display_name()) == "OrigCam":
            b.remove()
    return perf


def build_shot(sh, perf, perf_frames, folder, fps, log, aspect=16 / 9):
    n = sh["frames"]
    seq = _new_seq(f"SH_{sh['id']}", folder, n, fps)
    cam = seq.add_spawnable_from_class(unreal.CineCameraActor)
    cam.set_display_name(f"CAM_{sh['id']}")
    cc = cam.get_object_template().get_editor_property("camera_component")
    fb = cc.get_editor_property("filmback")
    fb.set_editor_property("sensor_width", 36.0)
    fb.set_editor_property("sensor_height", 36.0 / aspect)      # 画幅与预演一致（宽 36mm 固定，高按比例）
    cc.set_editor_property("filmback", fb)
    cc.set_editor_property("current_focal_length", float(sh["lens"]))
    fs = cc.get_editor_property("focus_settings")
    fs.set_editor_property("focus_method", unreal.CameraFocusMethod.DISABLE)
    cc.set_editor_property("focus_settings", fs)
    ch = cam.add_track(unreal.MovieScene3DTransformTrack).add_section()
    ch.set_range(0, n)
    chans = ch.get_all_channels()
    lin = unreal.MovieSceneKeyInterpolation.LINEAR
    rot = list(zip(*sh["rot"]))                    # roll, pitch, yaw
    cols = list(zip(*sh["loc"])) + [rot[0], rot[1], _unwrap(list(rot[2]))]
    for ci, vals in enumerate(cols):
        for i, v in enumerate(vals):
            chans[ci].add_key(time=unreal.FrameNumber(i), new_value=float(v), interpolation=lin)
    cut = seq.add_track(unreal.MovieSceneCameraCutTrack).add_section()
    cut.set_range(0, n)
    cut.set_camera_binding_id(seq.get_binding_id(cam))
    sub = seq.add_track(unreal.MovieSceneSubTrack).add_section()
    sub.set_sequence(perf)
    sub.set_range(0, n)
    p = sub.get_editor_property("parameters")
    if sh["hold"]:                                 # 定格：循环播放表演的第 1 帧
        p.set_editor_property("start_frame_offset", unreal.FrameNumber(0))
        p.set_editor_property("end_frame_offset", unreal.FrameNumber((perf_frames - 1) * TICK))
        p.set_editor_property("can_loop", True)
    else:
        p.set_editor_property("start_frame_offset", unreal.FrameNumber((sh["anim_frames"][0] - 1) * TICK))
    sub.set_editor_property("parameters", p)
    return seq


def import_edit(clip_dir, content_dir, clip, log=print, step=lambda m: None, save=True, cams=None):
    data = json.load(open(cams or f"{clip_dir}/blender/cameras_ue.json", encoding="utf-8"))
    fps = data["fps"]
    src = unreal.load_asset(f"{content_dir}/LS_{clip}")
    if src is None:
        raise RuntimeError(f"找不到 {content_dir}/LS_{clip}：先用「换角色 / 重做重定向…」跑一次 UE 部分")
    stamp = time.strftime("%m%d_%H%M%S")
    folder = f"{content_dir}/edit_{stamp}"        # 每次新目录：同名资产删了再建会拿到 None
    step("表演序列")
    perf = make_perf(src, folder, stamp, log)
    perf_frames = src.get_playback_end() - src.get_playback_start()
    sound = None
    for t in _root_tracks(src):
        if isinstance(t, unreal.MovieSceneAudioTrack) and t.get_sections():
            sound = t.get_sections()[0].get_sound()
    edit = _new_seq(f"LS_{clip}_edit", folder, data["film_frames"], fps)
    shots = edit.add_track(unreal.MovieSceneCinematicShotTrack)
    audio = edit.add_track(unreal.MovieSceneAudioTrack) if sound else None
    for i, sh in enumerate(data["shots"]):
        step(f"镜头 {sh['id']}")
        seq = build_shot(sh, perf, perf_frames, f"{folder}/shots", fps, log, data.get("aspect", 16 / 9))
        a, n = sh["film_start"], sh["frames"]
        sec = shots.add_section()
        sec.set_sequence(seq)
        sec.set_range(a, a + n)
        sec.set_shot_display_name(sh["id"])
        if audio and not sh["hold"]:
            asec = audio.add_section()
            asec.set_sound(sound)
            asec.set_range(a, a + n)
            asec.set_start_offset(unreal.FrameNumber((sh["anim_frames"][0] - 1) * TICK))
        if save:
            EAL.save_loaded_asset(seq)
    if save:
        EAL.save_loaded_asset(perf)
        EAL.save_loaded_asset(edit)
    log(f"edit imported: {edit.get_path_name()} shots {len(data['shots'])} frames {data['film_frames']}")
    return edit
