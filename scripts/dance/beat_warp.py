"""节拍对齐（动作微调速）：把动作的重音时刻（闪身步的急停等）挪到配乐的强拍上，段与段之间线性变速，总时长不变。
.venv-tools/Scripts/python.exe beat_warp.py --npz-dir <素材>/impact --out-dir <素材>/beat --music music_fit.wav --hits 1.3,2.87,... [--delay 0.1] [--max-stretch 0.3]
输出 out-dir/p*.npz（旋转用相邻帧四元数插值，位移线性）+ smplx_common.npz + warp.json；之后用 export_fbx.py --npz-dir out-dir 出 FBX。
强拍网格：librosa 节拍里取间隔最接近重音间隔的子网格（每 m 拍），相位取和重音最贴的那组。"""
import argparse
import glob
import json
import os
import shutil

import librosa
import numpy as np


def grid(music, hits, every=0, subdiv=1):
    """节拍网格。music 旁边有 beat_fit 写的 <名>.json（含 src + start）时，在整首原曲上测拍再平移：
    短片段上测拍可能锁到反拍（10-17 实测差半拍），和 beat_fit 选起点用的网格不一致。"""
    meta = os.path.splitext(music)[0] + ".json"
    if os.path.exists(meta):
        m_ = json.load(open(meta, encoding="utf-8"))
        y, sr = librosa.load(m_["src"], sr=22050)
        _, bt = librosa.beat.beat_track(y=y, sr=sr, units="time", tightness=300)
        bt = bt - m_["start"]
        bt = bt[(bt > -1) & (bt < m_["secs"] + 1)]
    else:
        y, sr = librosa.load(music, sr=22050)
        _, bt = librosa.beat.beat_track(y=y, sr=sr, units="time", tightness=300)
    if subdiv > 1:                                   # 细分：拍与拍之间插点（八分音符）
        bt = np.sort(np.concatenate([bt] + [bt[:-1] + np.diff(bt) * k / subdiv for k in range(1, subdiv)]))
    hp = float(np.median(np.diff(hits)))
    bp = float(np.median(np.diff(bt)))
    m = every or max(1, int(round(hp / bp)))      # 混合动作（闪 + 踢 + 回头）间隔不均：--every 1 吸附到最近的拍
    best = None
    for ph in range(m):
        g = bt[ph::m]
        err = np.mean([np.min(np.abs(g - h)) for h in hits])
        if best is None or err < best[0]:
            best = (err, g, ph)
    return best[1], m, bp, best[0]


def resample(P, src_t, fps):
    q = P["quat"].astype(np.float64)
    tr = P["transl"].astype(np.float64)
    n = q.shape[0]
    x = np.clip(src_t * fps, 0, n - 1)
    i0 = np.floor(x).astype(int)
    i1 = np.minimum(i0 + 1, n - 1)
    w = (x - i0)[:, None, None]
    q0, q1 = q[i0], q[i1]
    sgn = np.sign(np.sum(q0 * q1, -1, keepdims=True))
    sgn[sgn == 0] = 1
    qq = q0 * (1 - w) + q1 * sgn * w
    qq /= np.linalg.norm(qq, axis=-1, keepdims=True)
    out = {k: P[k] for k in P.files}
    out["quat"] = qq.astype(P["quat"].dtype)
    out["transl"] = (tr[i0] * (1 - w[:, :, 0]) + tr[i1] * w[:, :, 0]).astype(P["transl"].dtype)
    if "static_conf" in P.files:
        out["static_conf"] = P["static_conf"][np.rint(x).astype(int)]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--npz-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--music", required=True)
    ap.add_argument("--hits", required=True)
    ap.add_argument("--delay", type=float, default=0.1)
    ap.add_argument("--max-stretch", type=float, default=0.3)
    ap.add_argument("--every", type=int, default=0, help="强拍间隔（拍数），0 = 按重音间隔自动选")
    ap.add_argument("--subdiv", type=int, default=1, help="把每拍细分成几份（2 = 八分音符也能落）")
    a = ap.parse_args()
    hits = np.array([float(v) for v in a.hits.split(",")]) + a.delay
    g, m, bp, err0 = grid(a.music, hits, a.every, a.subdiv)
    files = sorted(glob.glob(os.path.join(a.npz_dir, "p*.npz")))
    P0 = np.load(files[0])
    fps = float(P0["fps"])
    n = P0["quat"].shape[0]
    T = (n - 1) / fps
    S, G = [0.0], [0.0]
    for h in hits:
        tgt = float(g[np.argmin(np.abs(g - h))])
        if tgt <= G[-1] or h <= S[-1] or tgt >= T:
            continue
        r = (tgt - G[-1]) / (h - S[-1])
        if abs(r - 1) > a.max_stretch:
            continue
        S.append(float(h))
        G.append(tgt)
    if (T - G[-1]) > 0 and abs((T - G[-1]) / max(T - S[-1], 1e-3) - 1) <= a.max_stretch:
        S.append(T)
        G.append(T)
    else:                                   # 尾段比例超限：最后一个锚点之后保持原速
        S.append(S[-1] + (T - G[-1]))
        G.append(T)
    tau = np.arange(n) / fps
    src_t = np.interp(tau, G, S)
    os.makedirs(a.out_dir, exist_ok=True)
    for f in files:
        out = resample(np.load(f), src_t, fps)
        np.savez(os.path.join(a.out_dir, os.path.basename(f)), **out)
    common = os.path.join(a.npz_dir, "smplx_common.npz")
    if os.path.exists(common):
        shutil.copy(common, os.path.join(a.out_dir, "smplx_common.npz"))
    ratios = [round((G[i + 1] - G[i]) / (S[i + 1] - S[i]), 3) for i in range(len(S) - 1)]
    rep = {"music": a.music, "beat_period": round(bp, 4), "every": m, "hit_err_before_ms": int(err0 * 1000),
           "anchors_src": [round(x, 3) for x in S], "anchors_dst": [round(x, 3) for x in G], "speed_ratios": ratios,
           "used_hits": len(S) - 2, "total_hits": len(hits)}
    json.dump(rep, open(os.path.join(a.out_dir, "warp.json"), "w", encoding="utf-8"), indent=1)
    print(json.dumps(rep, ensure_ascii=False))


if __name__ == "__main__":
    main()
