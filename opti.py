#!/usr/bin/env python3
"""Boîte à outils de montage Opti' FITNESS : voice, sfx, gen, mix, look, slow, beats, qca, qcv."""
import argparse, difflib, glob, json, os, re, subprocess, sys, tempfile, unicodedata
import numpy as np, soundfile as sf

SR = 48000
K = os.environ.get("OPTI_HOME", os.path.expanduser("~/opti"))


def sh(c):
    return subprocess.run(c, capture_output=True, text=True)


def load(p, ch=2):
    t = tempfile.mktemp(suffix=".wav")
    r = sh(["ffmpeg", "-y", "-v", "error", "-i", p, "-vn", "-ac", str(ch), "-ar", str(SR), "-c:a", "pcm_f32le", t])
    if r.returncode: sys.exit(f"Lecture audio impossible : {p}\n{r.stderr}")
    x, _ = sf.read(t, always_2d=True); os.remove(t)
    return x.astype(np.float64)


def db(v): return 20 * np.log10(np.maximum(v, 1e-9))


def lufs(x):
    import pyloudnorm as pl
    return float(pl.Meter(SR).integrated_loudness(x))


def true_peak(x):
    from scipy.signal import resample_poly
    return float(db(np.max(np.abs(resample_poly(x, 4, 1, axis=0)))))


def master(x, target=-14.0, ceil=-1.0):
    """Amène au niveau cible avec un vrai plafond de crête."""
    from pedalboard import Limiter
    for _ in range(6):
        x = x * 10 ** ((target - lufs(x)) / 20)
        if true_peak(x) <= ceil: return x
        y = Limiter(threshold_db=ceil - 1.0, release_ms=80)(x.T.astype(np.float32), SR).T
        x = y.astype(np.float64)
    return x * 10 ** ((ceil - 0.1 - true_peak(x)) / 20) if true_peak(x) > ceil else x


def rms_env(m, win=0.05):
    n = int(SR * win); k = len(m) // n
    return np.sqrt(np.mean(m[: k * n].reshape(k, n) ** 2, axis=1) + 1e-18)


def band_db(m, lo, hi):
    from scipy.signal import welch
    f, p = welch(m, SR, nperseg=8192)
    return float(10 * np.log10(np.sum(p[(f >= lo) & (f < hi)]) + 1e-18))


# ---------- VOIX ----------
def cmd_voice(a):
    from pedalboard import Pedalboard, HighpassFilter, PeakFilter, HighShelfFilter, Compressor
    d = tempfile.mkdtemp(); src = f"{d}/v.wav"
    sh(["ffmpeg", "-y", "-v", "error", "-i", a.input, "-vn", "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", src])
    if not a.no_denoise:
        r = sh([f"{K}/bin/deep-filter", "-a", str(a.atten), "-o", f"{d}/o", src])
        if r.returncode == 0 and os.path.exists(f"{d}/o/v.wav"): src = f"{d}/o/v.wav"
        else: print("Débruitage indisponible, on continue sans.", file=sys.stderr)
    x = load(src, 1)[:, 0]
    box = band_db(x, 250, 400) - band_db(x, 1000, 4000)
    cut = float(np.clip(box - 6, 0, 5)); pres = float(np.clip(box - 2, 1, 4))
    b = Pedalboard([HighpassFilter(80), PeakFilter(320, -cut, 1.0), PeakFilter(3500, pres, 0.9),
                    HighShelfFilter(9000, 2.0), Compressor(-22, 3, 6, 90)])
    y = b(x[None].astype(np.float32), SR)[0]
    t = f"{d}/c.wav"; sf.write(t, y, SR, subtype="FLOAT")
    t2 = f"{d}/d.wav"; sh(["ffmpeg", "-y", "-v", "error", "-i", t, "-af", "deesser=i=0.4:m=0.5:f=0.5", "-c:a", "pcm_f32le", t2])
    z = load(t2, 2)
    z = master(z, a.lufs, -1.5)
    sf.write(a.output, z, SR, subtype="PCM_24")
    print(json.dumps({"coupe_320Hz_dB": round(cut, 1), "presence_dB": round(pres, 1), "lufs": round(lufs(z), 1), "crete_dBTP": round(true_peak(z), 1)}))


