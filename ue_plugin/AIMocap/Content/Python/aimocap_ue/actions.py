"""菜单动作。"""
import importlib
import json
import re
from pathlib import Path

import unreal

from . import core, forms

YES, NO, OK = unreal.AppReturnType.YES, unreal.AppReturnType.NO, unreal.AppReturnType.OK
DEFAULT_MH = "/Game/MetaHumans/NewMetaHumanCharacter/BP_NewMetaHumanCharacter"


def _msg(title, text, kind=unreal.AppMsgType.OK, default=OK):
    return unreal.EditorDialog.show_message(title, text, kind, default)


def _default_characters(last):
    persons = core.config().get("person", [])
    d = [p.get("mh_bp") for p in persons] + [DEFAULT_MH, DEFAULT_MH]
    return last.get("left", d[0]), last.get("right", d[1])


def _guard():
    if core.busy():
        _msg("AI 动捕", f"已有任务在跑：{core.CURRENT.title}（{core.CURRENT.stage}，{core.CURRENT.elapsed():.0f}s）。\n"
                        "可以在「任务状态」里查看。")
        return False
    return True


def _write_persons(clip, left, right):
    d = core.clip_dir(clip) / "input"
    d.mkdir(parents=True, exist_ok=True)
    (d / "persons.json").write_text(json.dumps(
        [{"name": "left", "mh_bp": forms.asset_path(left)}, {"name": "right", "mh_bp": forms.asset_path(right)}],
        ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------- 新建动捕 ----------------
def new_job():
    if not _guard():
        return
    last = forms.load_last()
    f = unreal.new_object(forms.AIMocapNewJob)
    f.clip_name = last.get("clip_name", "")
    f.source = [forms.AIMocapSource.EXISTING_VIDEO, forms.AIMocapSource.GENERATE][last.get("source", 0)]
    f.resolution = [forms.AIMocapResolution.R480, forms.AIMocapResolution.R720, forms.AIMocapResolution.R1080][last.get("res", 0)]
    f.video = forms.fp(last.get("video"))
    f.prompt_file = forms.fp(last.get("prompt_file"))
    f.plate_image = forms.fp(last.get("plate_image"))
    f.duration = last.get("duration", 15)
    l, r = _default_characters(last)
    f.left_character, f.right_character = forms.bp(l), forms.bp(r)
    f.blender_preview = last.get("blender_preview", True)
    if not forms.show("AI 动捕：新建", f):
        return
    src = 1 if f.source == forms.AIMocapSource.GENERATE else 0
    res_i = [forms.AIMocapResolution.R480, forms.AIMocapResolution.R720, forms.AIMocapResolution.R1080].index(f.resolution)
    forms.save_last({"clip_name": f.clip_name, "source": src, "video": f.video.file_path,
                     "prompt_file": f.prompt_file.file_path, "plate_image": f.plate_image.file_path,
                     "duration": f.duration, "res": res_i, "left": forms.asset_path(f.left_character),
                     "right": forms.asset_path(f.right_character), "blender_preview": f.blender_preview})
    clip = f.clip_name.strip()
    if not re.fullmatch(r"[A-Za-z0-9_]+", clip):
        return _msg("AI 动捕", "素材名只能用英文、数字、下划线。")
    if not (f.left_character and f.right_character):
        return _msg("AI 动捕", "请选两个 MetaHuman 蓝图。")
    if core.clip_dir(clip).exists() and _msg("AI 动捕", f"素材「{clip}」已存在，继续会在它的基础上重跑（已完成的阶段会跳过）。继续？",
                                              unreal.AppMsgType.YES_NO, NO) != YES:
        return
    run_args = ["run", clip, "--to", "fbx"]
    if not f.blender_preview:
        run_args.append("--no-preview")
    if src == 0:
        if not Path(f.video.file_path).exists():
            return _msg("AI 动捕", "视频文件不存在。")
        code, out = core.cli(["new", clip, "--video", f.video.file_path])
    else:
        if not (Path(f.prompt_file.file_path).exists() and Path(f.plate_image.file_path).exists()):
            return _msg("AI 动捕", "请选编排提示词 txt 和构图板图片。")
        res = forms.RES_NAME[res_i]
        q = core.cli_json(["quote", "--resolution", res, "--duration", str(f.duration)])
        if q["balance"] is None:
            return _msg("AI 动捕", "读不到即梦的登录状态（没有提交，也没有扣费）。\n"
                                   "稍等一两分钟再试；仍然不行就在终端运行 dreamina login 重新登录。")
        if q["estimate"] > q["max_credits"]:
            return _msg("AI 动捕", f"预估 {q['estimate']} 积分，超过配置的上限 {q['max_credits']}。")
        if _msg("确认花费积分", f"用 Seedance 生成 {res}、{f.duration} 秒的视频：\n\n预估 {q['estimate']} 积分，"
                             f"当前余额 {q['balance']}。\n失败的任务也可能扣费。\n\n确定生成？",
                unreal.AppMsgType.YES_NO, NO) != YES:
            return
        code, out = core.cli(["new", clip, "--prompt", f.prompt_file.file_path, "--plate", f.plate_image.file_path])
        (core.clip_dir(clip) / "input" / "generate.json").write_text(
            json.dumps({"resolution": res, "duration": f.duration}), encoding="utf-8")
        run_args.append("--allow-spend")
    if code != 0:
        return _msg("AI 动捕", "建立素材失败：\n" + out[-1200:])
    _write_persons(clip, f.left_character, f.right_character)
    core.start(f"新建动捕 {clip}", clip, run_args, _after_background)
    _msg("AI 动捕", f"已在后台开始处理「{clip}」。\n进度在 Output Log（搜索「AI 动捕」），"
                    "或看菜单里的「任务状态」。\n\n解算大约 5–8 分钟，期间可以继续用编辑器；"
                    "完成后会自动切换到素材专用关卡并打开关卡序列。")


def _after_background(job, ok):
    if not ok:
        tail = "\n".join(job.lines[-25:])
        return _msg("AI 动捕：失败", f"「{job.clip}」在「{job.stage}」阶段失败：\n\n{tail}")
    finish_in_editor(job.clip)


# ---------------- 编辑器内的 UE 阶段 ----------------
def finish_in_editor(clip):
    import ue_pipeline
    importlib.reload(ue_pipeline)
    job = core.cli_json(["uejob", clip])
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    cur = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    if cur and cur.get_outermost().is_dirty() and _msg(
            "AI 动捕", "当前关卡有未保存的修改。接下来会切换到素材专用关卡，是否先保存当前关卡？",
            unreal.AppMsgType.YES_NO, YES) == YES:
        les.save_current_level()
    with unreal.ScopedSlowTask(8, f"AI 动捕：{clip} 重定向到 MetaHuman") as task:
        task.make_dialog(True)
        res = ue_pipeline.run_job(job, step=lambda m: task.enter_progress_frame(1, f"AI 动捕：{m}"))
    core.cli(["mark", clip, "ue"])
    core.cli(["run", clip, "--only", "qc"])
    seq = unreal.load_asset(res["sequence"])
    unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(seq)
    _summary(clip, res)


def _summary(clip, res):
    m_path = core.clip_dir(clip) / "qc" / "metrics.json"
    m = json.loads(m_path.read_text(encoding="utf-8")) if m_path.exists() else {"status": "?", "checks": []}
    bad = [c for c in m["checks"] if c["status"] in ("fail", "warn")]
    lines = [f"质检结果：{m['status'].upper()}", ""]
    for r in res["persons"]:
        lines.append(f"p{r['p']}：躯干误差 {r['torso_err_mean']:+.1f}°，头部 {r['head_err_mean']:+.1f}°，"
                     f"手臂 {r['arm_err_mean']:.1f}°")
    lines.append(f"两人间距比 {res.get('spacing_ratio_median')}（水平缩放 {res['horizontal_scale']}）")
    if bad:
        lines += ["", "需要注意："] + [f"  [{c['status']}] {c['name']} = {c['value']}" for c in bad[:10]]
    lines += ["", f"关卡：{res.get('level')}", f"序列：{res['sequence']}", "", "打开质检报告？"]
    if _msg(f"AI 动捕：{clip} 完成", "\n".join(lines), unreal.AppMsgType.YES_NO, YES) == YES:
        core.open_path(core.clip_dir(clip) / "qc" / "report.html")


# ---------------- 换角色 / 重做重定向 ----------------
def redo():
    if not _guard():
        return
    last = forms.load_last()
    f = unreal.new_object(forms.AIMocapRedo)
    f.clip_folder = forms.dp(last.get("redo_folder") or str(core.work_root()))
    l, r = _default_characters(last)
    f.left_character, f.right_character = forms.bp(l), forms.bp(r)
    if not forms.show("AI 动捕：换角色 / 重做重定向", f):
        return
    folder = Path(f.clip_folder.path)
    forms.save_last({"redo_folder": str(folder), "left": forms.asset_path(f.left_character),
                     "right": forms.asset_path(f.right_character)})
    if not (folder / "fbx" / "p0.fbx").exists():
        return _msg("AI 动捕", f"{folder} 里没有 fbx/p0.fbx，这个素材还没跑到导出阶段。")
    _write_persons(folder.name, f.left_character, f.right_character)
    finish_in_editor(folder.name)


# ---------------- 构图板候选（免费） ----------------
def plates():
    if not _guard():
        return
    last = forms.load_last()
    f = unreal.new_object(forms.AIMocapPlates)
    f.clip_name = last.get("clip_name", "")
    f.prompt_file = forms.fp(last.get("plate_prompt"))
    f.count = 4
    if not forms.show("AI 动捕：出构图板候选（免费）", f):
        return
    forms.save_last({"clip_name": f.clip_name, "plate_prompt": f.prompt_file.file_path})
    clip = f.clip_name.strip()
    if not re.fullmatch(r"[A-Za-z0-9_]+", clip) or not Path(f.prompt_file.file_path).exists():
        return _msg("AI 动捕", "请填素材名（英文数字下划线）并选构图板提示词文件。")

    def done(job, ok):
        if ok:
            core.open_path(core.clip_dir(clip) / "input" / "plates")
        else:
            _msg("AI 动捕：失败", "\n".join(job.lines[-20:]))
    core.start(f"构图板 {clip}", clip, ["plate", clip, "--prompt", f.prompt_file.file_path, "--n", str(f.count)], done)


# ---------------- 其它 ----------------
def status():
    j = core.CURRENT
    if j is None:
        return _msg("AI 动捕", "本次打开编辑器后还没有运行过任务。")
    state = "进行中" if j.running else ("成功" if j.proc.returncode == 0 else "失败")
    _msg("AI 动捕：任务状态", f"{j.title}\n状态：{state}　阶段：{j.stage}　用时：{j.elapsed():.0f}s\n\n"
                           + "\n".join(j.lines[-18:]))


def _pick_clip(title):
    last = forms.load_last()
    f = unreal.new_object(forms.AIMocapPickClip)
    f.clip_folder = forms.dp(last.get("report_folder") or str(core.work_root()))
    if not forms.show(title, f):
        return None
    forms.save_last({"report_folder": f.clip_folder.path})
    return Path(f.clip_folder.path)


def open_report():
    folder = _pick_clip("AI 动捕：打开质检报告")
    if folder:
        rep = folder / "qc" / "report.html"
        core.open_path(rep) if rep.exists() else _msg("AI 动捕", f"{rep} 不存在。")


def open_work():
    core.open_path(core.work_root())


def open_config():
    core.open_path(core.REPO / "config.toml")
