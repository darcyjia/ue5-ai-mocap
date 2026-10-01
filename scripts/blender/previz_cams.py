"""运镜预演：按镜头表 shots.json 给每个镜头建相机、逐帧打关键帧，按剪辑顺序渲染预演。
blender -b previz_mh.blend --python previz_cams.py -- --shots shots.json --impacts impacts.json --out-blend X.blend
        [--render-dir D --res 960x540]
相机自动算：按两人骨骼的逐帧位置瞄准；所有机位在原机位一侧（180° 轴线）；打击帧加轻微震动。
开场定格放在时间轴 -N..0 帧（动画停在第 1 帧）；重复剪辑的每个角度各一台相机、对着同一段动画。
输出 edl.json（剪辑表：成片顺序、每个镜头的动画帧范围和相机），给拼预演视频和导入 UE 用。"""
import json
import math
import os
import random
import sys

import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

sys.path.insert(0, os.path.dirname(__file__))
from common import args

A = args()
SH = json.load(open(A["shots"], encoding="utf-8"))
FPS = SH["fps"]
sc = bpy.context.scene
rigs = [bpy.data.objects["p0_rig"], bpy.data.objects["p1_rig"]]
L = sc.frame_end
BONES = {"pelvis": "pelvis", "chest": "spine_05", "head": "head"}


def sample():
    """逐帧取两人骨骼世界坐标（先隐藏网格，只算骨架，快很多）。"""
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    for o in meshes:
        o.hide_viewport = True
    out = {k: {b: np.zeros((L + 1, 3)) for b in BONES} for k in range(2)}
    for f in range(1, L + 1):
        sc.frame_set(f)
        for k, r in enumerate(rigs):
            for b, bn in BONES.items():
                out[k][b][f] = np.array(r.matrix_world @ r.pose.bones[bn].matrix.translation)
    for o in meshes:
        o.hide_viewport = False
    for k in range(2):
        for b in BONES:
            out[k][b][0] = out[k][b][1]
    return out


def smooth(x, s=4.0):
    if s <= 0:
        return x
    r = int(3 * s)
    w = np.exp(-0.5 * (np.arange(-r, r + 1) / s) ** 2)
    w /= w.sum()
    pad = np.concatenate([np.repeat(x[:1], r, 0), x, np.repeat(x[-1:], r, 0)])
    return np.stack([np.convolve(pad[:, i], w, "valid") for i in range(x.shape[1])], 1)


def unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v


POS = sample()
CAM0 = np.array(bpy.data.objects["orig_cam"].matrix_world.translation)


def target(name, f):
    if name == "mid":
        return (POS[0]["chest"][f] + POS[1]["chest"][f]) / 2
    k = int(name[1])
    if name.endswith("head"):
        return POS[k]["head"][f] + np.array([0, 0, 0.08])
    return POS[k]["chest"][f]


def frame_axes(frames):
    """这个镜头的两人连线方向 Ld（p0→p1，水平）和原机位一侧的法线 n。"""
    d = np.mean([POS[1]["pelvis"][f] - POS[0]["pelvis"][f] for f in frames], 0)
    Ld = unit(np.array([d[0], d[1], 0.0]))
    n = np.array([-Ld[1], Ld[0], 0.0])
    mid = np.mean([target("mid", f) for f in frames], 0)
    if np.dot(n, CAM0 - mid) < 0:
        n = -n
    return Ld, n


def look(pos, tgt):                                  # 相机朝向：-Z 对准目标，Y 朝上
    return Vector(tgt - pos).to_track_quat("-Z", "Y")


def lerp(a, b, u):
    return a + (b - a) * u


def shot_frames(s):
    """动画帧列表（Blender 帧号，1 起）。定格镜头：第 1 帧重复 hold 秒。"""
    if s.get("hold"):
        return [1] * int(round(s["hold"] * FPS))
    f0, f1 = int(round(s["t0"] * FPS)) + 1, min(L, int(round(s["t1"] * FPS)))
    return list(range(f0, f1 + 1))


IMPACTS = []
if A.get("impacts") and os.path.exists(A["impacts"]):
    for p in json.load(open(A["impacts"], encoding="utf-8")).get("persons", []):
        IMPACTS += [e["frame"] + 1 for e in p["impacts"]]


CHAR = [o for o in bpy.data.objects if o.type == "MESH" and o.name[:3] in ("p0_", "p1_")]


def _rc(dg, o, d, dist):
    n = float(np.linalg.norm(d))
    if n < 1e-6:
        return None
    hit, loc, *_ = sc.ray_cast(dg, Vector(o), Vector(d / n), distance=dist)
    return (Vector(loc) - Vector(o)).length if hit else None


