"""阶段 ue：UE 5.8 命令行里导入、重定向到 MetaHuman、建关卡序列。UE 编辑器必须先关闭。"""
import json
import math
import subprocess

import numpy as np

from ..util import SCRIPTS, file_sig, load_json, log, run as sh, save_json


def params(c, cfg):
    n = cfg["solve"]["num_people"]
    return {"in": [file_sig(c.fbx / f"p{k}.fbx") for k in range(n)], "ue": cfg["ue"],
            "person": cfg["person"][:n], "script": file_sig(SCRIPTS / "ue" / "ue_pipeline.py")}


def outputs(c, cfg):
    return [c.ue / "result.json"]


def camera_ue(cam):
    """solve/camera.json（Y 朝上、米）→ UE 位置(cm)/旋转。Blender→FBX→UE 往返已验证：UE 的 Y = −Blender Y。"""
    C = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]])
    pos = C @ np.array(cam["pos"]) * 100
    fwd = C @ (np.array(cam["R"]) @ np.array([0, 0, -1.0]))
    yaw = math.degrees(math.atan2(fwd[1], fwd[0]))
    pitch = math.degrees(math.asin(max(-1, min(1, fwd[2]))))
    return [float(pos[0]), float(-pos[1]), float(pos[2]), 0.0, pitch, -yaw]


def ue_running():
    out = subprocess.run(["tasklist"], stdout=subprocess.PIPE).stdout.decode("gbk", errors="ignore")
    return "UnrealEditor.exe" in out


def run(c, cfg, args):
    if ue_running():
        raise SystemExit("UE 编辑器正在运行：请先关闭（不要保存本素材的资产），命令行模式才能安全写入")
    n = cfg["solve"]["num_people"]
    cam = load_json(c.clean / "camera.json")
    job = {"clip": c.name, "fbx": [str(c.fbx / f"p{k}.fbx") for k in range(n)],
           "persons": cfg["person"][:n], "content_dir": f"{cfg['ue']['content_root']}/{c.name}",
           "retarget_dir": cfg["ue"]["retarget_dir"], "uniform_horizontal_scale": cfg["ue"]["uniform_horizontal_scale"],
           "force_horizontal_scale": cfg["ue"].get("force_horizontal_scale", 0),
           "fps": cam["fps"], "cam_ue": camera_ue(cam), "lens": cam["lens"], "res": cam["res"],
           "export_dir": str(c.ue / "export"), "result": str(c.ue / "result.json")}
    save_json(c.ue / "job.json", job)
    (c.ue / "result.json").unlink(missing_ok=True)
    p = cfg["paths"]
    _, out = sh([p["ue_cmd"], p["ue_project"], "-run=pythonscript",
                 f"-script={(SCRIPTS / 'ue' / 'ue_pipeline.py').as_posix()}", "-unattended", "-nop4", "-nosplash", "-NoSound",
                 "-stdout", "-FullStdOutLogOutput"], c.logs / "ue.log", env={"AIMOCAP_JOB": str(c.ue / "job.json")},
                check=False)
    res = load_json(c.ue / "result.json")
    if not res or not res.get("ok"):
        errs = [l for l in out.splitlines() if "LogPython: Error" in l or "Assertion failed" in l][:15]
        raise RuntimeError("UE 阶段失败，日志 " + str(c.logs / "ue.log") + "\n" + "\n".join(errs))
    for r in res["persons"]:
        log(f"p{r['p']}: 躯干误差 {r['torso_err_mean']:+.1f}° 头部 {r['head_err_mean']:+.1f}° 手臂 {r['arm_err_mean']:.1f}°")
    log(f"水平缩放 {res['horizontal_scale']}，两人间距比 {res.get('spacing_ratio_median')}；序列 {res['sequence']}")
    return res
