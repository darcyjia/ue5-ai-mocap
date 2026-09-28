"""阶段 qc：质量报告（qc/report.html + qc/metrics.json）。
- 追踪：身份数、覆盖率
- 脚部：着地脚在 3D 里的横向/深度速度 vs 画面实测、脚踝重投影误差、穿地/悬空（清理前后对比）
- 重定向：躯干/头部/手臂误差、两人间距比
超出阈值标红。"""
import html
import os

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ..kinematics import COCO_L_ANKLE, COCO_R_ANKLE, L_ANKLE, L_FOOT, PELVIS, R_ANKLE, R_FOOT, load_person, project
from ..handpose import STATE_CN
from ..util import file_sig, load_json, save_json

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False


def params(c, cfg):
    n = cfg["solve"]["num_people"]
    return {"in": [file_sig(c.clean / f"p{k}.npz") for k in range(n)], "ue": file_sig(c.ue / "result.json"),
            "hands": file_sig(c.hands / "hands.json"), "qc": cfg["qc"]}


def outputs(c, cfg):
    return [c.qc / "report.html", c.qc / "metrics.json"]


def foot_metrics(pos, vit, cam, fps):
    u, v, z, fx = project(pos, cam)
    right = np.array(cam["R"])[:, 0]
    fwd = -np.array(cam["R"])[:, 2]
    fwd[1] = 0
    fwd /= np.linalg.norm(fwd)
    lat2, lat3, dep3, rep = [], [], [], []
    for j3, j2, jf in ((L_ANKLE, COCO_L_ANKLE, L_FOOT), (R_ANKLE, COCO_R_ANKLE, R_FOOT)):
        h = pos[:, jf, 1]
        con = (h[1:] < 0.06) & (h[:-1] < 0.06) & (vit[1:, j2, 2] > 0.5) & (vit[:-1, j2, 2] > 0.5)
        d3 = np.diff(pos[:, j3], axis=0)
        lat3.append(np.abs(d3 @ right)[con] * fps * 100)
        dep3.append(np.abs(d3 @ fwd)[con] * fps * 100)
        lat2.append((np.abs(np.diff(vit[:, j2, 0])) * fps * z[1:, j3] / fx * 100)[con])
        err = np.hypot(u[:, j3] - vit[:, j2, 0], v[:, j3] - vit[:, j2, 1]) * z[:, j3] / fx * 100
        rep.append(err[1:][con])
    cat = lambda x: np.concatenate(x) if sum(len(a) for a in x) else np.array([np.nan])
    lat2, lat3, dep3, rep = map(cat, (lat2, lat3, dep3, rep))
    lowest = pos[:, [L_FOOT, R_FOOT], 1].min(1)
    return {"contact_frames": int(np.isfinite(lat3).sum()), "lat2d": float(np.nanmedian(lat2)),
            "lat3d": float(np.nanmedian(lat3)), "dep3d": float(np.nanmedian(dep3)), "reproj_cm": float(np.nanmedian(rep)),
            "penetration_pct": float((lowest < -0.03).mean() * 100),
            "floating_pct": float(((lowest > 0.15) & (pos[:, PELVIS, 1] > 0.6)).mean() * 100)}


def footprint(c, n, par, out):
    fig, axes = plt.subplots(2, n, figsize=(5.5 * n, 10), squeeze=False)
    for r, (sub, title) in enumerate(((c.solve, "清理前"), (c.clean, "清理后"))):
        for k in range(n):
            P, _, _, pos = load_person(sub / f"p{k}.npz", par)
            conf = P["static_conf"]
            ax = axes[r, k]
            for ank, ci, mk, nm in ((L_ANKLE, (0, 1), "o", "左脚"), (R_ANKLE, (2, 3), "s", "右脚")):
                con = conf[:, list(ci)].max(1) > 0.6
                ax.plot(pos[:, ank, 0] * 100, pos[:, ank, 2] * 100, "-", color="0.82", lw=0.6)
                ax.scatter(pos[con, ank, 0] * 100, pos[con, ank, 2] * 100, s=7, marker=mk, alpha=0.55, label=f"{nm}着地")
            ax.set_title(f"{title}  p{k}（俯视，着地帧）")
            ax.set_xlabel("左右 cm")
            ax.set_ylabel("深度（镜头方向）cm")
            ax.set_aspect("equal")
            ax.grid(alpha=0.3)
            ax.legend(fontsize=8)
    fig.suptitle("着地脚俯视轨迹：锁定成功时每次着地聚成一个点")
    plt.tight_layout()
    plt.savefig(out, dpi=85)
    plt.close(fig)


