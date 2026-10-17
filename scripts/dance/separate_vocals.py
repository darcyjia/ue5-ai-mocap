"""人声分离（Demucs htdemucs，CPU 即可）：配乐 -> 人声 / 伴奏，给口型用。
.venv-sep/Scripts/python.exe separate_vocals.py <配乐.wav> <人声.wav> [--accomp 伴奏.wav]
第一次运行会下载模型（约 80 MB）到 torch hub 缓存。"""
import argparse
import subprocess

import numpy as np
import soundfile as sf
import torch
from demucs.apply import apply_model
from demucs.pretrained import get_model

FF = "C:/FFmpeg/bin/ffmpeg.exe"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--accomp")
    ap.add_argument("--model", default="htdemucs")
    a = ap.parse_args()
    m = get_model(a.model)
    m.eval()
    sr = m.samplerate
    raw = subprocess.run([FF, "-nostdin", "-v", "error", "-i", a.inp, "-ac", "2", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, check=True, stdin=subprocess.DEVNULL).stdout
    x = torch.from_numpy(np.frombuffer(raw, np.float32).reshape(-1, 2).T.copy())
    ref = x.mean(0)
    x = (x - ref.mean()) / (ref.std() + 1e-8)
    with torch.no_grad():
        s = apply_model(m, x[None], device="cpu", shifts=1, split=True, overlap=0.25, progress=False)[0]
    s = s * (ref.std() + 1e-8) + ref.mean()
    names = list(m.sources)
    voc = s[names.index("vocals")]
    sf.write(a.out, voc.T.numpy(), sr)
    if a.accomp:
        sf.write(a.accomp, (s.sum(0) - voc).T.numpy(), sr)
    e = {n: round(float(10 * np.log10((s[i] ** 2).mean() + 1e-12)), 1) for i, n in enumerate(names)}
    print("stems dB", e)


if __name__ == "__main__":
    main()
