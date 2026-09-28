"""手型预设：拳 / 半握（戒备）/ 掌 / 放松。
不手写旋转轴：由 SMPL-X 静止骨架自动算（静止姿态为 T-pose、手心朝下）。
- 四指：弯曲轴 = 骨骼方向 × 手掌法线，正角度朝手心弯；MCP 另绕手掌法线旋转，向中指并拢。
- 拇指：指甲与四指成 90°，它的弯曲是在手掌平面内横扫向小指一侧（绕手掌法线），
  第一节再加"对掌"（朝手心方向转下去）。横扫方向由程序判定：选让拇指尖靠近中指根部的那一侧。
所有骨骼静止朝向为单位阵（我们的约定），所以静止坐标下的轴可直接作为局部旋转轴。"""
import numpy as np
from scipy.spatial.transform import Rotation as Rot

STATES = ["fist", "guard", "palm", "relaxed"]
STATE_CN = {"fist": "拳", "guard": "半握", "palm": "掌", "relaxed": "放松"}
FINGERS = {"index": 0, "middle": 3, "pinky": 6, "ring": 9, "thumb": 12}   # 左手 25 起，右手 40 起
N = np.array([0.0, -1.0, 0.0])                                             # 手掌法线（手心朝下）

# 角度（度）：四指 mcp/pip/dip 弯曲、together 并拢比例；拇指 sweep 横扫（第一节）、oppose 对掌（第一节朝手心）、t2/t3 第二三节横扫
PRESETS = {
    "fist":    {"mcp": 82, "pip": 98, "dip": 55, "together": 0.8, "sweep": 25, "oppose": 50, "t2": 45, "t3": 35},
    "guard":   {"mcp": 52, "pip": 65, "dip": 35, "together": 0.6, "sweep": 18, "oppose": 30, "t2": 22, "t3": 15},
    "palm":    {"mcp": -4, "pip": 0, "dip": 0, "together": 1.0, "squeeze": 3, "sweep": 18, "oppose": 8, "t2": 0, "t3": 0},
    "relaxed": {"mcp": 15, "pip": 25, "dip": 15, "together": 0.3, "sweep": 8, "oppose": 12, "t2": 8, "t3": 5},
}


def _unit(v):
    return v / np.linalg.norm(v)


def _inplane(v):
    return _unit(v - N * (v @ N))


def _signed_angle_about_n(a, b):
    """a 转到 b 绕手掌法线 N 的有符号角（弧度），a、b 先投影到手掌平面。"""
    a, b = _inplane(a), _inplane(b)
    return np.arctan2(np.cross(a, b) @ N, a @ b)


def preset_rotvecs(J, state):
    """返回 (30, 3)：左手 15 个关节 + 右手 15 个关节的局部轴角（弧度）。J 为静止关节 (55,3)。"""
    p = PRESETS[state]
    out = np.zeros((30, 3))
    for base in (25, 40):
        mid = _unit(J[base + 4] - J[base + 3])                          # 中指方向
        for name, off in FINGERS.items():
            j1, j2, j3 = base + off, base + off + 1, base + off + 2
            d1, d2 = _unit(J[j2] - J[j1]), _unit(J[j3] - J[j2])
            if name != "thumb":
                close = _signed_angle_about_n(d1, mid)
                k = {"index": 1, "middle": 0, "ring": 1, "pinky": 2}[name]          # 离中指几根手指
                extra = np.sign(close) * np.radians(p.get("squeeze", 0)) * k        # 再往中指收一点，指缝更小
                spread = Rot.from_rotvec(N * (close * p["together"] + extra))
                d1s = spread.apply(d1)
                for j, d, key in ((j1, d1s, "mcp"), (j2, d2, "pip"), (j3, d2, "dip")):
                    flex = Rot.from_rotvec(_unit(np.cross(d, N)) * np.radians(p[key]))
                    out[j - 25] = ((flex * spread) if j == j1 else flex).as_rotvec()
            else:
                tip = J[j3] + (J[j3] - J[j2])
                s = min((1, -1), key=lambda sg: np.linalg.norm(
                    J[j1] + Rot.from_rotvec(N * np.radians(30) * sg).apply(tip - J[j1]) - J[base + 3]))
                sweep1 = Rot.from_rotvec(N * np.radians(p["sweep"]) * s)
                oppose = Rot.from_rotvec(_unit(np.cross(d1, N)) * np.radians(p["oppose"]))
                out[j1 - 25] = (sweep1 * oppose).as_rotvec()
                out[j2 - 25] = N * np.radians(p["t2"]) * s
                out[j3 - 25] = N * np.radians(p["t3"]) * s
    return out


def all_presets(J):
    return {s: preset_rotvecs(J, s) for s in STATES}
