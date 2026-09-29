"""阶段 impact：受力反馈（hands 之后）。GVHMR 按时间序列解算，会把受击时头部、躯干短促的晃动当噪声压小
（fight_test_03 实测只剩视频里的 55–60%，连环小击打几乎全丢）。两层补回来：
① 高频放大：躯干/脖子/头的局部旋转只放大快速变化的部分（旋转 = 平滑 ∘ exp(gain·残差)），慢动作不变。
   gain 默认按视频校准：视频里头相对肩膀的高频晃动（ViTPose）与动捕投影回画面的比值（95 分位，限幅）。
② 打击反应：从动捕里找攻击者的拳/肘/脚/膝高速到达对方头、躯干、手臂附近并突然减速的帧，
   给被打的一方叠一个很短的冲击（临界阻尼脉冲，沿来拳方向）。input/impacts.json 手动增删改。
结果写到 impact/，preview 和 fbx 从这里读。"""
import shutil

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.spatial.transform import Rotation as Rot

from ..kinematics import fk, load_person, mats_to_quats, project
from ..util import file_sig, load_json, log, save_json

PELVIS, SPINE1, SPINE2, SPINE3, NECK, HEAD = 0, 3, 6, 9, 12, 15
HF_JOINTS = [SPINE1, SPINE2, SPINE3, NECK, HEAD]
SHOULDER, ELBOW, WRIST = {"L": 16, "R": 17}, {"L": 18, "R": 19}, {"L": 20, "R": 21}
KNEE, FOOT = {"L": 4, "R": 5}, {"L": 10, "R": 11}
TARGET_CN = {"head": "头", "chest": "胸", "belly": "腹", "arm": "手臂"}


def _n(cfg):
    return cfg["solve"]["num_people"]


def _kind(tg):
    return "arm" if tg.startswith("arm") else tg


def params(c, cfg):
    return {**cfg["impact"], "in": [file_sig(c.hands / f"p{k}.npz") for k in range(_n(cfg))],
            "override": file_sig(c.input / "impacts.json")}


def outputs(c, cfg):
    return [c.impact / f"p{k}.npz" for k in range(_n(cfg))] + [c.impact / "impacts.json"]


# ---------------- ① 高频放大 ----------------
def _smooth_quats(q, sigma):
    q = q.copy()
    for t in range(1, len(q)):                       # 符号连续
        if (q[t] * q[t - 1]).sum() < 0:
            q[t] = -q[t]
    s = gaussian_filter1d(q, sigma, axis=0, mode="nearest")
    return s / np.linalg.norm(s, axis=-1, keepdims=True)


def hf_gain(Rl, gain, sigma):
    """Rl (L,55,3,3)：对 HF_JOINTS 做 平滑 ∘ exp(gain · log(平滑⁻¹ ∘ 原))。"""
    Rl = Rl.copy()
    for j in HF_JOINTS:
        R = Rot.from_matrix(Rl[:, j])
        S = Rot.from_quat(_smooth_quats(R.as_quat(), sigma))
        Rl[:, j] = (S * Rot.from_rotvec((S.inv() * R).as_rotvec() * gain)).as_matrix()
    return Rl


FACE = np.array([0.0, 0.06, 0.10])                   # 脸部点（头关节局部：往上 6cm、往前 10cm），对应视频的鼻眼耳


def head_hf(pos, Rg, cam, sigma):
    """动捕投影回画面：脸部点相对肩膀中点的高频位移（像素）。头关节本身在后脑根部，头的转动反映不到它身上。"""
    face = pos[:, HEAD] + Rg[:, HEAD] @ FACE
    u, v, _, _ = project(np.concatenate([face[:, None], pos[:, 16:18]], 1), cam)
    rel = np.stack([u[:, 0] - (u[:, 1] + u[:, 2]) / 2, v[:, 0] - (v[:, 1] + v[:, 2]) / 2], 1)
    return np.linalg.norm(rel - gaussian_filter1d(rel, sigma, axis=0), axis=1)


def video_hf(vit, sigma):
    """视频（ViTPose）：头（鼻眼耳均值）相对肩膀中点的高频位移（像素），置信度低的帧为 nan。"""
    rel = vit[:, 0:5, :2].mean(1) - vit[:, 5:7, :2].mean(1)
    h = np.linalg.norm(rel - gaussian_filter1d(rel, sigma, axis=0), axis=1)
    h[vit[:, 0:7, 2].min(1) < 0.5] = np.nan
    return h


