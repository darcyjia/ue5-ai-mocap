"""运镜预演一条龙：Blender 场景 → 镜头表 → 相机 + 预演渲染 → 拼预演视频 → 导出 UE 相机和景深。

    python -m aimocap previz <素材> [--res 1128x480] [--auto-shots] [--no-render] [--force]

前提：素材已经在 UE 里重定向过（新建动捕 / 换角色），ue/export 下有 MH_p*.fbx 和 meshes_p*.json。
产物在 <素材>/blender/previz/：previz_mh.blend、shots.json、edl.json、previz_cams.blend、frames/、previz_<素材>.mp4；
导入运镜用的 cameras_ue.json 和 dof.json 同时复制到 <素材>/blender/（插件「导入运镜」默认读这里）。

镜头表 shots.json 已存在就沿用（可以手改后重跑）；--auto-shots 强制按受力检测重新生成：
九十年代港片规则——开场定格高机位缓降、全景交代、打中那一下切镜头、侧面跟拍 / 过肩 / 低机位仰拍 /
受击特写轮换、最狠的一下两个角度重复、结尾全景环绕；所有机位在原机位一侧（不越轴）。
"""
import json
import shutil
import sys
import time

import numpy as np

from .config import path as cpath
from .util import SCRIPTS, load_json, log, run as sh

MIN_SHOT, MAX_SHOT, MERGE = 0.9, 3.4, 0.45     # 秒：最短镜头、最长镜头、多少秒内的连续打击算一拍
ROTATION = ["side", "ots", "low", "close", "side", "ots", "wide", "close", "low"]


def _beats(c, fps):
    """受力检测 → 按时间排好的「拍」：[{t0, attacker, victim, target, speed}]，相邻 MERGE 秒内的合成一拍（取最快那下）。"""
    im = load_json(c.impact / "impacts.json", {}) or {}
    hits = []
    for p in im.get("persons", []):
        for e in p.get("impacts", []):
            hits.append({"t": e["frame"] / fps, "attacker": e.get("attacker", 1 - p["person"]), "victim": p["person"],
                         "target": e.get("target", "head"), "speed": e.get("speed", 0.0)})
    hits.sort(key=lambda h: h["t"])
    beats = []
    for h in hits:
        if beats and h["t"] - beats[-1]["t0"] < MERGE:
            if h["speed"] > beats[-1]["speed"]:
                beats[-1].update({k: h[k] for k in ("attacker", "victim", "target", "speed")})
            continue
        beats.append({**h, "t0": round(h["t"], 2)})
    return beats


def _side(k):
    """p0 一侧的机位用正方位角，p1 一侧用负的（和手写的 ring01 镜头表一致）。"""
    return 1 if k == 0 else -1


def _shot(kind, sid, t0, t1, beat, shake):
    att = beat["attacker"] if beat else 1
    vic = beat["victim"] if beat else 0
    if kind == "wide":
        return {"id": sid, "t0": t0, "t1": t1, "desc": "全景 交代两人位置", "target": "mid", "az": 10, "az1": 0,
                "dist": 7.0, "dist1": 6.2, "h": 1.8, "lens": 28}
    if kind == "side":
        return {"id": sid, "t0": t0, "t1": t1, "desc": "侧面中景 跟拍对打", "target": "mid", "az": 0, "dist": 3.8,
                "h": 1.4, "lens": 35, "track": True, "shake": shake}
    if kind == "ots":
        return {"id": sid, "t0": t0, "t1": t1, "desc": f"过 p{vic} 肩 看 p{att} 出手", "kind": "ots",
                "frm": f"p{vic}", "to": f"p{att}", "lens": 35, "shake": shake}
    if kind == "low":
        return {"id": sid, "t0": t0, "t1": t1, "desc": f"低机位仰拍 p{att}", "target": f"p{att}",
                "az": 30 * _side(att), "dist": 2.9, "dist1": 2.5, "h": 0.5, "lens": 24, "track": True, "shake": shake}
    if kind == "close":
        return {"id": sid, "t0": t0, "t1": t1, "desc": f"p{vic} 受击近景", "target": f"p{vic}head",
                "az": 60 * _side(vic), "dist": 1.9, "h": 1.6, "lens": 50, "track": True, "shake": shake}
    raise ValueError(kind)


