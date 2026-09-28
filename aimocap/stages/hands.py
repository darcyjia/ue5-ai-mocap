"""阶段 hands：手型状态（拳 / 半握 / 掌 / 放松），套到 SMPL-X 手指关节上。
GVHMR 不解手指，清理后的手是平伸的。这里不追求逐根手指还原，只要"感觉对"：
① scripts/tools/hand_detect.py（.venv-tools，MediaPipe）沿前臂裁手、算四指总弯曲角
② 弯曲角 → 状态（≥fist 为拳，<palm 为掌，中间半握）；识别不到的帧：短缺口沿用前后状态，
   长缺口按动作判断（手臂快速伸直 = 出拳 → 拳，其余用 fallback）
③ 多帧投票、去掉过短片段 ④ input/hands.json 手动覆盖 ⑤ 预设旋转沿时间平滑出过渡。
识别结果缓存在 hands/raw.json：只改阈值或手动覆盖时不重跑识别。"""
import shutil

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.spatial.transform import Rotation as Rot

from ..handpose import STATE_CN, STATES, all_presets
from ..kinematics import load_person, mats_to_quats
from ..util import ROOT, SCRIPTS, file_sig, load_json, log, params_hash, run as sh, save_json

HANDS = ("L", "R")
BASE = {"L": 25, "R": 40}
ARM = {"L": (16, 18, 20), "R": (17, 19, 21)}         # 肩 肘 腕（SMPL-X）
COLORS = {"fist": "#d62728", "guard": "#ff7f0e", "palm": "#2ca02c", "relaxed": "#1f77b4"}


def _n(cfg):
    return cfg["solve"]["num_people"]


def _detect_sig(c, cfg):
    return {"video": file_sig(c.video), "vit": [file_sig(c.solve / f"vit_p{k}.npy") for k in range(_n(cfg))],
            "script": file_sig(SCRIPTS / "tools" / "hand_detect.py")}


def params(c, cfg):
    return {**cfg["hands"], "in": [file_sig(c.clean / f"p{k}.npz") for k in range(_n(cfg))],
            "detect": _detect_sig(c, cfg), "override": file_sig(c.input / "hands.json"),
            "presets": file_sig(ROOT / "aimocap" / "handpose.py")}


def outputs(c, cfg):
    return [c.hands / f"p{k}.npz" for k in range(_n(cfg))] + [c.hands / "hands.json"]


def detect(c, cfg):
    """跑 MediaPipe 识别（约 40s），结果按输入指纹缓存。"""
    h = cfg["hands"]
    sig = params_hash(_detect_sig(c, cfg))
    raw = c.hands / "raw.json"
    if raw.exists() and (load_json(c.hands / "raw_sig.json", {}) or {}).get("sig") == sig:
        log("手部识别结果已是最新，跳过识别")
        return load_json(raw)
    py = ROOT / h["python"]
    if not py.exists():
        raise SystemExit(f"没有 {py}：手部识别需要单独的环境（mediapipe + opencv），见 README「手型」一节")
    shutil.rmtree(c.hands / "crops", ignore_errors=True)
    sh([py, SCRIPTS / "tools" / "hand_detect.py", "--video", c.video, "--vit-dir", c.solve, "--num", str(_n(cfg)),
        "--out", c.hands, "--model", ROOT / h["model"]], c.logs / "hands_detect.log")
    save_json(c.hands / "raw_sig.json", {"sig": sig})
    return load_json(raw)


def classify(curl, h):
    return [None if v is None else "fist" if v >= h["fist"] else "palm" if v < h["palm"] else "guard" for v in curl]


def punches(pos, side, h, fps):
    """出拳帧：手臂接近伸直且手腕速度快（前后几帧内任一帧满足即可）。"""
    s, e, w = ARM[side]
    a, b = pos[:, s] - pos[:, e], pos[:, w] - pos[:, e]
    elbow = np.degrees(np.arccos(np.clip((a * b).sum(1) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1)),
                                         -1, 1)))
    v = np.linalg.norm(np.gradient(pos[:, w], axis=0), axis=1) * fps
    hit = (elbow > h["punch_elbow"]) & (v > h["punch_speed"])
    k = 3
    return np.array([hit[max(0, t - k):t + k + 1].any() for t in range(len(hit))])


def fill(lab, punch, h):
    """补识别不到的帧：短缺口（两侧状态相同或 ≤gap_fill）沿用相邻状态；长缺口按动作判断。"""
    L, out, t, filled = len(lab), list(lab), 0, 0
    while t < L:
        if out[t] is not None:
            t += 1
            continue
        s = t
        while t < L and out[t] is None:
            t += 1
        prev, nxt = (out[s - 1] if s > 0 else None), (out[t] if t < L else None)
        for i in range(s, t):
            if t - s <= h["gap_fill"] and (prev or nxt):
                out[i] = (prev if i - s < (t - s) / 2 else nxt) or prev or nxt
            elif prev is not None and prev == nxt and t - s <= 3 * h["gap_fill"]:
                out[i] = prev
            else:
                out[i] = "fist" if punch[i] else h["fallback"]
            filled += 1
    return out, filled


def vote(lab, win):
    r = win // 2
    return [max(STATES, key=lambda s: (lab[max(0, t - r):t + r + 1].count(s), s == lab[t])) for t in range(len(lab))]


def runs(lab):
    out, s = [], 0
    for t in range(1, len(lab) + 1):
        if t == len(lab) or lab[t] != lab[s]:
            out.append([s, t - 1, lab[s]])
            s = t
    return out


