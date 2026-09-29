import tomllib
from pathlib import Path

from .util import ROOT

DEFAULTS = {
    "paths": {},
    "generate": {"model": "seedance2.5", "resolution": "480p", "duration": 15, "max_credits": 1200, "retries": 0},
    "solve": {"num_people": 2, "f_mm": 0},
    "clean": {"contact_on": 0.6, "contact_off": 0.4, "foot_max_height": 0.10, "min_segment": 3,
              "merge_gap": 4, "merge_max_lift": 0.12, "ik_ramp": 3},
    "hands": {"enabled": True, "python": ".venv-tools/Scripts/python.exe", "model": "models/hand_landmarker.task",
              "fist": 110, "palm": 55, "gap_fill": 8, "fallback": "guard", "punch_elbow": 150, "punch_speed": 2.5,
              "vote": 7, "min_segment": 5, "blend": 5},
    "impact": {"enabled": True, "hf_gain": "auto", "hf_gain_max": 2.5, "hf_sigma": 3,
               "min_speed": {"fist": 1.8, "elbow": 2.0, "foot": 3.0, "knee": 2.0},
               "stop_frames": 6, "stop_ratio": 0.45, "contact_dist": 0.15, "merge_frames": 3,
               "ref_speed": 3.0, "amp_deg": {"head": 7.0, "chest": 4.0, "belly": 4.0, "arm": 10.0},
               "tau": 0.06, "duration": 0.3},
    "preview": {"enabled": True},
    "ue": {"content_root": "/Game/AIMocap", "retarget_dir": "/Game/AIMocap/_Retarget",
           "uniform_horizontal_scale": True},
    "person": [],
    "qc": {"min_track_coverage": 0.95, "max_contact_depth_speed": 10.0, "max_reproj_cm": 6.0,
           "max_penetration_pct": 5.0, "max_torso_err": 8.0, "max_head_err": 8.0, "max_arm_err": 5.0,
           "min_hand_detect": 0.6},
}


def _merge(a, b):
    out = dict(a)
    for k, v in b.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load(path=None):
    """config.toml，再叠加可选的 config.local.toml。"""
    cfg = DEFAULTS
    for p in ([Path(path)] if path else [ROOT / "config.toml", ROOT / "config.local.toml"]):
        if p.exists():
            cfg = _merge(cfg, tomllib.loads(p.read_text(encoding="utf-8")))
    n = cfg["solve"]["num_people"]
    if len(cfg["person"]) < n:
        raise SystemExit(f"config 里只配置了 {len(cfg['person'])} 个 [[person]]，但 num_people = {n}")
    return cfg