# ---------------- ② 打击检测 ----------------
def _seg_dist(p, a, b):
    ab = b - a
    t = np.clip(((p - a) * ab).sum(-1) / ((ab * ab).sum(-1) + 1e-9), 0, 1)
    return np.linalg.norm(p - (a + ab * t[..., None]), axis=-1)


def targets(pos):
    """被打方的受击部位：名称 → 点 p 到部位表面的距离（已减去部位半径）。pos (55,3) 单帧。"""
    up = pos[HEAD] - pos[NECK]
    head_c = pos[HEAD] + 0.07 * up / (np.linalg.norm(up) + 1e-9)
    out = {"head": lambda p: np.linalg.norm(p - head_c) - 0.12,
           "chest": lambda p: _seg_dist(p, pos[SPINE3], pos[NECK]) - 0.16,
           "belly": lambda p: _seg_dist(p, pos[PELVIS], pos[SPINE2]) - 0.16}
    for s in "LR":
        out[f"arm{s}"] = (lambda p, s=s: min(_seg_dist(p, pos[ELBOW[s]], pos[WRIST[s]]) - 0.06,
                                             _seg_dist(p, pos[SHOULDER[s]], pos[ELBOW[s]]) - 0.07))
    return out


def effectors(pos):
    """攻击方的打击点：拳（腕沿前臂往前 8cm）、肘、脚、膝。名称 → ((L,3), 类别)。"""
    out = {}
    for s in "LR":
        fa = pos[:, WRIST[s]] - pos[:, ELBOW[s]]
        out[f"fist{s}"] = (pos[:, WRIST[s]] + 0.08 * fa / (np.linalg.norm(fa, axis=1, keepdims=True) + 1e-9), "fist")
        out[f"elbow{s}"] = (pos[:, ELBOW[s]], "elbow")
        out[f"foot{s}"] = (pos[:, FOOT[s]], "foot")
        out[f"knee{s}"] = (pos[:, KNEE[s]], "knee")
    return out


def detect(posA, posD, fps, h):
    """A 打 D：速度峰值超过门槛，峰后 stop_frames 内降到峰值的 stop_ratio 以下（打中或被挡住；挥空穿过去的不算），
    且这段时间里打击点离 D 的某个部位足够近。"""
    ev = []
    for name, (P, kind) in effectors(posA).items():
        V = gaussian_filter1d(np.gradient(P, axis=0) * fps, 1, axis=0)
        s = np.linalg.norm(V, axis=1)
        for t in range(1, len(s) - 1):
            if not (s[t] > h["min_speed"][kind] and s[t] >= s[t - 1] and s[t] > s[t + 1]):
                continue
            stop = next((u for u in range(t + 1, min(len(s), t + h["stop_frames"] + 1))
                         if s[u] < h["stop_ratio"] * s[t]), None)
            if stop is None:
                continue
            best = None
            for u in range(t, stop + 1):
                for tg, dist in targets(posD[u]).items():
                    d = float(dist(P[u]))
                    if best is None or d < best[0]:
                        best = (d, u, tg)
            if best[0] < h["contact_dist"]:
                ev.append({"frame": int(best[1]), "effector": name, "target": best[2], "speed": round(float(s[t]), 2),
                           "dist": round(best[0], 3), "dir": (V[t] / (s[t] + 1e-9)).round(3).tolist()})
    ev.sort(key=lambda e: e["frame"])
    out = []                                          # merge_frames 内只留最快的一下
    for e in ev:
        if out and e["frame"] - out[-1]["frame"] <= h["merge_frames"]:
            if e["speed"] > out[-1]["speed"]:
                out[-1] = e
            continue
        out.append(e)
    return out


# ---------------- ② 打击反应 ----------------
def pulse(n, fps, tau):
    """临界阻尼脉冲 (t/τ)·e^(1−t/τ)：t=τ 时到峰值 1，之后平滑衰减，不来回摆。"""
    t = np.arange(n) / fps
    return (t / tau) * np.exp(1 - t / tau)