def check(rows, name, value, limit, mode="max", warn_only=False):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        rows.append((name, "—", limit, "warn"))
        return
    bad = value > limit if mode == "max" else value < limit
    rows.append((name, round(value, 3) if isinstance(value, float) else value, limit,
                 ("warn" if warn_only else "fail") if bad else "ok"))


def run(c, cfg, args):
    q, n = cfg["qc"], cfg["solve"]["num_people"]
    cam = load_json(c.clean / "camera.json")
    par = np.load(c.clean / "smplx_common.npz")["parents"]
    track, solve_i, clean_i, ue_r = (load_json(c.solve / "track.json", {}), load_json(c.solve / "solve.json", {}),
                                     load_json(c.clean / "cleanup.json", {}), load_json(c.ue / "result.json"))
    M = {"clip": c.name, "track": track, "solve": solve_i, "cleanup": clean_i, "ue": ue_r, "persons": []}
    rows = []
    check(rows, "追踪到的身份总数（多于人数说明有断轨/串号）", len(track.get("all_tracks", [])), n, "max", warn_only=True)
    for pp in track.get("people", []):
        check(rows, f"p{pp['p']} 追踪覆盖率", pp["coverage"], q["min_track_coverage"], "min")
    for k in range(n):
        vit = np.load(c.solve / f"vit_p{k}.npy")
        rec = {}
        for tag, sub in (("before", c.solve), ("after", c.clean)):
            _, _, _, pos = load_person(sub / f"p{k}.npz", par)
            rec[tag] = foot_metrics(pos, vit, cam, cam["fps"])
        M["persons"].append(rec)
        a, b = rec["after"], rec["before"]
        check(rows, f"p{k} 着地脚深度速度 cm/s（清理前 {b['dep3d']:.1f}）", a["dep3d"], q["max_contact_depth_speed"])
        rows.append((f"p{k} 着地脚横向速度 3D / 画面实测 cm/s", f"{a['lat3d']:.1f} / {a['lat2d']:.1f}", "—", "info"))
        check(rows, f"p{k} 脚踝重投影误差 cm", a["reproj_cm"], q["max_reproj_cm"])
        check(rows, f"p{k} 穿地帧 %", a["penetration_pct"], q["max_penetration_pct"])
    if ue_r:
        for r in ue_r["persons"]:
            check(rows, f"p{r['p']} 重定向 躯干前倾误差均值 °", abs(r["torso_err_mean"]), q["max_torso_err"])
            check(rows, f"p{r['p']} 重定向 头部俯仰误差均值 °", abs(r["head_err_mean"]), q["max_head_err"])
            check(rows, f"p{r['p']} 重定向 手臂方向误差均值 °", r["arm_err_mean"], q["max_arm_err"])
        if ue_r.get("spacing_ratio_median"):
            dev = abs(ue_r["spacing_ratio_median"] / ue_r["spacing_ratio_expected"] - 1) * 100
            check(rows, f"两人间距比 {ue_r['spacing_ratio_median']}（期望 {ue_r['spacing_ratio_expected']}）偏差 %", dev, 8.0,
                  warn_only=True)
    hands = load_json(c.hands / "hands.json", {}) or {}
    for hp in hands.get("persons", []):
        for side, hr in hp["hands"].items():
            share = " ".join(f"{STATE_CN[s]}{v:.0%}" for s, v in hr["share"].items())
            check(rows, f"p{hp['person']} {'左' if side == 'L' else '右'}手 手型识别率（{share}）", hr["detect_rate"],
                  q["min_hand_detect"], "min", warn_only=True)
    M["hands"] = hands
    footprint(c, n, par, c.qc / "footprint.png")
    M["checks"] = [dict(zip(("name", "value", "limit", "status"), r)) for r in rows]
    M["status"] = "fail" if any(r[3] == "fail" for r in rows) else ("warn" if any(r[3] == "warn" for r in rows) else "ok")
    save_json(c.qc / "metrics.json", M)
    write_html(c, M, rows, ue_r)
    bad = [r for r in rows if r[3] in ("fail", "warn")]
    for r in bad:
        print(f"  [{r[3]}] {r[0]} = {r[1]}（阈值 {r[2]}）")
    return {"status": M["status"], "problems": len(bad)}


