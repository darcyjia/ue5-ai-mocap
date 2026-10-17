"""音乐节拍检查（纯 numpy，不依赖 librosa）：估 BPM、第一拍相位、节拍强度。
python beat_check.py a.flac [b.flac ...] [--bpm 128]   需要 ffmpeg 在 PATH 或 C:/FFmpeg/bin。"""
import json
import subprocess
import sys

import numpy as np

FF = "C:/FFmpeg/bin/ffmpeg.exe"
SR = 22050
HOP = 256


def load(path):
    raw = subprocess.run([FF, "-nostdin", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                         capture_output=True, check=True, stdin=subprocess.DEVNULL).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def onset_env(x):
    n = 1024
    win = np.hanning(n)
    frames = np.lib.stride_tricks.sliding_window_view(np.pad(x, (n // 2, n // 2)), n)[::HOP] * win
    mag = np.log1p(100 * np.abs(np.fft.rfft(frames, axis=1)))
    flux = np.maximum(np.diff(mag, axis=0), 0).sum(1)
    flux = np.concatenate([[0], flux])
    flux -= np.convolve(flux, np.ones(16) / 16, "same")            # 去掉慢变化
    return np.maximum(flux, 0)


def env_low(x):
    """150 Hz 以下能量的正向变化（底鼓）。"""
    n = 2048
    frames = np.lib.stride_tricks.sliding_window_view(np.pad(x, (n // 2, n // 2)), n)[::HOP] * np.hanning(n)
    spec = np.abs(np.fft.rfft(frames, axis=1))[:, :int(150 * n / SR) + 1]
    e = np.log1p(100 * spec.sum(1))
    return np.maximum(np.concatenate([[0], np.diff(e)]), 0)


def analyze(path, hint=None):
    x = load(path)
    env = onset_env(x)
    fps = SR / HOP
    ac = np.correlate(env, env, "full")[len(env) - 1:] / np.arange(len(env), 0, -1)   # 按重叠长度归一
    bpms = np.arange(70, 200, 0.25)
    lags = 60 * fps / bpms
    score = np.interp(lags, np.arange(len(ac)), ac)
    if hint:                                                       # 只在提示 BPM 的 ±10% 和倍/半速里找
        score = score * (np.abs(bpms / hint - np.round(bpms / hint * 2) / 2) < 0.05)
    bpm = float(bpms[np.argmax(score)])
    period = 60 * fps / bpm
    # 相位：对齐节拍网格时 onset 能量总和最大
    t = np.arange(len(env))
    best = max(np.arange(0, period, 0.25), key=lambda ph: np.interp(np.arange(ph, len(env), period), t, env).sum())
    grid = np.interp(np.arange(best, len(env), period), t, env)
    off = np.interp(np.arange(best + period / 2, len(env), period), t, env)
    k = SR // 4                                                    # 每 0.25 s 一格的响度
    rms = np.sqrt((x[:len(x) // k * k] ** 2).reshape(-1, k).mean(1))
    db = 20 * np.log10(rms + 1e-9)
    low = env_low(x)                                               # 低频（底鼓）起音间隔 → 节拍稳不稳
    pk = [i for i in range(1, len(low) - 1) if low[i] > low[i - 1] and low[i] >= low[i + 1] and low[i] > 0.3 * low.max()]
    ioi = np.diff(pk) / fps
    return {"file": path, "dur": round(len(x) / SR, 2), "bpm": round(bpm, 2), "first_beat_s": round(best / fps, 3),
            "beat_strength": round(float(grid.mean() / (off.mean() + 1e-9)), 2),
            "kick_bpm_median": round(float(60 / np.median(ioi)), 1) if len(ioi) else None,
            "kick_count": len(pk),
            "db_per_0.25s": [int(round(v)) for v in db]}


if __name__ == "__main__":
    args = sys.argv[1:]
    hint = None
    if "--bpm" in args:
        i = args.index("--bpm")
        hint = float(args[i + 1])
        del args[i:i + 2]
    for p in args:
        print(json.dumps(analyze(p, hint), ensure_ascii=False))