def react(Rl, Rg, pos, parents, e, h, fps):
    """在被打方身上叠加冲击：绕世界轴 a 转 θ(t)，按关节权重分配。R_l' = exp(θ·Rg_parent⁻¹a)·R_l。返回幅度（度）。"""
    f0, d, tg = e["frame"], np.array(e["dir"], float), e["target"]
    amp = h["amp_deg"][_kind(tg)] * np.clip(e["speed"] / h["ref_speed"], 0.5, 1.6) * e.get("scale", 1.0)
    head_axis = np.cross(pos[f0, HEAD] - pos[f0, NECK], d)
    if tg == "head":
        plan = [(SPINE3, head_axis, 0.2), (NECK, head_axis, 0.4), (HEAD, head_axis, 0.6)]
    elif tg in ("chest", "belly"):
        a = np.cross(pos[f0, NECK] - pos[f0, SPINE1], d if tg == "chest" else -d)   # 胸被打后仰，腹被打前折
        plan = [(SPINE1, a, 0.25), (SPINE2, a, 0.35), (SPINE3, a, 0.45), (HEAD, a, 0.3)]
    else:                                             # 格挡：手臂被砸回来，头和上身跟着震一下
        s = tg[-1]
        a = np.cross(pos[f0, WRIST[s]] - pos[f0, SHOULDER[s]], d)
        plan = [(SHOULDER[s], a, 1.0), (ELBOW[s], a, 0.3), (SPINE3, head_axis, 0.15), (NECK, head_axis, 0.25),
                (HEAD, head_axis, 0.35)]
    n = min(len(Rl) - f0, int(h["duration"] * fps) + 1)
    th = np.radians(amp) * pulse(n, fps, h["tau"])
    for j, a, w in plan:
        na = np.linalg.norm(a)
        if na < 1e-6:
            continue
        a = a / na
        for i in range(n):
            t = f0 + i
            Rl[t, j] = Rot.from_rotvec(Rg[t, parents[j]].T @ a * th[i] * w).as_matrix() @ Rl[t, j]
    return float(amp)


def overrides(c, events):
    """input/impacts.json（p 是被打的人）：
    {"p":1,"frame":130,"scale":1.5}          调这一下的幅度（±3 帧内的自动检测结果）
    {"p":1,"frame":130,"remove":true}         删掉
    {"p":1,"frame":130,"target":"head"}       附近没有检测结果时新增一下（target: head/chest/belly/armL/armR）"""
    ov = load_json(c.input / "impacts.json", []) or []
    for o in ov:
        k, f = int(o["p"]), int(o["frame"])
        near = [e for e in events[k] if abs(e["frame"] - f) <= 3]
        if o.get("remove"):
            events[k] = [e for e in events[k] if e not in near]
        elif near:
            for e in near:
                e["scale"] = float(o.get("scale", 1.0))
                e["target"] = o.get("target", e["target"])
                e["manual"] = True
        else:
            events[k].append({"frame": f, "target": o.get("target", "head"), "speed": float(o.get("speed", 4.0)),
                              "scale": float(o.get("scale", 1.0)), "effector": "manual", "dir": o.get("dir"),
                              "manual": True})
    for k in events:
        events[k].sort(key=lambda e: e["frame"])
    return len(ov)