# ---------- BRUITAGES GÉNÉRÉS PAR CODE (libres de droits : créés ici) ----------
def sweep(n, f0, f1, q, rng):
    """Bruit filtré passe-bande dont la fréquence glisse de f0 à f1."""
    w = rng.standard_normal(n); fc = np.geomspace(f0, f1, n)
    g = np.tan(np.pi * np.minimum(fc, SR * .45) / SR); k = 1 / q; o = np.zeros(n); s1 = s2 = 0.0
    for i in range(n):
        h = (w[i] - (k + g[i]) * s1 - s2) / (1 + g[i] * (k + g[i])); b = g[i] * h + s1
        l = g[i] * b + s2; s1 = g[i] * h + b; s2 = g[i] * b + l; o[i] = b
    return o


def stereo(m, pan=None):
    pan = np.zeros(len(m)) if pan is None else pan
    return np.c_[m * np.cos((pan + 1) * np.pi / 4), m * np.sin((pan + 1) * np.pi / 4)] * 1.414


def fin(x, peak=-3.0, rev=0.0):
    from pedalboard import Reverb
    x = np.atleast_2d(x)
    if rev:
        x = np.r_[x, np.zeros((int(SR * .6), 2))]
        x = Reverb(room_size=.45, wet_level=rev, dry_level=1, damping=.6)(x.T.astype(np.float32), SR).T
    n = min(int(SR * .004), len(x) // 4); x = np.array(x, dtype=np.float64)
    x[-n:] *= np.linspace(1, 0, n)[:, None]
    return x * 10 ** (peak / 20) / (np.max(np.abs(x)) + 1e-9)


def cmd_sfx(a):
    os.makedirs(a.dir, exist_ok=True); r = np.random.default_rng(7); out = {}
    def T(d): return np.linspace(0, d, int(SR * d), endpoint=False)
    def wh(d, f0, fm, f1, side):
        n = int(SR * d); p = int(n * .55)
        m = np.r_[sweep(p, f0, fm, 1.2, r), sweep(n - p, fm, f1, 1.2, r)]
        e = np.sin(np.pi * (np.arange(n) / n) ** .8) ** 2
        return stereo(m * e, np.linspace(-side, side, n))
    out["whoosh_court"] = fin(wh(.32, 350, 3200, 500, .7), -4, .12)
    out["whoosh_long"] = fin(wh(.8, 180, 2400, 300, .85), -4, .18)
    out["swipe"] = fin(wh(.16, 1200, 6500, 1800, .5), -8, .05)
    t = T(.9); s = np.sin(2 * np.pi * np.cumsum(38 + 90 * np.exp(-t * 28)) / SR) * np.exp(-t * 6.5)
    n = sweep(len(t), 2600, 180, .8, r) * np.exp(-t * 26) * 1.2
    out["impact"] = fin(stereo(s + n), -3, .15)
    t = T(.35); out["sub_drop"] = fin(stereo(np.sin(2 * np.pi * np.cumsum(90 * np.exp(-t * 4) + 30) / SR) * np.exp(-t * 9)), -5)
    t = T(1.6); e = (t / 1.6) ** 2.6
    out["riser"] = fin(stereo(sweep(len(t), 200, 7000, 2.5, r) * e + .25 * np.sin(2 * np.pi * np.cumsum(70 + 500 * e) / SR) * e), -6, .2)
    t = T(.09); out["pop"] = fin(stereo(np.sin(2 * np.pi * np.cumsum(1500 * np.exp(-t * 55) + 320) / SR) * np.exp(-t * 60)), -7, .06)
    t = T(.05); out["clic_souris"] = fin(stereo(sweep(len(t), 4200, 2200, 2.5, r) * np.exp(-t * 170)), -8)
    t = T(.9); out["ding_mot_cle"] = fin(stereo((np.sin(2 * np.pi * 1318.5 * t) + .45 * np.sin(2 * np.pi * 2637 * t)) * np.exp(-t * 7)), -12, .22)
    n = int(SR * 1.2); g = (r.random(n) < .012) * r.uniform(.3, 1, n)
    from scipy.signal import fftconvolve
    gr = fftconvolve(g, np.exp(-np.arange(240) / 45) * r.standard_normal(240), "same")
    env = np.sin(np.pi * np.arange(n) / n) ** 1.4
    out["carve_neige"] = fin(stereo((sweep(n, 2600, 1300, .7, r) * .55 + gr * .9) * env, np.linspace(-.5, .5, n)), -5, .08)
    n = SR * 8; lfo = .55 + .45 * np.interp(np.arange(n), np.linspace(0, n, 14), r.random(14))
    w = stereo(sweep(n, 420, 780, .5, r) * lfo); f = int(SR * .5)
    w[:f] = w[:f] * np.linspace(0, 1, f)[:, None] + w[-f:] * np.linspace(1, 0, f)[:, None]
    out["vent_boucle"] = fin(w[:-f], -12)
    for k, v in out.items(): sf.write(f"{a.dir}/{k}.wav", v, SR, subtype="PCM_24")
    print(", ".join(sorted(out)))


# ---------- MIXAGE ----------
def fit(x, n, loop=False):
    if loop and len(x) < n: x = np.tile(x, (n // len(x) + 1, 1))
    return x[:n] if len(x) >= n else np.r_[x, np.zeros((n - len(x), 2))]


def cmd_mix(a):
    from scipy.ndimage import maximum_filter1d, uniform_filter1d
    v = load(a.voice); n = len(v)
    if a.dur: n = int(a.dur * SR); v = fit(v, n)
    m = v.mean(1); e = db(rms_env(m, .02)); on = e > max(e.max() - 32, -50)
    on = maximum_filter1d(on.astype(float), 25)
    act = uniform_filter1d(np.interp(np.arange(n), np.arange(len(on)) * SR * .02, on), int(SR * .12))
    def bed(p, duck, free, loop):
        g = 10 ** ((free + (duck - free) * act) / 20)
        x = fit(load(p), n, loop); x = x * 10 ** ((-23 - lufs(x if n > SR else np.r_[x, x])) / 20)
        return x * g[:, None]
    rest = np.zeros((n, 2))
    if a.ambiance: rest += bed(a.ambiance, -13, -1, False)
    if a.music: rest += bed(a.music, -11, 0, True)
    for s in a.sfx or []:
        t, f, *g = s.split(":"); x = load(os.path.expanduser(f)) * 10 ** (float(g[0] if g else -8) / 20); i = int(float(t) * SR)
        if i < n: L = min(len(x), n - i); rest[i:i + L] += x[:L]
    x = v + rest
    vo = v[act > .9]; re_ = rest[act > .9]
    vb = float(db(np.sqrt(np.mean(vo ** 2) + 1e-18)) - db(np.sqrt(np.mean(re_ ** 2) + 1e-18))) if len(vo) else 99.0
    x = master(x)
    sf.write(a.output, x, SR, subtype="PCM_24")
    print(json.dumps({"voix_au_dessus_du_fond_dB": round(vb, 1), "lufs": round(lufs(x), 1), "crete_dBTP": round(true_peak(x), 1)}))


# ---------- IMAGE ----------
def cmd_look(a):
    d = tempfile.mkdtemp(); pre = []
    if a.stab:
        sh(["ffmpeg", "-y", "-v", "error", "-i", a.input, "-vf", f"vidstabdetect=shakiness=6:accuracy=12:result={d}/t.trf", "-f", "null", "-"])
        pre = [f"vidstabtransform=input={d}/t.trf:smoothing=18:zoom=1:optzoom=0", "unsharp=5:5:0.4"]
    chain = pre + ["scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos", "crop=1080:1920", "hqdn3d=1.2:1.0:3:3"]
    if a.cine: chain += ["eq=contrast=1.05:saturation=1.08:gamma=0.98", "colorbalance=rs=.02:bs=-.02:rh=.02:bh=-.02"]
    chain += ["cas=0.45", "format=yuv420p"]
    r = sh(["ffmpeg", "-y", "-v", "error", "-i", a.input, "-vf", ",".join(chain), "-c:v", "libx264", "-preset", a.preset, "-crf", "17",
            "-maxrate", "20M", "-bufsize", "30M", "-profile:v", "high", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-movflags", "+faststart", a.output])
    if r.returncode: sys.exit(r.stderr)
    print(a.output)


def cmd_slow(a):
    fps = 30 * a.x
    r = sh(["ffmpeg", "-y", "-v", "error", "-i", a.input, "-an", "-vf", f"minterpolate=fps={fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,setpts={a.x}*PTS,fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", a.output])
    if r.returncode: sys.exit(r.stderr)
    print(a.output)


def cmd_gen(a):
    import shutil
    from gradio_client import Client
    try:
        f = Client("stabilityai/stable-audio-3", verbose=False).predict("small-" + a.kind, a.prompt, a.dur, 8, 1.0, "pingpong", a.seed, api_name="/infer")
        shutil.copy(f, a.output); print(a.output)
    except Exception as e:
        print(f"Génération indisponible (quota ou service) : {str(e)[:160]}", file=sys.stderr); sys.exit(3)


def cmd_beats(a):
    import librosa
    y, sr = librosa.load(a.input, sr=22050, mono=True)
    tempo, b = librosa.beat.beat_track(y=y, sr=sr, units="time")
    o = librosa.onset.onset_strength(y=y, sr=sr); pk = librosa.util.peak_pick(o, pre_max=8, post_max=8, pre_avg=20, post_avg=20, delta=np.std(o), wait=20)
    print(json.dumps({"bpm": round(float(np.atleast_1d(tempo)[0]), 1), "beats": [round(float(t), 3) for t in b], "accents": [round(float(t), 3) for t in librosa.frames_to_time(pk, sr=sr)]}))


# ---------- CONTRÔLE QUALITÉ : LES OREILLES ----------
def norm_words(t):
    t = unicodedata.normalize("NFD", t.lower()); t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    N = dict(zip("zero un une deux trois quatre cinq six sept huit neuf dix onze douze treize quatorze quinze seize vingt trente quarante cinquante soixante cent".split(), "0 1 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 20 30 40 50 60 100".split()))
    return [N.get(w, w) for w in re.findall(r"[a-z0-9]+", t)]


def transcribe(x):
    import sherpa_onnx as so
    M = f"{K}/models/sherpa-onnx-whisper-small"
    r = so.OfflineRecognizer.from_whisper(encoder=f"{M}/small-encoder.int8.onnx", decoder=f"{M}/small-decoder.int8.onnx", tokens=f"{M}/small-tokens.txt", language="fr", task="transcribe", num_threads=2)
    m = x.mean(1).astype(np.float32); out = []; L = 25 * SR
    for i in range(0, len(m), L):
        s = r.create_stream(); s.accept_waveform(SR, m[i:i + L]); r.decode_stream(s); out.append(s.result.text)
    return " ".join(out).strip()


def cmd_qca(a):
    x = load(a.input); m = x.mean(1); bad = []; R = {}
    R["lufs"] = round(lufs(x), 1); R["crete_dBTP"] = round(true_peak(x), 1)
    if not -15.5 <= R["lufs"] <= -12.5: bad.append(f"Niveau {R['lufs']} LUFS (viser -14)")
    if R["crete_dBTP"] > -0.9: bad.append(f"Crête trop haute {R['crete_dBTP']} dBTP (max -1)")
    R["saturation_pct"] = round(100 * float(np.mean(np.abs(x) >= .995)), 3)
    if R["saturation_pct"] > .01: bad.append("Saturation audible")
    d = np.abs(np.diff(m)); loc = np.convolve(d, np.ones(49) / 49, "same")
    cl = np.where((d > .12) & (d > 14 * loc))[0]; cl = cl[np.r_[True, np.diff(cl) > SR // 20]] if len(cl) else cl
    R["clics"] = [round(float(i) / SR, 2) for i in cl[:12]]
    if len(cl): bad.append(f"{len(cl)} clic(s) de coupe vers {R['clics'][:5]} s")
    e = db(rms_env(m)); top = np.percentile(e, 95); low = e < top - 38
    runs = []; s = None
    for i, f in enumerate(np.r_[low, False]):
        if f and s is None: s = i
        if not f and s is not None:
            if (i - s) * .05 >= a.gap: runs.append([round(s * .05, 2), round(i * .05, 2)])
            s = None
    R["blancs"] = runs; R["voix_vs_bruit_de_fond_dB"] = round(float(top - np.percentile(e, 8)), 1)
    if runs: bad.append(f"Blanc(s) de plus de {a.gap} s : {runs[:4]}")
    v = m[: len(e) * int(SR * .05)][np.repeat(e > top - 20, int(SR * .05))]
    if len(v) > SR // 2:
        mid = band_db(v, 1000, 4000); R["sifflantes_dB"] = round(band_db(v, 5000, 9000) - mid, 1); R["son_enferme_dB"] = round(band_db(v, 250, 400) - mid, 1); R["sourd_dB"] = round(band_db(v, 8000, 14000) - mid, 1)
        if R["sifflantes_dB"] > 2: bad.append("Sifflantes trop fortes")
        if R["son_enferme_dB"] > 10: bad.append("Voix enfermée (250-400 Hz)")
        if R["sourd_dB"] < -32: bad.append("Voix sourde (manque d'aigus)")
    if a.script:
        ref = norm_words(open(a.script, encoding="utf-8").read() if os.path.exists(a.script) else a.script); txt = transcribe(x); hyp = norm_words(txt)
        sm = difflib.SequenceMatcher(None, ref, hyp, autojunk=False); R["transcription"] = txt; R["mots_compris_pct"] = round(100 * sm.ratio(), 1)
        R["mots_a_reecouter"] = [" ".join(ref[i:j]) for op, i, j, _, _ in sm.get_opcodes() if op in ("replace", "delete")][:12]
        if R["mots_compris_pct"] < a.min_words: bad.append(f"Voix peu intelligible : {R['mots_compris_pct']} % des mots reconnus")
    if a.ref:
        B = [(60, 150), (150, 400), (400, 1000), (1000, 4000), (4000, 8000), (8000, 16000)]; r = load(a.ref).mean(1)
        def prof(z): v = np.array([band_db(z, *b) for b in B]); return v - v.mean()
        D = prof(m) - prof(r); R["ecart_reference_dB"] = {f"{l}-{h}Hz": round(float(d), 1) for (l, h), d in zip(B, D)}
        if np.max(np.abs(D)) > 6: bad.append(f"Équilibre du son éloigné de la référence : {R['ecart_reference_dB']}")
    R["verdict"] = "OK" if not bad else "A CORRIGER"; R["problemes"] = bad
    print(json.dumps(R, ensure_ascii=False, indent=1)); sys.exit(0 if not bad else 2)


# ---------- CONTRÔLE QUALITÉ : LES YEUX ----------
def cmd_qcv(a):
    from PIL import Image, ImageDraw
    p = json.loads(sh(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", a.input]).stdout)
    v = next(s for s in p["streams"] if s["codec_type"] == "video"); au = [s for s in p["streams"] if s["codec_type"] == "audio"]
    dur = float(p["format"]["duration"]); fps = eval(v["avg_frame_rate"]); bad = []
    R = {"format": f"{v['width']}x{v['height']}", "fps": round(fps, 2), "duree_s": round(dur, 2), "codec": v["codec_name"], "pixels": v["pix_fmt"], "debit_Mbps": round(int(p["format"]["bit_rate"]) / 1e6, 1)}
    if (v["width"], v["height"]) != (1080, 1920): bad.append(f"Format {R['format']} au lieu de 1080x1920")
    if v["codec_name"] != "h264" or v["pix_fmt"] != "yuv420p": bad.append("Encodage non compatible (h264 yuv420p attendu)")
    if not au: bad.append("Pas de piste audio")
    if not 23.9 <= fps <= 60.1: bad.append(f"Cadence inhabituelle {R['fps']} i/s")
    log = sh(["ffmpeg", "-hide_banner", "-i", a.input, "-vf", "blackdetect=d=0.04:pix_th=0.08,freezedetect=n=-50dB:d=0.7", "-an", "-f", "null", "-"]).stderr
    bl = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", log); fr = re.findall(r"freeze_start: ([\d.]+)[\s\S]*?freeze_end: ([\d.]+)", log)
    R["ecrans_noirs"] = [[round(float(x), 2), round(float(y), 2)] for x, y in bl]; R["images_figees"] = [[round(float(x), 2), round(float(y), 2)] for x, y in fr]
    if bl: bad.append(f"Écran noir à {R['ecrans_noirs'][:3]}")
    av = []
    if fr: av.append(f"Image figée à {R['images_figees'][:3]} : normal seulement sur un écran graphique")
    log = sh(["ffmpeg", "-hide_banner", "-i", a.input, "-vf", "select='gt(scene,0.2)',showinfo", "-an", "-f", "null", "-"]).stderr
    cuts = [round(float(t), 2) for t in re.findall(r"pts_time:([\d.]+)", log)]; pts = [0] + cuts + [dur]; sh_len = np.diff(pts)
    R["coupes"] = cuts; R["plan_moyen_s"] = round(float(np.mean(sh_len)), 2); R["plan_le_plus_long_s"] = round(float(np.max(sh_len)), 2)
    if dur > 12 and R["plan_le_plus_long_s"] > 7: av.append(f"Plan de {R['plan_le_plus_long_s']} s détecté : vérifier s'il manque du mouvement")
    st = sh(["ffmpeg", "-hide_banner", "-i", a.input, "-vf", "fps=4,signalstats,metadata=print:file=-", "-an", "-f", "null", "-"]).stdout
    Y = np.array([float(n) for n in re.findall(r"YAVG=([\d.]+)", st)]); S = np.array([float(n) for n in re.findall(r"SATAVG=([\d.]+)", st)])
    R["luminosite_moy"] = round(float(Y.mean()), 1); R["saturation_moy"] = round(float(S.mean()), 1)
    dark = np.where(Y < 38)[0] / 4; bright = np.where(Y > 205)[0] / 4
    if len(dark): av.append(f"Passage sombre vers {round(float(dark[0]), 1)} s : normal seulement sur un fond graphique")
    if len(bright): bad.append(f"Passage surexposé vers {round(float(bright[0]), 1)} s")
    ex = []
    for c in cuts:
        i = int(c * 4)
        if 2 <= i < len(Y) - 2 and abs(Y[i + 1] - Y[i - 2]) > 55: ex.append(c)
    R["sauts_exposition"] = ex
    d = tempfile.mkdtemp(); W, H2 = 270, 480
    def grab(t, name):
        sh(["ffmpeg", "-y", "-v", "error", "-ss", str(max(0, min(t, dur - .05))), "-i", a.input, "-frames:v", "1", "-vf", f"scale={W}:{H2}", f"{d}/{name}.png"])
        im = Image.open(f"{d}/{name}.png").convert("RGBA"); o = Image.new("RGBA", im.size, (0, 0, 0, 0)); g = ImageDraw.Draw(o)
        g.rectangle([0, 0, W, int(H2 * .14)], fill=(255, 0, 60, 70)); g.rectangle([0, int(H2 * .80), W, H2], fill=(255, 0, 60, 70)); g.rectangle([int(W * .86), int(H2 * .14), W, int(H2 * .80)], fill=(255, 0, 60, 70))
        im = Image.alpha_composite(im, o); ImageDraw.Draw(im).rectangle([0, 0, 62, 15], fill=(0, 0, 0, 255)); ImageDraw.Draw(im).text((4, 2), f"{t:.1f}s", fill="white")
        return im.convert("RGB")
    ts = [0, .5, 1, 2, 3] + list(np.linspace(4, max(4.1, dur - .1), a.n)); ims = [grab(float(t), f"f{i}") for i, t in enumerate(ts)]
    cols = 5; rows = int(np.ceil(len(ims) / cols)); sheet = Image.new("RGB", (cols * W, rows * H2), "white")
    for i, m in enumerate(ims): sheet.paste(m, ((i % cols) * W, (i // cols) * H2))
    sheet.save(a.sheet); R["planche"] = a.sheet; R["a_verifier_sur_la_planche"] = av
    R["verdict"] = "OK" if not bad else "A CORRIGER"; R["problemes"] = bad
    print(json.dumps(R, ensure_ascii=False, indent=1)); sys.exit(0 if not bad else 2)


p = argparse.ArgumentParser(); s = p.add_subparsers(dest="c", required=True)
q = s.add_parser("voice"); q.add_argument("input"); q.add_argument("output"); q.add_argument("--no-denoise", action="store_true"); q.add_argument("--atten", type=int, default=28); q.add_argument("--lufs", type=float, default=-16); q.set_defaults(f=cmd_voice)
q = s.add_parser("sfx"); q.add_argument("dir", nargs="?", default=f"{K}/sfx"); q.set_defaults(f=cmd_sfx)
q = s.add_parser("mix"); q.add_argument("--voice", required=True); q.add_argument("--ambiance"); q.add_argument("--music"); q.add_argument("--sfx", action="append", help="temps:fichier:gain_dB"); q.add_argument("--dur", type=float); q.add_argument("-o", "--output", required=True); q.set_defaults(f=cmd_mix)
q = s.add_parser("look"); q.add_argument("input"); q.add_argument("output"); q.add_argument("--stab", action="store_true"); q.add_argument("--cine", action="store_true"); q.add_argument("--preset", default="medium"); q.set_defaults(f=cmd_look)
q = s.add_parser("slow"); q.add_argument("input"); q.add_argument("output"); q.add_argument("--x", type=int, default=3); q.set_defaults(f=cmd_slow)
q = s.add_parser("gen"); q.add_argument("kind", choices=["sfx", "music"]); q.add_argument("prompt"); q.add_argument("output"); q.add_argument("--dur", type=float, default=4); q.add_argument("--seed", type=int, default=7); q.set_defaults(f=cmd_gen)
q = s.add_parser("beats"); q.add_argument("input"); q.set_defaults(f=cmd_beats)
q = s.add_parser("qca"); q.add_argument("input"); q.add_argument("--script"); q.add_argument("--ref"); q.add_argument("--gap", type=float, default=.7); q.add_argument("--min-words", type=float, default=85); q.set_defaults(f=cmd_qca)
q = s.add_parser("qcv"); q.add_argument("input"); q.add_argument("--sheet", default="planche.png"); q.add_argument("--n", type=int, default=5); q.set_defaults(f=cmd_qcv)
a = p.parse_args(); a.f(a)
