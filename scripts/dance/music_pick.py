"""从长一点的配乐里挑一段从小节头开始、没有静音的 N 秒，切出来并写节拍表。
.venv-tools/Scripts/python.exe music_pick.py a.flac [b.flac ...] --bpm 128 --secs 15 [--cut out_dir]
输出每个文件：实测 BPM、节拍间隔抖动、强拍相位、最佳起点；--cut 时写 <名>_cut.wav 和 <名>_beats.json。"""
import argparse
import json
import subprocess
from pathlib import Path

import librosa
import numpy as np

FF = "C:/FFmpeg/bin/ffmpeg.exe"


def analyze(path, bpm, secs):
    y, sr = librosa.load(path, sr=22050, mono=True)
    dur = len(y) / sr
    oenv = librosa.onset.onset_strength(y=y, sr=sr)
    tempo, beats = librosa.beat.beat_track(onset_envelope=oenv, sr=sr, start_bpm=bpm, tightness=300, units="frames")
    bt = librosa.frames_to_time(beats, sr=sr)
    ibi = np.diff(bt)
    # 强拍：低频起音最强的那一拍相位（底鼓 + 镲片通常落在小节第一拍）
    low = librosa.onset.onset_strength(y=y, sr=sr, fmax=200)
    strength = low[beats]
    phase = int(np.argmax([strength[k::4].mean() for k in range(4)]))
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    db = librosa.amplitude_to_db(rms, ref=1.0)
    t_rms = librosa.frames_to_time(np.arange(len(db)), sr=sr, hop_length=512)
    best = None
    for i in range(phase, len(bt), 4):
        s = bt[i]
        if s + secs > dur - 0.05:
            break
        m = (t_rms >= s) & (t_rms < s + secs)
        seg = db[m]
        # 0.5 s 平滑后的最低响度：不能有掉坑；同时偏好整体响一点
        sm = np.convolve(seg, np.ones(21) / 21, "valid")
        score = sm.min() + 0.5 * seg.mean()
        if best is None or score > best[0]:
            best = (score, s, float(sm.min()), float(seg.mean()))
    return {"file": Path(path).name, "dur": round(dur, 2), "tempo": round(float(np.atleast_1d(tempo)[0]), 2),
            "beat_bpm_median": round(60 / float(np.median(ibi)), 2), "ibi_jitter_ms": round(float(ibi.std() * 1000), 1),
            "n_beats": len(bt), "downbeat_phase": phase,
            "best_start": round(best[1], 3) if best else None,
            "win_min_db": round(best[2], 1) if best else None, "win_mean_db": round(best[3], 1) if best else None,
            "_beats": bt.tolist(), "_downbeats": bt[phase::4].tolist()}


def cut(path, info, secs, out_dir):
    s = info["best_start"]
    out = Path(out_dir) / (Path(path).stem + "_cut.wav")
    subprocess.run([FF, "-nostdin", "-y", "-v", "error", "-ss", f"{s:.3f}", "-t", f"{secs:.3f}", "-i", path,
                    "-af", f"afade=t=in:d=0.01,afade=t=out:st={secs - 0.25:.3f}:d=0.25", "-ar", "48000", "-ac", "2", str(out)],
                   check=True, stdin=subprocess.DEVNULL)
    beats = [round(b - s, 4) for b in info["_beats"] if s - 1e-3 <= b < s + secs]
    downs = [round(b - s, 4) for b in info["_downbeats"] if s - 1e-3 <= b < s + secs]
    meta = {"source": Path(path).name, "start_in_source": s, "secs": secs, "bpm": info["beat_bpm_median"],
            "beats": beats, "downbeats": downs}
    out.with_name(Path(path).stem + "_beats.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--bpm", type=float, default=128)
    ap.add_argument("--secs", type=float, default=15)
    ap.add_argument("--cut")
    a = ap.parse_args()
    for f in a.files:
        info = analyze(f, a.bpm, a.secs)
        print(json.dumps({k: v for k, v in info.items() if not k.startswith("_")}, ensure_ascii=False))
        if a.cut and info["best_start"] is not None:
            print("  ->", cut(f, info, a.secs, a.cut))