def auto_shots(c):
    """按受力检测生成镜头表 dict（不写文件）。"""
    P = np.load(c.clean / "p0.npz")
    fps = float(P["fps"]) if "fps" in P.files else 24.0
    T = (P["quat"].shape[0] - 1) / fps
    beats = _beats(c, fps)
    cuts = [0.0]                                   # 切点：每一拍打中的那一刻切；太密的去掉，太长的中间补一刀
    for b in beats:
        if b["t0"] - cuts[-1] >= MIN_SHOT and T - b["t0"] >= MIN_SHOT:
            cuts.append(round(b["t0"], 2))
    cuts.append(round(T, 2))
    filled = [cuts[0]]
    for t in cuts[1:]:
        while t - filled[-1] > MAX_SHOT:
            filled.append(round(filled[-1] + MAX_SHOT * 0.6, 2))
        filled.append(t)
    cuts = filled
    key = max(beats, key=lambda b: b["speed"]) if beats else None     # 最狠的一下：重复两个角度

    shots = [{"id": "S00", "t0": None, "t1": None, "desc": "开场定格：高机位缓降到两人对峙", "target": "mid",
              "az": 25, "az1": 10, "dist": 12, "dist1": 9, "h": 6, "h1": 3, "lens": 24, "hold": 1.5}]
    n, rot, prev = 1, 0, "hold"
    for i in range(len(cuts) - 1):
        t0, t1 = cuts[i], cuts[i + 1]
        beat = next((b for b in beats if abs(b["t0"] - t0) < 1e-3), None)
        inside = [b for b in beats if t0 - 1e-3 <= b["t0"] < t1]
        ctx = beat or (inside[0] if inside else None)
        sid = f"S{n:02d}"
        if i == len(cuts) - 2 and i > 0:
            shots.append({"id": sid, "t0": t0, "t1": t1, "desc": "结尾 全景环绕", "target": "mid", "az": -15,
                          "az1": 15, "dist": 7.0, "h": 1.8, "lens": 28})
            break
        if key is not None and beat is key and t1 - t0 >= 0.8:
            k1 = round(min(t1, t0 + 0.8), 2)       # 关键一击：打中后 0.8 秒拍两个角度，然后接这一镜剩下的部分
            a = _shot("side", sid + "a", t0, k1, key, True)
            a["desc"] = "关键一击 角度一 侧面"
            b = _shot("close", sid + "b", t0, k1, key, True)
            b["desc"] = f"关键一击 角度二 p{key['victim']} 受击近景"
            shots += [a, b]
            prev = "close"
            if t1 - k1 >= 0.5:
                n += 1
                shots.append(_shot("low", f"S{n:02d}", k1, t1, key, False))
                prev = "low"
        else:
            kind = "wide"
            if i:
                kind = ROTATION[rot % len(ROTATION)]
                rot += 1
                if kind == prev:                       # 相邻两镜不用同一种景别
                    kind = ROTATION[rot % len(ROTATION)]
                    rot += 1
            prev = kind
            if kind == "close" and t1 - t0 > 1.4:      # 近景不拖：前 1.2 秒近景，剩下切回侧面中景
                k1 = round(t0 + 1.2, 2)
                shots.append(_shot("close", sid, t0, k1, ctx, True))
                n += 1
                kind, t0, sid, prev = "side", k1, f"S{n:02d}", "side"
                inside = [b for b in beats if t0 - 1e-3 <= b["t0"] < t1]
            s = _shot(kind, sid, t0, t1, ctx, bool(inside))
            if kind == "wide" and i:
                s["desc"] = "全景 拉开距离"
            shots.append(s)
        n += 1
    return {"fps": int(round(fps)), "auto": True, "beats": [round(b["t0"], 2) for b in beats], "shots": shots}