def visible(cam, tg, fr, step=4):
    """外部场景里这个机位能不能用：每隔 step 帧，①相机到两人头/胸/骨盆 6 个点都无遮挡；②镜头前 1.5 米内
    画面范围（3×3 条射线）没有东西。返回 (是否合格, 视线最短可用比例)。只看场景，不看两个角色。"""
    for o in CHAR:
        o.hide_viewport = True
    dg = bpy.context.evaluated_depsgraph_get()
    ok, ratio = True, 1.0
    for i in range(0, len(cam), step):
        c, t, f = cam[i], tg[i], fr[i]
        for k in range(2):
            for bn in ("head", "chest", "pelvis"):
                p = POS[k][bn][f]
                d = c - p
                dist = float(np.linalg.norm(d))
                h = _rc(dg, p, d, dist)
                if h is not None:
                    ok = False
                    ratio = min(ratio, max(0.0, h - 0.25) / dist)
        fwd = unit(t - c)
        right = unit(np.cross(fwd, [0, 0, 1.0]))
        up = np.cross(right, fwd)
        for a in (-0.3, 0.0, 0.3):
            for b in (-0.17, 0.0, 0.17):
                if _rc(dg, c, fwd + right * a + up * b, 1.5) is not None:
                    ok = False
    for o in CHAR:
        o.hide_viewport = False
    return ok, ratio


def poses(s):
    """逐帧 (位置, 旋转四元数)。"""
    fr = shot_frames(s)
    n_ = len(fr)
    Ld, n = frame_axes(sorted(set(fr)))
    kind = s.get("kind", "orbit")
    if kind == "ots":
        a, b = int(s["frm"][1]), int(s["to"][1])
        cam = np.array([POS[a]["head"][f] - unit(np.r_[(POS[b]["head"][f] - POS[a]["head"][f])[:2], 0]) * s.get("back", 1.1)
                        + n * s.get("shoulder", 0.6) + np.array([0, 0, s.get("up", 0.2)]) for f in fr])
        tg = np.array([(POS[b]["chest"][f] + POS[b]["head"][f]) / 2 for f in fr])
        cam, tg = smooth(cam, 5), smooth(tg, 3)
    else:
        tg = np.array([target(s["target"], f) for f in fr])
        tg = smooth(tg, 4) if s.get("track") else np.repeat(tg.mean(0, keepdims=True), n_, 0)

        def orbit(off):
            out = []
            for i in range(n_):
                if s.get("snap"):                     # 急推：前 snap 帧内迅速推到位，之后保持
                    u = min(1.0, i / s["snap"])
                    u = 1 - (1 - u) ** 3
                else:
                    u = i / max(1, n_ - 1)
                    u = u * u * (3 - 2 * u)          # 缓入缓出
                az = math.radians(lerp(s["az"], s.get("az1", s["az"]), u) + off)
                d, h = lerp(s["dist"], s.get("dist1", s["dist"]), u), lerp(s["h"], s.get("h1", s["h"]), u)
                o = math.cos(az) * n + math.sin(az) * Ld
                out.append(np.array([tg[i][0] + o[0] * d, tg[i][1] + o[1] * d, h]))
            return np.array(out)
        cam = orbit(0.0)
        if A.get("avoid"):                            # 外部场景：按改动从小到大试 换角度 / 升高 / 拉近
            base = s["az"]
            sgn = (1, -1) if base >= 0 else (-1, 1)
            offs = [0.0] + [g * k for k in (15, 30, 45, 60, 75) for g in sgn]
            cands = []
            for off in offs:
                if abs(base + off) > 85 or abs(s.get("az1", base) + off) > 85:
                    continue
                for dh in (0.0, 0.6, 1.2):
                    for df in (1.0, 0.75, 0.55):
                        cands.append((abs(off) / 15 + dh / 0.6 * 1.5 + (1 - df) / 0.25 * 1.2, off, dh, df))
            cands.sort()
            best = None
            for cost, off, dh, df in cands:
                c = orbit(off)
                c = tg + (c - tg) * df
                c[:, 2] += dh
                ok, r = visible(c, tg, fr)
                if ok:
                    best = (off, dh, df, c, 1.0)
                    break
                if best is None or r > best[4]:
                    best = (off, dh, df, c, r)
            off, dh, df, cam, r = best
            k = df if r >= 1.0 else df * max(r - 0.05, 0.15)
            if r < 1.0:                               # 都不合格：取视线最好的，再拉到遮挡物前面
                cam = tg + (cam - tg) * max(r - 0.05, 0.15)
            if k < 0.999:
                s["_lens"] = max(14.0, s["lens"] * k)
            s["_avoid"] = {"az_offset": off, "raise": dh, "dist_k": round(k, 2), "ok": r >= 1.0,
                           "lens": round(s.get("_lens", s["lens"]), 1)}
    if A.get("avoid") and kind == "ots":
        ok, r = visible(cam, tg, fr)
        if not ok:                                    # 过肩：往肩后上方抬一点再拉近
            for dh, df in ((0.3, 1.0), (0.3, 0.8), (0.6, 0.7)):
                c = tg + (cam - tg) * df
                c[:, 2] += dh
                ok2, r2 = visible(c, tg, fr)
                if ok2:
                    cam, ok, r = c, True, 1.0
                    if df < 1:
                        s["_lens"] = max(14.0, s["lens"] * df)
                    break
        s["_avoid"] = {"ok": ok, "lens": round(s.get("_lens", s["lens"]), 1)}
    rng = random.Random(s["id"])
    out = []
    for i, f in enumerate(fr):
        q = look(cam[i], tg[i])
        rx = ry = 0.0
        if s.get("shake"):
            for fi in IMPACTS:
                if 0 <= f - fi < 8:
                    r2 = random.Random(fi)
                    amp = 0.9 if s["shake"] is True else float(s["shake"])     # true = 0.9°，数字 = 指定幅度
                    a = amp * math.exp(-(f - fi) / (0.12 * FPS))
                    rx += math.radians(a * r2.uniform(-1, 1))
                    ry += math.radians(a * r2.uniform(-1, 1))
        if s.get("handheld"):
            t = i / FPS
            rx += math.radians(0.35 * math.sin(2.1 * t + 1) + 0.15 * math.sin(5.3 * t))
            ry += math.radians(0.35 * math.sin(1.7 * t) + 0.15 * math.sin(4.1 * t + 2))
        q = q @ Euler((rx, ry, 0)).to_quaternion()
        out.append((Vector(cam[i]), q))
    return fr, out


