"""Seedance 全能参考出片的音轨不一定从配乐第 0 秒开始（dance_01：从 2.57 s 开始，11.2 s 后又跳回去重复一段）。
找出视频音轨在原配乐里的位置，切出同样长度、节拍对齐的干净配乐当成片音轨。
.venv-tools/Scripts/python.exe align_audio.py <video.mp4> <原配乐.flac> <输出.wav> [--start-in-cut 秒]
--start-in-cut：上传给 Seedance 的那段在原配乐里的起点（music_beats.json 的 start_in_source），只用于报告。"""
import argparse
import json
import subprocess
from pathlib import Path

import librosa
import numpy as np

FF = "C:/FFmpeg/bin/ffmpeg.exe"
SR, H = 22050, 256


def load(p):
    raw = subprocess.run([FF, "-nostdin", "-v", "error", "-i", str(p), "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                         capture_output=True, check=True, stdin=subprocess.DEVNULL).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def mel(y):
    return librosa.power_to_db(librosa.feature.melspectrogram(y=y, sr=SR, hop_length=H, n_mels=64))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("source")
    ap.add_argument("out")
    ap.add_argument("--win", type=float, default=1.5)
    ap.add_argument("--step", type=float, default=0.75)
    a = ap.parse_args()
    fps = SR / H
    v, s = load(a.video), load(a.source)
    mv, ms = mel(v), mel(s)
    W = int(a.win * fps)
    rows = []
    for t0 in np.arange(0, len(v) / SR - a.win, a.step):
        i = int(t0 * fps)
        y = mv[:, i:i + W].ravel()
        cs = [np.corrcoef(ms[:, j:j + W].ravel(), y)[0, 1] for j in range(0, ms.shape[1] - W)]
        j = int(np.argmax(cs))
        rows.append({"video_t": round(float(t0), 2), "source_t": round(j / fps, 3), "sim": round(float(cs[j]), 3)})
    shifts = np.array([r["source_t"] - r["video_t"] for r in rows])
    # 主偏移：出现最多的那一档（±0.05 s）
    main_shift = float(np.median(shifts[np.abs(shifts - np.median(shifts)) < 0.05])) if len(shifts) else 0.0
    ok = [r for r, sh in zip(rows, shifts) if abs(sh - main_shift) < 0.05]
    jumps = [r for r, sh in zip(rows, shifts) if abs(sh - main_shift) >= 0.05]
    dur = len(v) / SR
    if main_shift + dur > len(s) / SR:
        print(f"!! 原配乐不够长：需要到 {main_shift + dur:.2f}s，只有 {len(s) / SR:.2f}s，尾部会缺")
    subprocess.run([FF, "-nostdin", "-y", "-v", "error", "-ss", f"{main_shift:.3f}", "-t", f"{dur:.3f}", "-i", a.source,
                    "-af", f"afade=t=out:st={dur - 0.3:.3f}:d=0.3", "-ar", "48000", "-ac", "2", a.out],
                   check=True, stdin=subprocess.DEVNULL)
    beat = 60 / librosa.beat.beat_track(y=s, sr=SR, start_bpm=128)[0].item()
    rep = {"video": a.video, "source": a.source, "out": a.out, "video_dur": round(dur, 3),
           "shift_s": round(main_shift, 3), "matched_windows": len(ok), "total_windows": len(rows),
           "jumps": [{**r, "shift_beats": round((r["source_t"] - r["video_t"] - main_shift) / beat, 2)} for r in jumps]}
    Path(a.out).with_suffix(".json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in rep.items() if k != "jumps"}, ensure_ascii=False))
    for r in rep["jumps"]:
        print("  跳段", r)


if __name__ == "__main__":
    main()