def run(cfg, clip, a):
    from .state import Clip
    c = Clip(cfg, clip)
    exp = c.ue / "export"
    need = [exp / f"meshes_p{k}.json" for k in range(cfg["solve"]["num_people"])]
    if not all(p.exists() for p in need):
        raise SystemExit(f"{clip} 还没有导出给预演用的角色网格（{exp}）。\n"
                         "先在 UE 编辑器里跑一次 UE 部分：菜单「新建动捕」或「换角色 / 重做重定向」。")
    bl, ff = cpath(cfg, "blender"), cpath(cfg, "ffmpeg")
    pv = c.blender / "previz"
    pv.mkdir(parents=True, exist_ok=True)
    blend_mh, blend_cams, shots = pv / "previz_mh.blend", pv / "previz_cams.blend", pv / "shots.json"

    log("== 预演场景（Blender）")
    if a.force or not blend_mh.exists():
        sh([bl, "-b", "--factory-startup", "--python", SCRIPTS / "blender" / "previz_mh.py", "--",
            "--clip-dir", c.root, "--out", blend_mh], c.logs / "previz_mh.log")
    else:
        log(f"沿用 {blend_mh.name}（--force 重建）")

    if a.auto_shots or not shots.exists():
        sd = auto_shots(c)
        if shots.exists():
            shutil.copy(shots, shots.with_name("shots.bak_" + time.strftime("%m%d_%H%M%S") + ".json"))
        shots.write_text(json.dumps(sd, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"== 自动镜头表：{len(sd['shots'])} 个镜头，打击 {len(sd['beats'])} 拍 → {shots}")
    else:
        log(f"== 沿用镜头表 {shots}（--auto-shots 重新生成）")

    log("== 相机" + ("" if a.no_render else " + 预演渲染"))
    frames = pv / "frames"
    cmd = [bl, "-b", blend_mh, "--python", SCRIPTS / "blender" / "previz_cams.py", "--", "--shots", shots,
           "--impacts", c.impact / "impacts.json", "--out-blend", blend_cams, "--res", a.res, "--avoid"]
    if not a.no_render:
        shutil.rmtree(frames, ignore_errors=True)      # 镜头数变了，旧帧会混进去
        cmd += ["--render-dir", frames]
    sh(cmd, c.logs / "previz_cams.log")

    if not a.no_render:
        log("== 拼预演视频")
        out = pv / f"previz_{clip}.mp4"
        sh([sys.executable, SCRIPTS / "tools" / "assemble_edit.py", "--edl", pv / "edl.json", "--frames", frames,
            "--audio", c.video, "--out", out, "--ffmpeg", ff], c.logs / "previz_assemble.log")
        log(f"预演视频：{out}")

    log("== 导出 UE 相机和景深")
    sh([bl, "-b", blend_cams, "--python", SCRIPTS / "blender" / "export_cams_ue.py", "--", "--edl", pv / "edl.json",
        "--out", pv / "cameras_ue.json", "--shots", shots], c.logs / "previz_export.log")
    stamp = time.strftime("%m%d_%H%M%S")
    for name in ("cameras_ue.json", "dof.json"):
        dst = c.blender / name
        if dst.exists():
            shutil.copy(dst, dst.with_name(dst.stem + ".bak_" + stamp + ".json"))
        shutil.copy(pv / name, dst)
    ov = load_json(c.input / "ue.json", {}) or {}
    other = {p: o["cameras"] for p, o in ov.items() if isinstance(o, dict) and o.get("cameras")}
    if other:
        log(f"注意：input/ue.json 给这些工程指定了别的运镜文件，导入运镜会用那个：{other}")
    n = len((load_json(pv / "edl.json", {}) or {}).get("shots", []))
    log(f"完成：{n} 个镜头。下一步：UE 菜单「导入运镜（Blender 预演）…」选 {c.root}")