def run(c, cfg, args):
    h, n = cfg["impact"], _n(cfg)
    c.impact.mkdir(parents=True, exist_ok=True)
    for f in ("smplx_common.npz", "camera.json"):
        shutil.copy(c.hands / f, c.impact / f)
    if not h["enabled"]:
        for k in range(n):
            shutil.copy(c.hands / f"p{k}.npz", c.impact / f"p{k}.npz")
        save_json(c.impact / "impacts.json", {"enabled": False, "persons": []})
        return {}
    par = np.load(c.hands / "smplx_common.npz")["parents"]
    cam = load_json(c.hands / "camera.json")
    P, Rl, Rg0, pos = map(list, zip(*[load_person(c.hands / f"p{k}.npz", par) for k in range(n)]))
    fps, sg = float(P[0]["fps"]), h["hf_sigma"]
    vh = [video_hf(np.load(c.solve / f"vit_p{k}.npy")[:len(pos[k])], sg) for k in range(n)]
    # ② 打击检测（用原始位置）
    events = {k: [] for k in range(n)}
    for a in range(n):
        for d in range(n):
            if a != d:
                for e in detect(pos[a], pos[d], fps, h):
                    events[d].append({**e, "attacker": a})
    n_over = overrides(c, events)
    rec = {"enabled": True, "overrides": n_over, "persons": []}
    for k in range(n):
        # ① 高频放大
        before = head_hf(pos[k], Rg0[k], cam, sg)
        ratio = float(np.nanpercentile(vh[k], 95) / max(np.percentile(before, 95), 1e-6))
        g = float(np.clip(ratio, 1.0, h["hf_gain_max"])) if h["hf_gain"] == "auto" else float(h["hf_gain"])
        R = hf_gain(Rl[k], g, sg)
        # ② 打击反应
        J, T = P[k]["rest_joints"].astype(np.float64), P[k]["transl"].astype(np.float64)
        Rg, _ = fk(J, R, T, par)
        for e in events[k]:
            if not e.get("dir"):                      # 手动新增：取对方骨盆指向本人头部的方向
                o = [a for a in range(n) if a != k][0]
                v = pos[k][e["frame"], HEAD] - pos[o][e["frame"], PELVIS]
                e["dir"] = (v / (np.linalg.norm(v) + 1e-9)).round(3).tolist()
            e["amp_deg"] = round(react(R, Rg, pos[k], par, e, h, fps), 1)
        np.savez(c.impact / f"p{k}.npz", **{**P[k], "quat": mats_to_quats(R).astype(P[k]["quat"].dtype)})
        Rg_new, pos_new = fk(J, R, T, par)
        cnt = {}
        for e in events[k]:
            cnt[TARGET_CN[_kind(e["target"])]] = cnt.get(TARGET_CN[_kind(e["target"])], 0) + 1
        pr = {"person": k, "video_ratio": round(ratio, 2), "hf_gain": round(g, 2), "impacts": events[k],
              "hf95_px": {"video": round(float(np.nanpercentile(vh[k], 95)), 2),
                          "before": round(float(np.percentile(before, 95)), 2),
                          "after": round(float(np.percentile(head_hf(pos_new, Rg_new, cam, sg), 95)), 2)}}
        rec["persons"].append(pr)
        log(f"p{k}：高频放大 ×{g:.2f}（视频/动捕 {ratio:.2f}），受击 {len(events[k])} 次 {cnt}；"
            f"头部高频 95 分位 视频 {pr['hf95_px']['video']} / 原 {pr['hf95_px']['before']} / 现 {pr['hf95_px']['after']} px")
    save_json(c.impact / "impacts.json", rec)
    timeline(c, rec, fps, len(pos[0]), vh, cam, sg, par, list(zip(pos, Rg0)))
    return {"persons": [{"gain": p["hf_gain"], "impacts": len(p["impacts"])} for p in rec["persons"]]}


def timeline(c, rec, fps, L, vh, cam, sg, par, pos_before):
    """每人两行：受击事件（竖线高 = 幅度），头部高频晃动（视频 / 原动捕 / 处理后）。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    col = {"head": "#d62728", "chest": "#ff7f0e", "belly": "#9467bd", "arm": "#1f77b4"}
    n = len(rec["persons"])
    fig, axes = plt.subplots(2 * n, 1, figsize=(15, 2.2 * n * 2), sharex=True)
    t = np.arange(L) / fps
    for p in rec["persons"]:
        k = p["person"]
        ax = axes[2 * k]
        for e in p["impacts"]:
            ax.vlines(e["frame"] / fps, 0, e["amp_deg"], color=col[_kind(e["target"])], lw=2)
        ax.set_ylim(0, 15)
        ax.set_ylabel(f"p{k} 受击 °", rotation=0, ha="right", va="center")
        ax = axes[2 * k + 1]
        _, _, rgn, pn = load_person(c.impact / f"p{k}.npz", par)
        ax.plot(t, vh[k][:L], lw=0.7, color="#999", label="视频")
        ax.plot(t, head_hf(*pos_before[k], cam, sg)[:L], lw=0.8, label="原动捕")
        ax.plot(t, head_hf(pn, rgn, cam, sg)[:L], lw=0.8, label=f"处理后（×{p['hf_gain']} + 受击）")
        ax.set_ylabel(f"p{k} 头部\n高频 px", rotation=0, ha="right", va="center")
        ax.legend(loc="upper right", fontsize=8)
    handles = [plt.Line2D([0], [0], color=v, lw=3) for v in col.values()]
    fig.legend(handles, ["打头", "打胸", "打腹", "打在手臂（格挡）"], loc="upper left", ncol=4)
    axes[-1].set_xlabel("秒")
    for a in axes:
        a.grid(alpha=.3)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(c.impact / "timeline.png", dpi=80)
    plt.close(fig)
