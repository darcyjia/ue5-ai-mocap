"""阶段 clean：脚部锁定。
⓪ 每人单独贴地 ① 着地检测（GVHMR 静止置信度 + 脚高，滞回）并合并被切碎的片段
② 根部水平校正（让着地脚停住）③ 髋-膝-踝两段 IK。
背景：GVHMR 自带的清理只修 global 结果的根平移，我们用的相机空间结果根平移没修，
所以脚滑集中在镜头深度方向。"""
import shutil

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.spatial.transform import Rotation as Rot

from ..kinematics import (HEAD, L_ANKLE, L_FOOT, L_HIP, L_KNEE, PELVIS, R_ANKLE, R_FOOT, R_HIP, R_KNEE, fk,
                          mats_to_quats, quats_to_mats)
from ..util import file_sig, log, save_json

SIDES = {"L": dict(c=(0, 1), ank=L_ANKLE, foot=L_FOOT, hip=L_HIP, knee=L_KNEE),
         "R": dict(c=(2, 3), ank=R_ANKLE, foot=R_FOOT, hip=R_HIP, knee=R_KNEE)}


def params(c, cfg):
    n = cfg["solve"]["num_people"]
    return {**cfg["clean"], "in": [file_sig(c.solve / f"p{k}.npz") for k in range(n)]}


def outputs(c, cfg):
    return [c.clean / f"p{k}.npz" for k in range(cfg["solve"]["num_people"])] + [c.clean / "cleanup.json"]


def hysteresis(p, on, off):
    out = np.zeros(len(p), bool)
    state = False
    for t, v in enumerate(p):
        state = v > (off if state else on)
        out[t] = state
    return out


def segments(mask, min_len):
    segs, t = [], 0
    while t < len(mask):
        if mask[t]:
            s = t
            while t < len(mask) and mask[t]:
                t += 1
            if t - s >= min_len:
                segs.append([s, t - 1])
        else:
            t += 1
    return segs


def merge_segments(segs, foot_h, gap, max_lift):
    """两段着地之间空档很短、且期间脚没真正抬起 → 视为同一次着地（置信度抖动造成的切碎）。"""
    if not segs:
        return segs, 0
    out, merged = [segs[0][:]], 0
    for s, e in segs[1:]:
        ps, pe = out[-1]
        g = s - pe - 1
        if g <= gap and (g <= 0 or foot_h[pe + 1:s].max() < max_lift):
            out[-1][1] = e
            merged += 1
        else:
            out.append([s, e])
    return out, merged


def rot_between(u, v):
    u = u / np.linalg.norm(u)
    v = v / np.linalg.norm(v)
    ax = np.cross(u, v)
    s = np.linalg.norm(ax)
    if s < 1e-8:
        return np.eye(3)
    return Rot.from_rotvec(ax / s * np.arctan2(s, u @ v)).as_matrix()


