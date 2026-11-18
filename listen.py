#!/usr/bin/env python3
"""Écoute locale : reconnaît ce qui s'entend (527 sons) et juge l'équilibre voix/musique."""
import argparse, glob, json, os, subprocess, sys, tempfile
import numpy as np, soundfile as sf, sherpa_onnx as so

K = os.environ.get("OPTI_HOME", os.path.expanduser("~/opti"))
M = glob.glob(f"{K}/models/sherpa-onnx-ced-mini*")[0]; D = f"{K}/models/sherpa-onnx-spleeter-2stems-int8"
AT = so.AudioTagging(so.AudioTaggingConfig(model=so.AudioTaggingModelConfig(ced=f"{M}/model.int8.onnx", num_threads=2), labels=f"{M}/class_labels_indices.csv", top_k=80))
DEFECTS = ["Wind noise (microphone)", "Static", "White noise", "Pink noise", "Hum", "Mains hum", "Buzz", "Distortion", "Echo", "Reverberation", "Inside, small room", "Noise", "Environmental noise"]
MOODS = ["Happy music", "Exciting music", "Funny music", "Sad music", "Tender music", "Angry music", "Scary music"]


def load(p, sr):
    t = tempfile.mktemp(suffix=".wav")
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", p, "-vn", "-ac", "2", "-ar", str(sr), "-c:a", "pcm_f32le", t], capture_output=True, text=True)
    if r.returncode: sys.exit(r.stderr)
    x, _ = sf.read(t, always_2d=True); os.remove(t); return x.astype(np.float32)


def tags(m, sr):
    s = AT.create_stream(); s.accept_waveform(sr, m); return {e.name: float(e.prob) for e in AT.compute(s)}


def balance(p):
    c = so.OfflineSourceSeparationConfig(model=so.OfflineSourceSeparationModelConfig(spleeter=so.OfflineSourceSeparationSpleeterModelConfig(vocals=f"{D}/vocals.int8.onnx", accompaniment=f"{D}/accompaniment.int8.onnx"), num_threads=2))
    x = load(p, 44100); o = so.OfflineSourceSeparation(c).process(sample_rate=44100, samples=np.ascontiguousarray(x.T))
    def env(a):
        m = np.atleast_2d(np.array(a)).mean(0); n = int(.05 * o.sample_rate); k = len(m) // n
        return np.sqrt((m[: k * n].reshape(k, n) ** 2).mean(1) + 1e-12)
    v, a = env(o.stems[0].data), env(o.stems[1].data); on = v > np.percentile(v, 95) * .2
    return round(float(20 * np.log10(np.sqrt((v[on] ** 2).mean()) / np.sqrt((a[on] ** 2).mean() + 1e-12))), 1)


def analyse(p, voice=True):
    sr = 16000; m = load(p, sr).mean(1); m = np.r_[m, np.zeros(max(0, sr - len(m)), np.float32)]; T = tags(m, sr); W = []; L = 5 * sr
    for i in range(0, max(1, len(m) - sr), L):
        t = tags(m[i:i + L], sr); sp, mu = t.get("Speech", 0), t.get("Music", 0)
        if sp > .15 and mu > sp + .15: W.append(round(i / sr, 1))
    return T, W, balance(p) if voice else None


p = argparse.ArgumentParser(); p.add_argument("input"); p.add_argument("--ref"); p.add_argument("--expect"); p.add_argument("--no-voice", action="store_true"); a = p.parse_args()
T, W, B = analyse(a.input, not a.no_voice); bad = []
R = {"ce_que_j_entends": {k: round(v, 2) for k, v in sorted(T.items(), key=lambda z: -z[1])[:8]}, "ambiance_musique": {k: round(T[k], 2) for k in MOODS if T.get(k, 0) >= .04}, "indice_voix_musique": B}
d = {k: round(T[k], 2) for k in DEFECTS if T.get(k, 0) >= .3}
if d: R["defauts_entendus"] = d; bad.append(f"Défaut entendu : {d}")
if not a.no_voice:
    if W: bad.append(f"Musique qui couvre la voix vers {W} s")
    if B < -10: bad.append(f"Voix trop basse face à la musique (indice {B}, viser au moins -6)")
if a.expect and not any(a.expect.lower() in k.lower() for k, v in sorted(T.items(), key=lambda z: -z[1])[:8]): bad.append(f"Ne ressemble pas à « {a.expect} »")
if a.ref:
    Tr, _, Br = analyse(a.ref); R["indice_reference"] = Br
    if B < Br - 6: bad.append(f"Voix plus basse que dans la référence ({B} contre {Br})")
R["verdict"] = "OK" if not bad else "A CORRIGER"; R["problemes"] = bad
print(json.dumps(R, ensure_ascii=False, indent=1)); sys.exit(0 if not bad else 2)
