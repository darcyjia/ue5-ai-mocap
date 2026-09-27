"""在 WSL 的 GVHMR 环境里运行：多人追踪 → 每人 GVHMR 解算 → 导出到共享坐标系。
cwd 必须是 GVHMR 仓库根目录。输出（--work）：
  p{k}.npz        rest_verts/rest_joints/quat(wxyz)/transl/fps/static_conf/betas，Y 朝上、米、地面 Y=0
  smplx_common.npz faces/weights/parents
  camera.json     原机位（Y 朝上世界里的 R、pos、lens、res、fps）
  vit_p{k}.npy    ViTPose 2D 关键点（质检用）
  p{k}_incam.mp4  GVHMR 叠合预览
  track.json / solve.json
人物编号按画面从左到右：p0 最左。"""
import argparse
import json
import os
import shutil
import subprocess
import sys

import numpy as np
import torch

ap = argparse.ArgumentParser()
ap.add_argument("--video", required=True)
ap.add_argument("--work", required=True)
ap.add_argument("--out", required=True, help="GVHMR 中间结果目录（WSL 本地盘）")
ap.add_argument("--num", type=int, default=2)
ap.add_argument("--f_mm", type=float, default=0)
a = ap.parse_args()

G = os.getcwd()
sys.path.insert(0, G)
os.makedirs(a.work, exist_ok=True)
import hmr4d.utils.preproc.tracker as T
from hmr4d.utils.geo.hmr_cam import get_bbx_xys_from_xyxy
from hmr4d.utils.video_io_utils import get_video_lwh
import smplx
from scipy.spatial.transform import Rotation as Rot
from scipy.signal import savgol_filter
import cv2


def log(*x):
    print("[solve]", *x, flush=True)


cap = cv2.VideoCapture(a.video)
FPS = float(cap.get(cv2.CAP_PROP_FPS) or 24.0)
cap.release()
L, W, H = get_video_lwh(a.video)
stem = os.path.splitext(os.path.basename(a.video))[0]
log(f"video {W}x{H} L={L} fps={FPS:.3f}")

# ---------- 1 多人追踪：取面积最大的 num 条轨迹，按画面 x 从左到右编号 ----------
tr = T.Tracker()
hist = tr.track(a.video)
id2f, id2b, ids = T.Tracker.sort_track_length(hist, a.video)
del tr
track = {"L": L, "fps": FPS, "W": W, "H": H,
         "all_tracks": [{"id": int(t), "frames": len(id2f[t]), "coverage": len(id2f[t]) / L} for t in ids]}
if len(ids) < a.num:
    raise SystemExit(f"只追踪到 {len(ids)} 个人，需要 {a.num}")
tracks = []
for tid in ids[:a.num]:
    fr = torch.tensor(id2f[tid])
    bb = torch.tensor(id2b[tid])
    m = T.frame_id_to_mask(fr, L)
    bb = T.rearrange_by_mask(bb, m)
    bb = T.linear_interpolate_frame_ids(bb, T.get_frame_id_list_from_mask(~m))
    bb = T.moving_average_smooth(bb, window_size=5, dim=0)
    bb = T.moving_average_smooth(bb, window_size=5, dim=0)
    tracks.append((int(tid), bb.float()))
tracks.sort(key=lambda t: t[1][:, [0, 2]].mean().item())
track["people"] = [{"p": k, "track_id": tid, "coverage": len(id2f[tid]) / L,
                    "mean_x": float(bb[:, [0, 2]].mean())} for k, (tid, bb) in enumerate(tracks)]
json.dump(track, open(f"{a.work}/track.json", "w"), indent=1)
log("tracks", [(p["p"], p["track_id"], round(p["coverage"], 3)) for p in track["people"]],
    "total ids", len(ids))

