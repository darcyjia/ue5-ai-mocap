"""舞蹈动作的重音时刻（给 beat_fit / beat_warp 当 --hits）：闪（骨盆水平速度峰）、踢（脚踝离地最高点）、回头（头部偏航角速度峰）。
.venv-tools/Scripts/python.exe accents.py <p0.npz> <smplx_common.npz> [--flash 0.9] [--kick 0.18] [--turn 150] [--merge 0.35]
输出 JSON：每类时刻 + 合并后的 hits（同一 0.35 s 内只留一个，优先 踢 > 闪 > 回头）。时刻已含“定住”的延迟：闪 +0.1 s。"""
import argparse
import json

import numpy as np
from scipy.spatial.transform import Rotation as Rot

PELVIS, L_ANK, R_ANK, NECK, HEAD = 0, 7, 8, 12, 15


def fk(npz, parents):
    P = np.load(npz)
    q = P["quat"].astype(np.float64)
    L = q.shape[0]
    Rl = Rot.from_quat(q.reshape(-1, 4)[:, [1, 2, 3, 0]]).as_matrix().reshape(L, -1, 3, 3)
    J, T = P["rest_joints"].astype(np.float64), P["transl"].astype(np.float64)
    Rg = np.zeros((L, 55, 3, 3))
    pos = np.zeros((L, 55, 3))
    for i in range(55):
        p = parents[i]
        if p < 0:
            Rg[:, i], pos[:, i] = Rl[:, i], J[i] + T
        else:
            Rg[:, i] = Rg[:, p] @ Rl[:, i]
            pos[:, i] = pos[:, p] + Rg[:, p] @ (J[i] - J[p])
    return pos, Rg, float(P["fps"])


def peaks(x, thr, min_gap):
    out = []
    for i in range(1, len(x) - 1):
        if x[i] > thr and x[i] >= x[i - 1] and x[i] > x[i + 1]:
            if out and i - out[-1] < min_gap:
                if x[i] > x[out[-1]]:
                    out[-1] = i
                continue
            out.append(i)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("npz")
    ap.add_argument("common")
    ap.add_argument("--flash", type=float, default=0.9, help="骨盆水平速度门槛 m/s")
    ap.add_argument("--kick", type=float, default=0.18, help="脚踝离地高度门槛 m")
    ap.add_argument("--turn", type=float, default=150.0, help="头相对躯干的偏航角速度门槛 度/秒")
    ap.add_argument("--merge", type=float, default=0.35)
    a = ap.parse_args()
    pos, Rg, fps = fk(a.npz, np.load(a.common)["parents"].astype(int))
    sm = lambda x: np.convolve(x, np.ones(3) / 3, "same")  # noqa: E731
    gap = int(a.merge * fps)
    v = sm(np.linalg.norm(np.gradient(pos[:, PELVIS, [0, 2]], 1 / fps, axis=0), axis=1))
    flash = [i / fps + 0.1 for i in peaks(v, a.flash, gap)]
    kick = []
    for ank in (L_ANK, R_ANK):
        h = pos[:, ank, 1] - np.percentile(pos[:, ank, 1], 10)
        kick += [i / fps for i in peaks(sm(h), a.kick, gap)]
    # 头相对颈的偏航（绕竖轴）角速度
    rel = np.einsum("tij,tjk->tik", np.transpose(Rg[:, NECK], (0, 2, 1)), Rg[:, HEAD])
    yaw = np.unwrap(np.arctan2(rel[:, 0, 2], rel[:, 2, 2]))
    w = sm(np.abs(np.gradient(np.degrees(yaw), 1 / fps)))
    turn = [i / fps + 0.05 for i in peaks(w, a.turn, gap)]
    ev = sorted([(t, 0, "kick") for t in kick] + [(t, 1, "flash") for t in flash] + [(t, 2, "turn") for t in turn])
    hits = []
    for t, pr, kind in ev:
        if hits and t - hits[-1][0] < a.merge:
            if pr < hits[-1][1]:
                hits[-1] = (t, pr, kind)
            continue
        hits.append((t, pr, kind))
    print(json.dumps({"flash": [round(t, 2) for t in flash], "kick": sorted(round(t, 2) for t in kick),
                      "turn": [round(t, 2) for t in turn], "hits": [round(t, 3) for t, _, _ in hits],
                      "kinds": [k for _, _, k in hits]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
