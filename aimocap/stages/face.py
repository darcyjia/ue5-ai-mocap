"""阶段 face：表情（impact 之后）。不还原视频里的脸，只让表情和动作配合，全部由动作数据驱动：
① 眼神：逐帧算对手的脸在自己头部坐标系里的方向 → 眼球（CTRL_C_eye），加少量扫视；
② 眨眼：每人各自随机间隔，自己出拳、受击前后不眨；
③ 受击：impact 检测到的每一下 → 闭眼、缩眼、压眉、皱鼻、咧嘴、下巴微张，幅度跟冲击走（格挡减弱）；
底色按性格（person 的 face_style：calm 冷静 / fierce 狰狞）。
输出每人每帧的 MetaHuman 面部控制板（Face_ControlBoard_CtrlRig）控件值，UE 阶段写进序列的 Face 轨道。"""
import zlib

import numpy as np
from scipy.ndimage import gaussian_filter1d

from ..kinematics import load_person
from ..util import file_sig, load_json, log, save_json
from .ue import persons

HEAD = 15
EYE = np.array([0.0, 0.09, 0.08])            # 眼睛（头关节局部：往上 9cm、往前 8cm）
LR = ("L", "R")

# 性格底色：成对控件写 "*"（展开成 L/R）
STYLES = {
    "calm":   {"*_brow_down": 0.15, "*_jaw_clench": 0.2, "*_mouth_lipsPressU": 0.2, "*_eye_squintInner": 0.1},
    "fierce": {"*_brow_down": 0.45, "*_jaw_clench": 0.35, "*_nose_wrinkleUpper": 0.2, "*_mouth_upperLipRaise": 0.25,
               "*_eye_squintInner": 0.25, "*_mouth_stretch": 0.1},
}
# 受击表情（强度 1 时的增量）
HIT = {"*_eye_squintInner": 0.6, "*_eye_faceScrunch": 0.5, "*_brow_down": 0.5, "*_nose_wrinkleUpper": 0.4,
       "*_mouth_stretch": 0.4, "*_mouth_upperLipRaise": 0.3, "*_eye_cheekRaise": 0.3}
BLINK = [0.5, 1.0, 1.0, 0.7, 0.35, 0.1]       # 一次眨眼的形状（24fps 约 0.25s）


def _n(cfg):
    return cfg["solve"]["num_people"]


def params(c, cfg):
    return {**cfg["face"], "in": [file_sig(c.impact / f"p{k}.npz") for k in range(_n(cfg))],
            "impacts": file_sig(c.impact / "impacts.json"),
            "styles": [p.get("face_style") for p in persons(c, cfg)]}


def outputs(c, cfg):
    return [c.face / f"face_p{k}.json" for k in range(_n(cfg))] + [c.face / "face.json"]


def style_of(c, cfg, k):
    s = (persons(c, cfg)[k] or {}).get("face_style") or ("calm" if k == 0 else "fierce")
    return s if s in STYLES else "calm"


def pulse(n, fps, tau):
    t = np.arange(n) / fps
    return (t / tau) * np.exp(1 - t / tau)


def _add(ch, name, val, sl=slice(None)):
    for s in (LR if name.startswith("*") else ("",)):
        key = "CTRL_" + (s + name[1:] if s else name)
        ch.setdefault(key, np.zeros(ch["_L"]))[sl] += val


def gaze(Rg, pos, Rg_o, pos_o, h):
    """对手的脸在自己头部坐标系（SMPL-X：+x 左、+y 上、+z 前）里的偏航/俯仰 → 眼球控件 [-1,1]。"""
    eye = pos[:, HEAD] + Rg[:, HEAD] @ EYE
    tgt = pos_o[:, HEAD] + Rg_o[:, HEAD] @ EYE
    v = np.einsum("tji,tj->ti", Rg[:, HEAD], tgt - eye)          # Rg^T · (目标 − 眼睛)
    yaw = np.degrees(np.arctan2(v[:, 0], v[:, 2]))
    pitch = np.degrees(np.arctan2(v[:, 1], np.hypot(v[:, 0], v[:, 2])))
    # 双人相对纵深是单目解算看不准的方向（实测会差 40°），眼球只转应转角度的一部分，其余交给头部朝向
    lim = h["gaze_limit"]
    x = np.clip(yaw * h["gaze_gain"][0] / h["eye_max_yaw"], -lim, lim) * h["gaze_x_sign"]
    y = np.clip(pitch * h["gaze_gain"][1] / h["eye_max_pitch"], -lim, lim) * h["gaze_y_sign"]
    return x, y, yaw, pitch


