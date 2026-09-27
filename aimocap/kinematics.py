"""SMPL-X 前向运动学等共用函数（Windows 侧，numpy/scipy）。
约定：npz 里 quat 为 (L,55,4) wxyz 局部旋转，所有骨骼静止朝向为单位阵，Y 朝上、米。"""
import numpy as np
from scipy.spatial.transform import Rotation as Rot

# SMPL-X 关节编号
PELVIS, L_HIP, R_HIP, SPINE1, L_KNEE, R_KNEE, SPINE2, L_ANKLE, R_ANKLE, SPINE3, L_FOOT, R_FOOT, NECK = range(13)
HEAD = 15
L_WRIST, R_WRIST = 20, 21
# ViTPose(COCO17) 的脚踝
COCO_L_ANKLE, COCO_R_ANKLE = 15, 16


def quats_to_mats(q):
    L = q.shape[0]
    return Rot.from_quat(q.reshape(-1, 4)[:, [1, 2, 3, 0]]).as_matrix().reshape(L, -1, 3, 3)


def mats_to_quats(R):
    L = R.shape[0]
    return Rot.from_matrix(R.reshape(-1, 3, 3)).as_quat()[:, [3, 0, 1, 2]].reshape(L, -1, 4)


def fk(J, Rl, T, parents):
    """返回 (全局旋转 (L,55,3,3), 关节位置 (L,55,3))。"""
    L = Rl.shape[0]
    Rg = np.zeros((L, 55, 3, 3))
    pos = np.zeros((L, 55, 3))
    for i in range(55):
        p = parents[i]
        if p < 0:
            Rg[:, i] = Rl[:, i]
            pos[:, i] = J[i] + T
        else:
            Rg[:, i] = Rg[:, p] @ Rl[:, i]
            pos[:, i] = pos[:, p] + Rg[:, p] @ (J[i] - J[p])
    return Rg, pos


def load_person(npz_path, parents):
    P = dict(np.load(npz_path))
    Rl = quats_to_mats(P["quat"])
    Rg, pos = fk(P["rest_joints"].astype(np.float64), Rl, P["transl"].astype(np.float64), parents)
    return P, Rl, Rg, pos


def project(pos, cam):
    """世界点 -> 像素坐标 (u, v) 与深度 z。cam 为 solve/camera.json。"""
    R, P = np.array(cam["R"]), np.array(cam["pos"])
    W, _ = cam["res"]
    fx = cam["lens"] / 36.0 * W
    c = (pos - P) @ R                     # Blender 相机坐标：x 右 y 上 z 后
    z = -c[..., 2]
    u = fx * c[..., 0] / z + cam["res"][0] / 2
    v = -fx * c[..., 1] / z + cam["res"][1] / 2
    return u, v, z, fx