# ---------- 2 每人跑一遍 GVHMR（预置 bbx.pt，demo 会跳过它自己的单人追踪） ----------
results = []
for k, (tid, bb) in enumerate(tracks):
    root = os.path.join(a.out, f"p{k}")
    d = os.path.join(root, stem)
    pre = os.path.join(d, "preprocess")
    os.makedirs(pre, exist_ok=True)
    for f in ("vitpose.pt", "vit_features.pt", "slam_results.pt"):      # 轨迹变了，旧缓存必须清掉
        if os.path.exists(os.path.join(pre, f)):
            os.remove(os.path.join(pre, f))
    if os.path.exists(os.path.join(d, "hmr4d_results.pt")):
        os.remove(os.path.join(d, "hmr4d_results.pt"))
    torch.save({"bbx_xyxy": bb, "bbx_xys": get_bbx_xys_from_xyxy(bb, base_enlarge=1.2).float()},
               os.path.join(pre, "bbx.pt"))
    cmd = [sys.executable, "tools/demo/demo.py", f"--video={a.video}", "-s", "--output_root", root]
    if a.f_mm > 0:
        cmd += ["--f_mm", str(a.f_mm)]
    r = subprocess.run(cmd, cwd=G, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.returncode != 0 or not os.path.exists(os.path.join(d, "hmr4d_results.pt")):
        print(r.stdout[-4000:])
        raise SystemExit(f"GVHMR 解算 p{k} 失败")
    log(f"p{k} solved")
    results.append(torch.load(os.path.join(d, "hmr4d_results.pt"), map_location="cpu"))
    vit = torch.load(os.path.join(pre, "vitpose.pt"), map_location="cpu")
    np.save(f"{a.work}/vit_p{k}.npy", vit.numpy() if hasattr(vit, "numpy") else np.array(vit))
    if os.path.exists(os.path.join(d, "1_incam.mp4")):
        shutil.copy(os.path.join(d, "1_incam.mp4"), f"{a.work}/p{k}_incam.mp4")

# ---------- 3 导出到共享坐标系 ----------
# GVHMR 的 global 结果每人各自归一化（首帧放原点），不能用于多人；用相机空间结果 + 重力方向。
model = smplx.create("inputs/checkpoints/body_models", model_type="smplx", gender="neutral",
                     num_betas=10, use_pca=False, flat_hand_mean=True)
np.savez(f"{a.work}/smplx_common.npz", faces=model.faces.astype(np.int32),
         weights=model.lbs_weights.numpy().astype(np.float32), parents=model.parents.numpy().astype(np.int32))


def fwd(betas, go, bp, tr):
    n = go.shape[0]
    z = lambda k: torch.zeros((n, k))
    o = model(betas=torch.tensor(np.repeat(betas[None], n, 0), dtype=torch.float32),
              global_orient=torch.tensor(go, dtype=torch.float32), body_pose=torch.tensor(bp, dtype=torch.float32),
              transl=torch.tensor(tr, dtype=torch.float32), jaw_pose=z(3), leye_pose=z(3), reye_pose=z(3),
              left_hand_pose=z(45), right_hand_pose=z(45), expression=z(10))
    return o.vertices.detach().numpy(), o.joints[:, :55].detach().numpy()


def pelvis_rest(betas):
    _, J = fwd(betas, np.zeros((1, 3)), np.zeros((1, 63)), np.zeros((1, 3)))
    return J[0, 0]


people = []
for r in results:
    inc = {k: (v[0] if v.dim() == 3 else v).numpy().astype(np.float64) for k, v in r["smpl_params_incam"].items()}
    gv = r["net_outputs"]["decode_dict"]["global_orient_gv"][0].numpy()
    people.append(dict(inc=inc, Rc2gv=Rot.from_rotvec(gv) * Rot.from_rotvec(inc["global_orient"]).inv(),
                       K=r["K_fullimg"][0].numpy(),
                       sc=torch.sigmoid(r["net_outputs"]["static_conf_logits"][0]).numpy()))

allR = Rot.concatenate([p["Rc2gv"] for p in people])
Rm = allR.mean()
dev = np.degrees((allR * Rm.inv()).magnitude())
agree = [float(np.degrees((p["Rc2gv"].mean() * Rm.inv()).magnitude())) for p in people]
R = Rm.as_matrix()


def apply_rot(Rw, q):
    j0 = pelvis_rest(q["betas"])
    q["go"] = (Rot.from_matrix(Rw) * Rot.from_rotvec(q["go"])).as_rotvec()
    q["tr"] = (Rw @ (q["tr"] + j0).T).T - j0


res = []
for p in people:
    inc = p["inc"]
    q = dict(betas=inc["betas"].mean(0), go=inc["global_orient"], bp=inc["body_pose"], tr=inc["transl"].copy(),
             L=inc["body_pose"].shape[0], sc=p["sc"])
    apply_rot(R, q)
    res.append(q)

up = np.mean([(fwd(q["betas"], q["go"], q["bp"], q["tr"])[1][:, 15] - fwd(q["betas"], q["go"], q["bp"], q["tr"])[1][:, 0]).mean(0) for q in res], 0)
up /= np.linalg.norm(up)
if up[1] < 0:                                   # GV 坐标系 Y 朝下，翻成 Y 朝上
    F = Rot.from_euler("x", 180, degrees=True).as_matrix()
    R = F @ R
    for q in res:
        apply_rot(F, q)
tilt_up = float(np.degrees(np.arccos(abs(up[1]))))

jit = []
for q in res:                                   # 单目深度抖动：根平移轻度平滑
    raw = q["tr"].copy()
    q["tr"] = savgol_filter(q["tr"], 9, 2, axis=0)
    jit.append(float(100 * np.sqrt(((raw - q["tr"]) ** 2).sum(1).mean())))

mins = []
for q in res:                                   # 地面：只用站立帧（倒地时单目常把身体估到地下）
    V, J = fwd(q["betas"], q["go"], q["bp"], q["tr"])
    upright = (J[:, 15, 1] - J[:, 0, 1]) > 0.35
    mins.append(V[upright][:, :, 1].min(1))
floor = float(np.percentile(np.concatenate(mins), 10))
for q in res:
    q["tr"][:, 1] -= floor

for k, q in enumerate(res):
    Lk = q["L"]
    quat = np.zeros((Lk, 55, 4))
    quat[..., 0] = 1.0
    quat[:, 0] = Rot.from_rotvec(q["go"]).as_quat()[:, [3, 0, 1, 2]]
    quat[:, 1:22] = Rot.from_rotvec(q["bp"].reshape(-1, 3)).as_quat().reshape(Lk, 21, 4)[..., [3, 0, 1, 2]]
    Vr, Jr = fwd(q["betas"], np.zeros((1, 3)), np.zeros((1, 63)), np.zeros((1, 3)))
    np.savez(f"{a.work}/p{k}.npz", rest_verts=Vr[0].astype(np.float32), rest_joints=Jr[0].astype(np.float32),
             quat=quat.astype(np.float32), transl=q["tr"].astype(np.float32), fps=round(FPS),
             static_conf=q["sc"].astype(np.float32), betas=q["betas"].astype(np.float32))

K = people[0]["K"]
Wc, Hc = 2 * K[0, 2], 2 * K[1, 2]
cam = dict(R=(R @ np.diag([1, -1, -1])).tolist(), pos=[0.0, -floor, 0.0],
           lens=float(K[0, 0] / Wc * 36.0), res=[int(round(Wc)), int(round(Hc))], fps=round(FPS), fps_exact=FPS)
json.dump(cam, open(f"{a.work}/camera.json", "w"), indent=1)
dist = []
if len(res) >= 2:
    dist = np.linalg.norm(res[0]["tr"][:, [0, 2]] - res[1]["tr"][:, [0, 2]], axis=1)
info = {"rc2gv_dev_median": float(np.median(dev)), "rc2gv_dev_p95": float(np.percentile(dev, 95)),
        "rc2gv_person_agree_deg": agree, "up_tilt_deg": tilt_up, "root_jitter_cm": jit,
        "camera_height_m": -floor, "lens_mm": cam["lens"],
        "pelvis_dist_m": {"median": float(np.median(dist)), "min": float(np.min(dist)), "max": float(np.max(dist))} if len(dist) else None}
json.dump(info, open(f"{a.work}/solve.json", "w"), indent=1)
log("done", json.dumps(info))