def run(c, cfg, args):
    h, n = cfg["face"], _n(cfg)
    c.face.mkdir(parents=True, exist_ok=True)
    if not h["enabled"]:
        save_json(c.face / "face.json", {"enabled": False})
        for k in range(n):
            (c.face / f"face_p{k}.json").unlink(missing_ok=True)
        return {}
    par = np.load(c.impact / "smplx_common.npz")["parents"]
    ppl = [load_person(c.impact / f"p{k}.npz", par) for k in range(n)]
    fps, L = float(ppl[0][0]["fps"]), len(ppl[0][3])
    imp = load_json(c.impact / "impacts.json", {}) or {}
    hits = {p["person"]: p["impacts"] for p in imp.get("persons", [])}
    strikes = {k: sorted({e["frame"] for ev in hits.values() for e in ev if e.get("attacker") == k}) for k in range(n)}
    summary = {"enabled": True, "fps": fps, "frames": L, "persons": []}
    plots = []
    for k in range(n):
        o = [a for a in range(n) if a != k][0] if n > 1 else k
        _, _, Rg, pos = ppl[k]
        _, _, Rg_o, pos_o = ppl[o]
        rng = np.random.default_rng(zlib.crc32(f"{c.name}:{k}".encode()))
        style = style_of(c, cfg, k)
        ch = {"_L": L}
        for name, v in STYLES[style].items():                      # 底色
            _add(ch, name, v * h["style_strength"])
        blink = np.zeros(L)
        for e in hits.get(k, []):                                  # ③ 受击
            i = float(np.clip(e.get("amp_deg", 6) / 10, 0.3, 1.0)) * (0.6 if e["target"].startswith("arm") else 1.0)
            i *= h["hit_strength"]
            f0 = e["frame"]
            m = min(L - f0, int(h["hit_duration"] * fps) + 1)
            env = pulse(m, fps, h["hit_tau"]) * i
            sl = slice(f0, f0 + m)
            for name, v in HIT.items():
                _add(ch, name, v * env, sl)
            _add(ch, "C_jaw.y", 0.12 * env, sl)
            blink[sl] = np.maximum(blink[sl], np.minimum(1.0, 1.4 * env))       # 受击下意识闭眼
        busy = np.zeros(L, bool)                                   # ② 眨眼
        for f in strikes[k]:
            busy[max(0, f - 3):f + 4] = True
        for e in hits.get(k, []):
            busy[max(0, e["frame"] - 4):e["frame"] + 8] = True
        lo, hi = h["blink_interval"][style]
        nb, t, blinks = len(BLINK), rng.uniform(0.5, hi) * fps, 0
        while t < L - nb:
            f = int(t)
            while f < L - nb and busy[f:f + nb].any():
                f += 1                                             # 忙的时候往后推
            if f >= L - nb:
                break
            blink[f:f + nb] = np.maximum(blink[f:f + nb], BLINK)
            blinks += 1
            t = f + rng.uniform(lo, hi) * fps
        for s in LR:
            ch[f"CTRL_{s}_eye_blink"] = blink.copy()
        gx, gy, yaw, pitch = gaze(Rg, pos, Rg_o, pos_o, h)         # ① 眼神 + 扫视
        sx, sy, t = np.zeros(L), np.zeros(L), 0.0
        while t < L:
            dur = rng.uniform(*h["saccade_interval"]) * fps
            a, b = int(t), int(min(L, t + dur))
            sx[a:b], sy[a:b] = rng.uniform(-1, 1, 2) * h["saccade_amp"]
            t += dur
        gx = np.clip(gaussian_filter1d(gx, 0.7) + gaussian_filter1d(sx, 0.8), -1, 1)
        gy = np.clip(gaussian_filter1d(gy, 0.7) + gaussian_filter1d(sy, 0.8), -1, 1)
        flt = {kk: np.clip(v, -1 if kk.endswith("eye_blink") else 0, 1).round(4).tolist()
               for kk, v in ch.items() if kk != "_L" and not kk.startswith("CTRL_C_jaw")}
        jaw_y = np.clip(ch.get("CTRL_C_jaw.y", np.zeros(L)), 0, 1)
        vec2 = {"CTRL_C_eye": np.stack([gx, gy], 1).round(4).tolist(),
                "CTRL_C_jaw": np.stack([np.zeros(L), jaw_y], 1).round(4).tolist()}
        save_json(c.face / f"face_p{k}.json", {"fps": fps, "frames": L, "style": style, "float": flt, "vec2": vec2})
        look_ok = float(np.mean(np.abs(yaw * h["gaze_gain"][0]) < h["eye_max_yaw"] * h["gaze_limit"]))
        summary["persons"].append({"person": k, "style": style, "blinks": blinks, "hits": len(hits.get(k, [])),
                                   "gaze_in_range": round(look_ok, 3)})
        plots.append((k, style, blink, ch.get("CTRL_L_eye_squintInner"), ch.get("CTRL_L_brow_down"), gx))
        log(f"p{k}（{style}）：眨眼 {blinks} 次，受击表情 {len(hits.get(k, []))} 次，"
            f"{look_ok:.0%} 的帧对手在眼球可转范围内（其余帧眼球顶到边，头没转过去）")
    save_json(c.face / "face.json", summary)
    timeline(c, plots, fps, L)
    return {"persons": summary["persons"]}


def timeline(c, plots, fps, L):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    fig, axes = plt.subplots(len(plots), 1, figsize=(15, 2.4 * len(plots)), sharex=True)
    t = np.arange(L) / fps
    for ax, (k, style, blink, squint, brow, gx) in zip(np.atleast_1d(axes), plots):
        ax.plot(t, blink, lw=0.8, label="闭眼")
        ax.plot(t, squint if squint is not None else np.zeros(L), lw=0.8, label="缩眼")
        ax.plot(t, brow if brow is not None else np.zeros(L), lw=0.8, label="压眉")
        ax.plot(t, gx, lw=0.8, label="眼球左右")
        ax.set_ylim(-1.05, 1.05)
        ax.set_ylabel(f"p{k}（{style}）", rotation=0, ha="right", va="center")
        ax.legend(loc="upper right", fontsize=8, ncol=4)
        ax.grid(alpha=.3)
    np.atleast_1d(axes)[-1].set_xlabel("秒")
    fig.tight_layout()
    fig.savefig(c.face / "timeline.png", dpi=80)
    plt.close(fig)
