"""Blender 脚本共用：参数解析、SMPL-X 骨骼名。"""
import sys


def args():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    d = {}
    i = 0
    while i < len(a):
        k = a[i].lstrip("-").replace("-", "_")
        if i + 1 < len(a) and not a[i + 1].startswith("--"):
            d[k] = a[i + 1]
            i += 2
        else:
            d[k] = True
            i += 1
    return d


SMPLX = ["pelvis", "left_hip", "right_hip", "spine1", "left_knee", "right_knee", "spine2", "left_ankle",
         "right_ankle", "spine3", "left_foot", "right_foot", "neck", "left_collar", "right_collar", "head",
         "left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist", "jaw",
         "left_eye", "right_eye"]
for _s in ("left", "right"):
    for _f in ("index", "middle", "pinky", "ring", "thumb"):
        SMPLX += [f"{_s}_{_f}{i}" for i in (1, 2, 3)]

# UE / MetaHuman 骨骼命名（与 SMPLX 一一对应）
UE = ["pelvis", "thigh_l", "thigh_r", "spine_01", "calf_l", "calf_r", "spine_02", "foot_l", "foot_r",
      "spine_03", "ball_l", "ball_r", "neck_01", "clavicle_l", "clavicle_r", "head", "upperarm_l",
      "upperarm_r", "lowerarm_l", "lowerarm_r", "hand_l", "hand_r", "jaw", "eye_l", "eye_r"]
for _s in ("l", "r"):
    for _f in ("index", "middle", "pinky", "ring", "thumb"):
        UE += [f"{_f}_0{i}_{_s}" for i in (1, 2, 3)]

PALETTE = [(0.12, 0.25, 0.85, 1), (0.25, 0.62, 0.22, 1), (0.85, 0.45, 0.10, 1), (0.60, 0.20, 0.70, 1)]