# ---- 建相机、打关键帧、标记、剪辑表 ----
for m in list(sc.timeline_markers):
    sc.timeline_markers.remove(m)
edl, film = [], 0
for s in SH["shots"]:
    fr, ps = poses(s)
    cd = bpy.data.cameras.new(f"CAM_{s['id']}")
    cd.lens, cd.sensor_width = s.get("_lens", s["lens"]), 36
    cam = bpy.data.objects.new(f"CAM_{s['id']}", cd)
    sc.collection.objects.link(cam)
    cam.rotation_mode = "QUATERNION"
    keyf = [f - len(fr) for f in range(1, len(fr) + 1)] if s.get("hold") else fr   # 定格放在 -N..0 帧
    for kf, (p, q) in zip(keyf, ps):
        cam.location, cam.rotation_quaternion = p, q
        cam.keyframe_insert("location", frame=kf)
        cam.keyframe_insert("rotation_quaternion", frame=kf)
    if not s["id"][-1] in "bc":                      # 主线（重复剪辑只取第一个角度）打相机切换标记
        m = sc.timeline_markers.new(s["id"], frame=keyf[0])
        m.camera = cam
    edl.append({"id": s["id"], "desc": s["desc"], "camera": cam.name, "lens": round(s.get("_lens", s["lens"]), 2), "avoid": s.get("_avoid"), "film_start": film,
                "frames": len(fr), "anim_frames": [fr[0], fr[-1]], "hold": bool(s.get("hold")), "key_frames": [keyf[0], keyf[-1]]})
    film += len(fr)
    s["_ps"], s["_fr"] = ps, fr
sc.frame_start = -int(round(SH["shots"][0].get("hold", 0) * FPS)) + 1 if SH["shots"][0].get("hold") else 1
json.dump({"fps": FPS, "film_frames": film, "shots": edl}, open(os.path.join(os.path.dirname(A["shots"]), "edl.json"), "w",
          encoding="utf-8"), ensure_ascii=False, indent=1)
bpy.ops.wm.save_as_mainfile(filepath=A["out_blend"])
print("@@ cameras", len(edl), "film frames", film, "saved", A["out_blend"])

# ---- 按剪辑顺序渲染 ----
if A.get("render_dir"):
    W, H = (int(x) for x in A.get("res", "960x540").split("x"))
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = W, H, 100
    sc.display.shading.light = "STUDIO"
    sc.display.shading.show_shadows = True
    sc.display.shading.show_cavity = True
    sc.render.use_stamp, sc.render.use_stamp_note = True, True
    for k in ("date", "time", "render_time", "frame", "memory", "camera", "lens", "scene", "filename", "hostname"):
        setattr(sc.render, f"use_stamp_{k}", False)
    for m in sc.timeline_markers:                    # 渲染时 Blender 会按标记切相机，覆盖我们指定的相机（已存盘，不影响 .blend）
        m.camera = None
    rc = bpy.data.objects.new("RENDER_CAM", bpy.data.cameras.new("RENDER_CAM"))
    sc.collection.objects.link(rc)
    rc.rotation_mode, sc.camera = "QUATERNION", rc
    rc.data.sensor_width = 36
    os.makedirs(A["render_dir"], exist_ok=True)
    i = 0
    for s in SH["shots"]:
        rc.data.lens = s.get("_lens", s["lens"])
        sc.render.stamp_note_text = f"{s['id']}   anim {s['_fr'][0]}-{s['_fr'][-1]}   lens {rc.data.lens:.0f}mm"
        for f, (p, q) in zip(s["_fr"], s["_ps"]):
            sc.frame_set(f)
            sc.camera = rc                           # 时间轴上的相机切换标记会在换帧时改 scene.camera
            rc.location, rc.rotation_quaternion = p, q
            sc.render.filepath = os.path.join(A["render_dir"], f"f_{i:05d}.png")
            bpy.ops.render.render(write_still=True)
            i += 1
    print("@@ rendered", i)