def drop_short(lab, min_len):
    """短于 min_len 的片段并入更长的邻居，反复直到没有短片段。"""
    lab = list(lab)
    while True:
        rs = runs(lab)
        short = [i for i, (s, e, _) in enumerate(rs) if e - s + 1 < min_len]
        if not short or len(rs) == 1:
            return lab
        i = min(short, key=lambda i: rs[i][1] - rs[i][0])
        s, e, _ = rs[i]
        nb = [rs[j] for j in (i - 1, i + 1) if 0 <= j < len(rs)]
        st = max(nb, key=lambda r: r[1] - r[0])[2]
        lab[s:e + 1] = [st] * (e - s + 1)


def overrides(c, k, side, lab):
    n = 0
    for o in load_json(c.input / "hands.json", []) or []:
        if int(o.get("p", -1)) != k or o.get("hand", "").upper() not in (side, "LR", "BOTH"):
            continue
        if o["state"] not in STATES:
            raise SystemExit(f"input/hands.json：未知手型 {o['state']}（可选 {', '.join(STATES)}）")
        a, b = max(0, int(o.get("from", 0))), min(len(lab) - 1, int(o.get("to", len(lab) - 1)))
        lab[a:b + 1] = [o["state"]] * (b - a + 1)
        n += b - a + 1
    return n


def timeline(c, info, curls, L, fps, h):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    rows = [(p["person"], side) for p in info for side in HANDS]
    fig, axes = plt.subplots(len(rows), 1, figsize=(14, 1.5 * len(rows)), sharex=True)
    for ax, (k, side) in zip(np.atleast_1d(axes), rows):
        for s, e, st in info[k]["hands"][side]["segments"]:
            ax.axvspan(s / fps, (e + 1) / fps, color=COLORS[st], alpha=0.35, lw=0)
        cv = np.array([np.nan if v is None else v for v in curls[k][side]])
        ax.plot(np.arange(L) / fps, cv, ".", ms=2, color="k")
        for y in (h["fist"], h["palm"]):
            ax.axhline(y, color="gray", lw=0.5, ls="--")
        ax.set_ylim(0, 260)
        ax.set_ylabel(f"p{k} {'左' if side == 'L' else '右'}手", rotation=0, ha="right", va="center")
    handles = [plt.Rectangle((0, 0), 1, 1, color=COLORS[s], alpha=0.5) for s in STATES]
    fig.legend(handles, [STATE_CN[s] for s in STATES], loc="upper right", ncol=4)
    np.atleast_1d(axes)[-1].set_xlabel("秒（黑点：识别出的四指弯曲角，虚线：拳/掌阈值）")
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(c.hands / "timeline.png", dpi=90)
    plt.close(fig)


def run(c, cfg, args):
    h = cfg["hands"]
    c.hands.mkdir(parents=True, exist_ok=True)
    for f in ("smplx_common.npz", "camera.json"):
        shutil.copy(c.clean / f, c.hands / f)
    par = np.load(c.clean / "smplx_common.npz")["parents"]
    raw = detect(c, cfg) if h["enabled"] else None
    info, curls = [], []
    for k in range(_n(cfg)):
        P, Rl, _, pos = load_person(c.clean / f"p{k}.npz", par)
        L, fps = len(P["quat"]), float(P["fps"])
        if not h["enabled"]:
            shutil.copy(c.clean / f"p{k}.npz", c.hands / f"p{k}.npz")
            continue
        pre = all_presets(P["rest_joints"].astype(np.float64))
        rv = np.zeros((L, 30, 3))
        rec, cur = {"person": k, "hands": {}}, {}
        for side in HANDS:
            curl = raw["curl"][k][raw["hands"].index(side)][:L]
            curl += [None] * (L - len(curl))
            cur[side] = curl
            lab0 = classify(curl, h)
            lab, filled = fill(lab0, punches(pos, side, h, fps), h)
            lab = drop_short(vote(lab, h["vote"]), h["min_segment"])
            n_over = overrides(c, k, side, lab)
            b = BASE[side] - 25
            for t, st in enumerate(lab):
                rv[t, b:b + 15] = pre[st][b:b + 15]
            rec["hands"][side] = {
                "detect_rate": round(float(np.mean([v is not None for v in curl])), 3),
                "filled": filled, "overridden": n_over,
                "share": {s: round(lab.count(s) / L, 3) for s in STATES if s in lab},
                "segments": runs(lab)}
        # 过渡：旋转向量沿时间高斯平滑（手指旋转基本单轴，线性平滑足够）
        rv = gaussian_filter1d(rv, h["blend"] / 2.5, axis=0, mode="nearest") if h["blend"] > 0 else rv
        Q = P["quat"].copy()
        Q[:, 25:55] = mats_to_quats(Rot.from_rotvec(rv.reshape(-1, 3)).as_matrix().reshape(L, 30, 3, 3))
        P["quat"] = Q.astype(P["quat"].dtype)
        np.savez(c.hands / f"p{k}.npz", **P)
        info.append(rec)
        curls.append(cur)
        log(f"p{k}：" + "；".join(
            f"{'左' if s == 'L' else '右'}手 识别 {rec['hands'][s]['detect_rate']:.0%}，"
            + " ".join(f"{STATE_CN[st]} {v:.0%}" for st, v in rec["hands"][s]["share"].items())
            for s in HANDS))
    out = {"enabled": h["enabled"], "persons": info,
           "samples": (raw or {}).get("samples", [])[:: max(1, len((raw or {}).get("samples", [])) // 24)]}
    save_json(c.hands / "hands.json", out)
    if h["enabled"]:
        timeline(c, info, curls, L, fps, h)
    return {"persons": [{s: v["share"] for s, v in p["hands"].items()} for p in info]}
