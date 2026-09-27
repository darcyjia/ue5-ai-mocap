"""SMPL-X 动作 -> UE 友好的 FBX（每人一个）：Z 朝上、厘米、UE 骨骼命名、root 骨在地面原点。
blender -b --factory-startup --python export_fbx.py -- --npz-dir D --out-dir O"""
import glob
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix

sys.path.insert(0, os.path.dirname(__file__))
from common import UE, args

A = args()
D, OUT = A["npz_dir"], A["out_dir"]
os.makedirs(OUT, exist_ok=True)
SCALE = 100.0
C = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float)      # Y 朝上 -> Z 朝上
com = np.load(os.path.join(D, "smplx_common.npz"))
faces, W, PAR = com["faces"], com["weights"], com["parents"]


def q2m(q):
    w, x, y, z = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                     [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                     [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])


for f in sorted(glob.glob(os.path.join(D, "p*.npz"))):
    name = os.path.splitext(os.path.basename(f))[0]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.unit_settings.system = "METRIC"
    sc.unit_settings.scale_length = 0.01
    P = np.load(f)
    rv = (P["rest_verts"] @ C.T) * SCALE
    rj = (P["rest_joints"] @ C.T) * SCALE
    lift = np.array([0, 0, -rv[:, 2].min()])      # SMPL-X 静止姿态原点在腰部：抬到脚底 z=0，否则 UE 按负骨盆高度缩放
    rv, rj = rv + lift, rj + lift
    Q, T, L = P["quat"], P["transl"], P["quat"].shape[0]
    ad = bpy.data.armatures.new("Armature")
    arm = bpy.data.objects.new("Armature", ad)    # 必须叫 Armature，否则 UE 会多出一层根骨骼
    sc.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    root = ad.edit_bones.new("root")
    root.head, root.tail, root.roll = (0, 0, 0), (0, 10, 0), 0
    ebs = []
    for i, n in enumerate(UE):
        eb = ad.edit_bones.new(n)
        eb.head = rj[i].tolist()
        eb.tail = (rj[i] + np.array([0, 5.0, 0])).tolist()
        eb.roll = 0
        ebs.append(eb)
    for i, p in enumerate(PAR):
        ebs[i].parent = ebs[p] if p >= 0 else root
    bpy.ops.object.mode_set(mode="OBJECT")
    me = bpy.data.meshes.new(name)
    me.from_pydata(rv.tolist(), [], faces.tolist())
    me.update()
    body = bpy.data.objects.new(name, me)
    sc.collection.objects.link(body)
    body.parent = arm
    for j, n in enumerate(UE):
        vg = body.vertex_groups.new(name=n)
        for v in np.nonzero(W[:, j] > 1e-4)[0]:
            vg.add([int(v)], float(W[v, j]), "REPLACE")
    body.modifiers.new("Armature", "ARMATURE").object = arm
    act = bpy.data.actions.new(f"A_{name}")
    arm.animation_data_create()
    arm.animation_data.action = act
    pb = arm.pose.bones
    for b in pb:
        b.rotation_mode = "QUATERNION"
    prev = {}
    for t in range(L):
        pb["pelvis"].location = (C @ T[t] * SCALE - lift).tolist()
        pb["pelvis"].keyframe_insert("location", frame=t + 1)
        for i in range(22):
            q = Matrix((C @ q2m(Q[t, i]) @ C.T).tolist()).to_quaternion()
            if i in prev and q.dot(prev[i]) < 0:
                q.negate()
            prev[i] = q.copy()
            pb[UE[i]].rotation_quaternion = q
            pb[UE[i]].keyframe_insert("rotation_quaternion", frame=t + 1)
    sc.render.fps = int(P["fps"])
    sc.frame_start, sc.frame_end = 1, L
    for o in (arm, body):
        o.select_set(True)
    out = os.path.join(OUT, f"{name}.fbx")
    bpy.ops.export_scene.fbx(filepath=out, use_selection=True, object_types={"ARMATURE", "MESH"},
                             add_leaf_bones=False, bake_anim=True, bake_anim_use_all_actions=False,
                             bake_anim_use_nla_strips=False, bake_anim_simplify_factor=0.0,
                             apply_unit_scale=True, apply_scale_options="FBX_SCALE_NONE",
                             primary_bone_axis="Y", secondary_bone_axis="X", armature_nodetype="NULL",
                             axis_forward="-Z", axis_up="Y")
    print(f"@@ exported {out} frames={L} pelvis_rest={rj[0][2]:.1f}cm")
