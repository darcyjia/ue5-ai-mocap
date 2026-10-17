"""让配乐的强拍对上动作的重音：在原曲里找一个起点，使每个“重音时刻”（比如闪身步的急停）落在强拍（每 N 拍一次）上，切出来当成片音轨。
.venv-tools/Scripts/python.exe beat_fit.py a.flac [b.flac ...] --hits 1.3,2.87,... --secs 12.07 [--every 2] [--delay 0.1] [--cut out_dir]
--every：重音间隔几拍（闪身步约 1.41 s，85 BPM 下是 2 拍）；--delay：速度峰值到“定住”的延迟。"""
import argparse
import json
import subprocess
from pathlib import Path

import librosa
import numpy as np

FF = "C:/FFmpeg/bin/ffmpeg.exe"


def fit(path, hits, secs, every, delay):
    y, sr = librosa.load(path, sr=22050)
    dur = len(y) / sr
    _, bt = librosa.beat.beat_track(y=y, sr=sr, units="time", tightness=300)
    low = librosa.onset.onset_strength(y=y, sr=sr, fmax=200)
    fr = librosa.time_to_frames(bt, sr=sr)
    phase = int(np.argmax([low[fr[k::every]].mean() for k in range(every)]))
    strong = bt[phase::every]
    rms = librosa.amplitude_to_db(librosa.feature.rms(y=y, hop_length=512)[0])
    t_rms = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=512)
    h = np.array(hits) + delay
    best = None
    for sb in strong:
        s = sb - h[0]
        if s < 0 or s + secs > dur - 0.05:
            continue
        err = np.array([np.min(np.abs(strong - (hk + s))) for hk in h])
        m = (t_rms >= s) & (t_rms < s + secs)
        loud = float(np.convolve(rms[m], np.ones(21) / 21, "valid").min())
        score = err.mean() - 0.01 * min(loud + 25, 0)      # 有掉坑（< -25 dB）的窗口扣分
        if best is None or score < best[0]:
            best = (score, s, err, loud)
    period = float(np.median(np.diff(strong)))
    return {"file": Path(path).name, "bpm": round(60 / float(np.median(np.diff(bt))), 2), "strong_period": round(period, 4),
            "hit_period": round(float(np.polyfit(np.arange(len(h)), h, 1)[0]), 4),
            "start": round(best[1], 3) if best else None, "err_ms": [int(round(e * 1000)) for e in best[2]] if best else None,
            "err_mean_ms": int(round(best[2].mean() * 1000)) if best else None, "win_min_db": round(best[3], 1) if best else None}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--hits", required=True)
    ap.add_argument("--secs", type=float, required=True)
    ap.add_argument("--every", type=int, default=2)
    ap.add_argument("--delay", type=float, default=0.1)
    ap.add_argument("--cut")
    a = ap.parse_args()
    hits = [float(x) for x in a.hits.split(",")]
    res = [fit(f, hits, a.secs, a.every, a.delay) for f in a.files]
    for r in res:
        print(json.dumps(r, ensure_ascii=False))
    if a.cut:
        r = min((r for r in res if r["start"] is not None), key=lambda r: r["err_mean_ms"])
        src = next(f for f in a.files if Path(f).name == r["file"])
        out = Path(a.cut) / "music_fit.wav"
        subprocess.run([FF, "-nostdin", "-y", "-v", "error", "-ss", f"{r['start']:.3f}", "-t", f"{a.secs:.3f}", "-i", src,
                        "-af", f"afade=t=in:d=0.02,afade=t=out:st={a.secs - 0.3:.3f}:d=0.3", "-ar", "48000", "-ac", "2", str(out)],
                       check=True, stdin=subprocess.DEVNULL)
        out.with_suffix(".json").write_text(json.dumps({**r, "src": str(Path(src).resolve()), "hits": hits, "secs": a.secs},
                                                       ensure_ascii=False, indent=1), encoding="utf-8")
        print("->", out, "from", r["file"])