def write_html(c, M, rows, ue_r):
    color = {"ok": "#1f9d55", "warn": "#d97706", "fail": "#dc2626", "info": "#6b7280"}
    rel = lambda p: os.path.relpath(p, c.qc).replace("\\", "/")
    tr = "".join(f"<tr><td>{html.escape(str(n))}</td><td>{html.escape(str(v))}</td><td>{html.escape(str(l))}</td>"
                 f"<td style='color:{color[s]};font-weight:600'>{s.upper()}</td></tr>" for n, v, l, s in rows)
    vids = ""
    if (c.blender / "triptych.mp4").exists():
        vids += f"<h2>三联画：原视频 | Blender 原机位 | 斜上方 3/4</h2><video src='{rel(c.blender / 'triptych.mp4')}' controls width='100%'></video>"
    for k in range(len(M["persons"])):
        p = c.solve / f"p{k}_incam.mp4"
        if p.exists():
            vids += f"<h3>p{k} GVHMR 叠合</h3><video src='{rel(p)}' controls width='49%'></video>"
    seq = f"<p>UE 关卡序列：<code>{html.escape(ue_r['sequence'])}</code>，水平缩放 {ue_r['horizontal_scale']}</p>" if ue_r else ""
    hands = ""
    if (c.hands / "timeline.png").exists():
        crops = "".join(f"<img src='{rel(c.hands / 'crops' / f)}' width='112' title='{html.escape(f)}'>"
                        for f in M["hands"].get("samples", []) if (c.hands / "crops" / f).exists())
        hands = (f"<h2>手型时间线</h2><p>不对可以写 input/hands.json 手动覆盖（插件：AI 动捕 → 手型修正…）</p>"
                 f"<img src='{rel(c.hands / 'timeline.png')}' width='100%'><h3>识别抽样（左上角数字为弯曲角）</h3>{crops}")
    s = M["solve"]
    doc = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8"><title>{html.escape(c.name)} 质检</title>
<style>body{{font-family:'Microsoft YaHei',sans-serif;max-width:1200px;margin:24px auto;padding:0 16px;color:#111}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #e5e7eb;padding:6px 8px;text-align:left;font-size:14px}}
.badge{{display:inline-block;padding:4px 12px;border-radius:12px;color:#fff;background:{color[M['status']]}}}</style></head><body>
<h1>{html.escape(c.name)} <span class="badge">{M['status'].upper()}</span></h1>
<p>相机高度 {s.get('camera_height_m', 0):.2f} m，焦距 {s.get('lens_mm', 0):.1f} mm，重力方向两人一致性 {s.get('rc2gv_person_agree_deg')}°，
两人骨盆间距 {s.get('pelvis_dist_m')}</p>{seq}
<table><tr><th>检查项</th><th>值</th><th>阈值</th><th>结果</th></tr>{tr}</table>
<h2>着地脚俯视轨迹</h2><img src="footprint.png" width="100%">{hands}{vids}
<h2>清理统计</h2><pre>{html.escape(str(M['cleanup']))}</pre></body></html>"""
    (c.qc / "report.html").write_text(doc, encoding="utf-8")
