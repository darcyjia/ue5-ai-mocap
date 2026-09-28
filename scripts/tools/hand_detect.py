"""手部弯曲度识别（在 .venv-tools 里运行：mediapipe + opencv）。
沿前臂方向在手腕外侧裁一块、放大后交给 MediaPipe HandLandmarker，取 3D 世界坐标关键点，
算四指（食/中/无名/小）的总弯曲角度：伸直约 0–40°，握拳约 180° 以上。
输出 JSON：curl[p][hand][frame]（度，识别不到为 null）、识别率，和抽样的裁剪图。

用法：python hand_detect.py --video V --vit-dir SOLVE_DIR --num 2 --out OUT_DIR --model hand_landmarker.task
"""
import argparse
import json
import os

import cv2
import numpy as np
from mediapipe import Image, ImageFormat
from mediapipe.tasks.python import BaseOptions, vision

ap = argparse.ArgumentParser()
ap.add_argument("--video", required=True)
ap.add_argument("--vit-dir", required=True)
ap.add_argument("--num", type=int, default=2)
ap.add_argument("--out", required=True)
ap.add_argument("--model", required=True)
ap.add_argument("--crop", type=int, default=224)
ap.add_argument("--sample-every", type=int, default=12)
a = ap.parse_args()
os.makedirs(os.path.join(a.out, "crops"), exist_ok=True)

# COCO17：左肘 7 右肘 8 左腕 9 右腕 10
ARM = {"L": (7, 9), "R": (8, 10)}
FINGERS = [(5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20)]

lm = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
    base_options=BaseOptions(model_asset_path=a.model), num_hands=2, running_mode=vision.RunningMode.IMAGE,
    min_hand_detection_confidence=0.3, min_hand_presence_confidence=0.3))
vits = [np.load(os.path.join(a.vit_dir, f"vit_p{k}.npy")) for k in range(a.num)]


def angle(u, v):
    c = np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v) + 1e-9)
    return np.degrees(np.arccos(np.clip(c, -1, 1)))


def curl(world):
    """四指总弯曲：每根手指 腕→MCP、MCP→PIP、PIP→DIP、DIP→TIP 相邻骨段夹角之和，再取平均。"""
    w = np.array([[p.x, p.y, p.z] for p in world])
    tot = []
    for m, p, d, t in FINGERS:
        segs = [w[m] - w[0], w[p] - w[m], w[d] - w[p], w[t] - w[d]]
        tot.append(sum(angle(segs[i], segs[i + 1]) for i in range(3)))
    return float(np.mean(tot))


cap = cv2.VideoCapture(a.video)
L = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
H0, W0 = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)), int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
vit_w = None
res = {"curl": [[[None] * L for _ in ARM] for _ in range(a.num)], "hands": list(ARM), "L": L}
samples = []
f = 0
while True:
    ok, frame = cap.read()
    if not ok or f >= L:
        break
    for k in range(a.num):
        v = vits[k]
        if f >= len(v):
            continue
        # ViTPose 坐标是按原视频像素的
        for hi, (hname, (je, jw)) in enumerate(ARM.items()):
            e, w = v[f, je], v[f, jw]
            if w[2] < 0.3:
                continue
            fore = w[:2] - e[:2]
            flen = float(np.linalg.norm(fore))
            if flen < 3:
                continue
            c = w[:2] + 0.45 * fore                      # 手掌中心大约在手腕外侧半个前臂处…的一部分
            half = max(0.75 * flen, 20.0)
            x0, y0, x1, y1 = int(c[0] - half), int(c[1] - half), int(c[0] + half), int(c[1] + half)
            pad = cv2.copyMakeBorder(frame, max(0, -y0), max(0, y1 - H0), max(0, -x0), max(0, x1 - W0),
                                     cv2.BORDER_REPLICATE)
            crop = pad[y0 + max(0, -y0):y1 + max(0, -y0), x0 + max(0, -x0):x1 + max(0, -x0)]
            if crop.size == 0:
                continue
            crop = cv2.resize(crop, (a.crop, a.crop), interpolation=cv2.INTER_CUBIC)
            r = lm.detect(Image(image_format=ImageFormat.SRGB, data=cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)))
            val = None
            if r.hand_landmarks:
                # 多只手时取手腕离“预期手腕位置”最近的那只（预期手腕在裁剪图里的坐标）
                ew = ((w[:2] - np.array([x0, y0])) / (2 * half))
                best = min(range(len(r.hand_landmarks)),
                           key=lambda i: np.hypot(r.hand_landmarks[i][0].x - ew[0], r.hand_landmarks[i][0].y - ew[1]))
                val = curl(r.hand_world_landmarks[best])
            res["curl"][k][hi][f] = val
            if f % a.sample_every == 0:
                name = f"f{f:04d}_p{k}{hname}.jpg"
                cv2.putText(crop, f"f{f} p{k}{hname} {'' if val is None else int(val)}", (4, 16),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
                cv2.imwrite(os.path.join(a.out, "crops", name), crop)
                samples.append(name)
    f += 1
res["detect_rate"] = [[float(np.mean([x is not None for x in h])) for h in p] for p in res["curl"]]
res["samples"] = samples
json.dump(res, open(os.path.join(a.out, "raw.json"), "w"), indent=0)
print("detect_rate", res["detect_rate"])