def clean_person(P, par, k):
    J = P["rest_joints"].astype(np.float64)
    T = P["transl"].astype(np.float64).copy()
    conf = P["static_conf"]
    Rl = quats_to_mats(P["quat"])
    L = Rl.shape[0]
    _, pos = fk(J, Rl, T, par)
    st = {}

    # ⓪ 每人单独贴地：按本人站立帧的脚掌关节高度，对齐到"脚掌关节离脚底"的静止高度
    sole = J[[L_FOOT, R_FOOT], 1].mean() - P["rest_verts"][:, 1].min()
    upright = (pos[:, HEAD, 1] - pos[:, PELVIS, 1]) > 0.35
    dy = sole - np.percentile(pos[upright][:, [L_FOOT, R_FOOT], 1].min(1), 10)
    T[:, 1] += dy
    pos[..., 1] += dy
    st["ground_dy_cm"] = round(float(dy * 100), 2)

    # ① 着地检测 + 合并
    for name, sd in SIDES.items():
        sd["p"] = conf[:, list(sd["c"])].max(1)
        if k.get("kin_contact", True):
            # 运动学备用判据：脚掌贴地（离静止脚底高度 kin_height 以内）且水平速度慢 → 着地。
            # ring01（55 秒）实测 GVHMR 给绿衣的着地概率中位数只有 0.03，只靠它锁脚完全失效。
            fh = pos[:, sd["foot"], 1] - sole
            v = np.linalg.norm(np.gradient(gaussian_filter1d(pos[:, sd["foot"]][:, [0, 2]], 1.5, axis=0), axis=0), axis=1) * P["fps"]
            kin = (fh < k["kin_height"]) & (v < k["kin_speed"])
            st[f"{name}_kin_pct"] = round(float(kin.mean() * 100), 1)
            sd["p"] = np.maximum(sd["p"], np.where(kin, 0.75, 0.0))
        m = hysteresis(sd["p"], k["contact_on"], k["contact_off"]) & (pos[:, sd["foot"], 1] < k["foot_max_height"])
        raw = segments(m, k["min_segment"])
        sd["segs"], merged = merge_segments(raw, pos[:, sd["foot"], 1], k["merge_gap"], k["merge_max_lift"])
        st[f"{name}_segments"] = len(sd["segs"])
        st[f"{name}_merged"] = merged
        st[f"{name}_contact_pct"] = round(100 * sum(e - s + 1 for s, e in sd["segs"]) / L, 1)

    # ② 根部水平校正：每段着地的锚点 = 该段脚踝均值；偏移零均值，不改整体位移
    num = np.zeros((L, 2))
    den = np.zeros(L)
    for sd in SIDES.values():
        for s, e in sd["segs"]:
            a = pos[s:e + 1, sd["ank"]][:, [0, 2]]
            w = sd["p"][s:e + 1]
            num[s:e + 1] += (a.mean(0) - a) * w[:, None]
            den[s:e + 1] += w
    ok = den > 0
    off = np.zeros((L, 2))
    t = np.arange(L)
    if ok.any():
        for d in range(2):
            off[:, d] = np.interp(t, t[ok], num[ok, d] / den[ok])
    off = gaussian_filter1d(off, 1.5, axis=0)
    T[:, [0, 2]] += off
    st["root_offset_max_cm"] = [round(float(x * 100), 1) for x in np.abs(off).max(0)]
    Rg, pos = fk(J, Rl, T, par)

    # ③ 两段骨骼 IK：保持膝盖弯曲平面与脚掌世界朝向
    Rl2 = Rl.copy()
    for sd in SIDES.values():
        A_i, B_i, C_i = sd["hip"], sd["knee"], sd["ank"]
        l1 = np.linalg.norm(J[B_i] - J[A_i])
        l2 = np.linalg.norm(J[C_i] - J[B_i])
        for s, e in sd["segs"]:
            anchor = pos[s:e + 1, C_i].mean(0)
            n = e - s + 1
            for t_ in range(s, e + 1):
                i = t_ - s
                w = min(1.0, (i + 1) / k["ik_ramp"], (n - i) / k["ik_ramp"])
                A, B, Cc = pos[t_, A_i], pos[t_, B_i], pos[t_, C_i]
                dv = Cc + w * (anchor - Cc) - A
                dn = np.linalg.norm(dv)
                u = dv / dn
                d = np.clip(dn, abs(l1 - l2) + 1e-4, l1 + l2 - 1e-4)
                pole = (B - A) - u * ((B - A) @ u)
                pn = np.linalg.norm(pole)
                pole = pole / pn if pn > 1e-6 else Rg[t_, A_i] @ np.array([0, 0, 1.0])
                aa = (l1 * l1 - l2 * l2 + d * d) / (2 * d)
                hh = np.sqrt(max(l1 * l1 - aa * aa, 0))
                Bn = A + u * aa + pole * hh
                Cn = A + u * d
                R1 = rot_between(B - A, Bn - A)
                R2 = rot_between(A + R1 @ (Cc - A) - Bn, Cn - Bn)
                G_hip = R1 @ Rg[t_, A_i]
                G_knee = R2 @ R1 @ Rg[t_, B_i]
                Rl2[t_, A_i] = Rg[t_, par[A_i]].T @ G_hip
                Rl2[t_, B_i] = G_hip.T @ G_knee
                Rl2[t_, C_i] = G_knee.T @ Rg[t_, C_i]
    out = dict(P)
    out["quat"] = mats_to_quats(Rl2).astype(np.float32)
    out["transl"] = T.astype(np.float32)
    return out, st


def run(c, cfg, args):
    k = cfg["clean"]
    par = np.load(c.solve / "smplx_common.npz")["parents"]
    report = {}
    for i in range(cfg["solve"]["num_people"]):
        P = dict(np.load(c.solve / f"p{i}.npz"))
        out, st = clean_person(P, par, k)
        np.savez(c.clean / f"p{i}.npz", **out)
        report[f"p{i}"] = st
        log(f"p{i}: {st}")
    shutil.copy(c.solve / "smplx_common.npz", c.clean / "smplx_common.npz")
    shutil.copy(c.solve / "camera.json", c.clean / "camera.json")
    save_json(c.clean / "cleanup.json", report)
    return report
