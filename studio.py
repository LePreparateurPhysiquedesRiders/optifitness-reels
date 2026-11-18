#!/usr/bin/env python3
"""Studio Opti' FITNESS : looks (étalonnages), lut, trans (transitions), music (musique originale), style (profil d'un Reel)."""
import argparse, glob, json, os, re, subprocess, sys
import numpy as np, soundfile as sf

K = os.environ.get("OPTI_HOME", os.path.expanduser("~/opti")); SR = 48000
XF = "fade wipeleft wiperight wipeup wipedown slideleft slideright slideup slidedown circlecrop rectcrop distance fadeblack fadewhite radial smoothleft smoothright smoothup smoothdown circleopen circleclose vertopen vertclose horzopen horzclose dissolve pixelize diagtl diagtr diagbl diagbr hlslice hrslice vuslice vdslice hblur fadegrays wipetl wipetr wipebl wipebr squeezeh squeezev zoomin fadefast fadeslow hlwind hrwind vuwind vdwind coverleft coverright coverup coverdown revealleft revealright revealup revealdown".split()
# nom : contraste, saturation, teinte ombres RVB, teinte hautes lumières RVB, voile noir, gamma
LOOKS = {"naturel_net": (1.06, 1.05, (0, 0, 0), (0, 0, 0), 0, 1), "neige_fraiche": (1.08, 1.02, (-.01, 0, .025), (.0, .01, .025), 0, .94), "alpin_froid": (1.12, .92, (-.03, 0, .04), (-.015, .005, .03), 0, 1), "golden_hour": (1.08, 1.14, (.015, 0, -.02), (.05, .02, -.04), 0, .97),
         "teal_orange": (1.14, 1.1, (-.04, .01, .05), (.05, .015, -.04), 0, 1), "teal_doux": (1.05, .98, (-.025, .01, .03), (.02, .01, -.015), .015, 1), "film_chaud": (1.03, .95, (.02, .005, -.005), (.03, .015, -.02), .035, .98), "film_froid": (1.03, .9, (-.01, .01, .025), (.005, .01, .012), .04, 1),
         "kodak_200": (1.1, 1.12, (.015, -.005, -.01), (.035, .02, -.025), .015, .97), "fuji_400": (1.08, 1.03, (-.02, .018, .015), (.0, .02, -.005), .02, .98), "cine_nuit": (1.18, .82, (-.03, -.005, .05), (-.01, 0, .025), 0, 1.12), "orage": (1.22, .72, (-.015, 0, .025), (-.015, -.005, .01), 0, 1.08),
         "punch_action": (1.2, 1.22, (-.012, 0, .012), (.012, .005, -.01), 0, 1), "pop_reels": (1.12, 1.3, (0, 0, .01), (.015, .01, 0), 0, .96), "mat_premium": (.96, .9, (.005, .005, .01), (.01, .008, 0), .06, 1), "doux_lifestyle": (.98, 1.02, (.012, .004, .005), (.02, .012, 0), .035, .92),
         "desature_doc": (1.1, .68, (0, 0, .008), (.008, .004, 0), .01, 1), "noir_blanc": (1.2, 0, (0, 0, 0), (0, 0, 0), 0, 1), "noir_blanc_mat": (1.03, 0, (.008, .008, .012), (.01, .008, .004), .06, .96), "ocean": (1.1, 1.1, (-.04, .02, .04), (-.01, .025, .03), 0, .98),
         "desert": (1.08, .98, (.03, .012, -.02), (.05, .03, -.035), .015, .96), "foret": (1.1, 1.0, (-.012, .025, -.012), (.012, .025, -.025), .01, 1), "retro_80": (1.06, 1.12, (.03, -.01, .05), (.04, .01, -.015), .03, .98), "vhs": (.94, 1.15, (.03, 0, .04), (.02, .01, 0), .08, .98)}


def run(c): return subprocess.run(c, capture_output=True, text=True)


def cube(n):
    ct, sa, sh, hi, fd, ga = LOOKS[n]; N = 33; g = np.linspace(0, 1, N); B, G, R = np.meshgrid(g, g, g, indexing="ij"); x = np.stack([R, G, B], -1).reshape(-1, 3)
    x = np.clip(x, 0, 1) ** ga; x = .5 + (x - .5) * ct; L = (x * [.2126, .7152, .0722]).sum(1, keepdims=True); x = L + (x - L) * sa
    L = np.clip(L, 0, 1); x = x + np.array(sh) * (1 - L) ** 2 * 2 + np.array(hi) * L ** 2 * 2; x = fd + x * (1 - fd * 1.4)
    return f'TITLE "{n}"\nLUT_3D_SIZE {N}\n' + "\n".join("%.5f %.5f %.5f" % tuple(v) for v in np.clip(x, 0, 1))


def cmd_looks(a):
    d = f"{K}/looks"; os.makedirs(d, exist_ok=True)
    for n in LOOKS: open(f"{d}/{n}.cube", "w").write(cube(n))
    print(len(LOOKS), "looks :", ", ".join(LOOKS))


def cmd_lut(a):
    p = f"{K}/looks/{a.name}.cube"
    if not os.path.exists(p): open(p, "w").write(cube(a.name)) if a.name in LOOKS else sys.exit("Look inconnu")
    v = f"lut3d={p}:interp=tetrahedral" if a.force >= 1 else f"split[a][b];[b]lut3d={p}:interp=tetrahedral[c];[a][c]blend=all_expr='A*(1-{a.force})+B*{a.force}'"
    r = run(["ffmpeg", "-y", "-v", "error", "-i", a.input, "-vf", v + ",format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-c:a", "copy", a.output])
    sys.exit(r.stderr) if r.returncode else print(a.output)


def probe(p):
    d = json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", p]).stdout); v = next(s for s in d["streams"] if s["codec_type"] == "video")
    return float(d["format"]["duration"]), v["width"], v["height"], eval(v["avg_frame_rate"]), any(s["codec_type"] == "audio" for s in d["streams"])


def cmd_trans(a):
    if a.type not in XF: sys.exit("Types : " + ", ".join(XF))
    da, w, h, fps, aa = probe(a.a); _, _, _, _, ab = probe(a.b); o = max(0, da - a.d)
    f = f"[0:v]fps={fps},scale={w}:{h},setsar=1,format=yuv420p[a];[1:v]fps={fps},scale={w}:{h},setsar=1,format=yuv420p[b];[a][b]xfade=transition={a.type}:duration={a.d}:offset={o:.3f}[v]"; m = ["-map", "[v]"]
    if aa and ab: f += f";[0:a]aresample=48000[x];[1:a]aresample=48000[y];[x][y]acrossfade=d={a.d}[s]"; m += ["-map", "[s]", "-c:a", "aac", "-b:a", "256k"]
    r = run(["ffmpeg", "-y", "-v", "error", "-i", a.a, "-i", a.b, "-filter_complex", f] + m + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "17", a.output])
    sys.exit(r.stderr) if r.returncode else print(a.output)


# ---------- MUSIQUE ORIGINALE (échantillons CC0 + synthèse) ----------
MOODS = {"energique": (126, [0, 8, 3, 10], "min"), "tension": (112, [0, 0, 8, 7], "min"), "epique": (118, [0, 10, 8, 10], "min"), "chill": (92, [0, 7, 9, 5], "maj"), "fun": (128, [0, 5, 9, 7], "maj"), "sombre": (100, [0, 1, 0, 10], "min")}


def smp(n):
    f = glob.glob(f"{K}/bank/sonicpi/etc/samples/{n}.flac"); x, r = sf.read(f[0], always_2d=True); x = x.mean(1)
    return np.interp(np.arange(0, len(x) * SR / r), np.arange(len(x)) * SR / r, x) if r != SR else x


def cmd_music(a):
    from scipy.signal import butter, sosfilt
    from pedalboard import Pedalboard, Reverb, Compressor, Limiter
    import pyloudnorm as pl
    bpm, pr, md = MOODS[a.mood]; bpm = a.bpm or bpm; r = np.random.default_rng(a.seed); root = 41 + int(r.integers(0, 7)); B = 60 / bpm; bar = 4 * B; n = int(a.dur * SR) + SR * 2
    L = {k: np.zeros(n) for k in ("kick", "sn", "hat", "bass", "pad", "arp")}
    def put(t, s, st, g=1): i = int(t * SR); m = min(len(s), n - i); L[st][i:i + m] += s[:m] * g if m > 0 else 0
    def saw(f, d, voices=5):
        t = np.arange(int(d * SR)) / SR; o = sum(2 * ((f * (1 + .004 * v) * t + r.random()) % 1) - 1 for v in np.linspace(-1, 1, voices)) / voices; return o
    k, s_, h = smp("bd_haus"), smp(str(r.choice(["sn_dolf", "elec_snare", "sn_generic"]))), smp(str(r.choice(["drum_cymbal_closed", "hat_snap", "hat_psych"])))[:int(.16 * SR)]
    tri = [0, 3 if md == "min" else 4, 7]; arp = [0, 7, 12, tri[1] + 12, 7, 12, 19, 12]; nb = int(np.ceil(a.dur / bar)) + 1; key = np.ones(n)
    for b in range(nb):
        t0 = b * bar; deg = pr[b % 4]; sec = b % 16; drop = sec >= 12 and sec < 14; intro = b < 2; fr = lambda m: 440 * 2 ** ((m - 69) / 12)
        c = sum(saw(fr(root + 24 + deg + x), bar) for x in tri) / 3; env = np.minimum(1, np.arange(len(c)) / (.02 * SR)) * np.minimum(1, (len(c) - np.arange(len(c))) / (.05 * SR)); put(t0, c * env, "pad", .5)
        for st in range(16):
            t = t0 + st * B / 4
            if not intro and not drop and st % 4 == 0: put(t, k, "kick", 1); i = int(t * SR); m = min(int(.22 * SR), n - i); key[i:i + m] = np.minimum(key[i:i + m], np.linspace(.25, 1, m) if m > 0 else 1)
            if not intro and not drop and st % 8 == 4: put(t, s_, "sn", .6)
            if st % 2 == 0 or r.random() < .35: put(t, h * (.8 if st % 4 == 2 else .45), "hat", .55)
            if not intro and st % 2 == 0 and st % 4 != 0: d = B / 2 * .9; o = saw(fr(root + 12 + deg), d, 3); put(t, o * np.exp(-np.arange(len(o)) / (.18 * SR)), "bass", 1)
            d = B / 4 * .9; o = saw(fr(root + 36 + deg + arp[(st + b) % 8]), d, 3) * np.exp(-np.arange(int(d * SR)) / (.05 * SR)); put(t, o, "arp", .32 if sec % 8 >= 4 or drop else .12)
    F = lambda x, c, m="low": sosfilt(butter(2, c, m, fs=SR, output="sos"), x)
    pad = F(L["pad"], 1500) * key; bass = F(L["bass"], 420) * key; arpv = F(L["arp"], 4200, "low")
    m = np.c_[pad * .55 + bass * .85 + L["kick"] * .95 + L["sn"] * .5 + L["hat"] * .3 + arpv * .6, pad * .55 + bass * .85 + L["kick"] * .95 + L["sn"] * .5 + np.roll(L["hat"], 90) * .3 + np.roll(arpv, 280) * .6]
    m = Pedalboard([Reverb(room_size=.35, wet_level=.14, dry_level=.9), Compressor(-14, 2.5, 8, 120), Limiter(-1.5)])(m.T.astype(np.float32), SR).T.astype(np.float64)[: int(a.dur * SR)]
    f = int(SR * 1.2); m[-f:] *= np.linspace(1, 0, f)[:, None]; m *= 10 ** ((-16 - pl.Meter(SR).integrated_loudness(m)) / 20); m = np.clip(m, -.98, .98); sf.write(a.output, m, SR, subtype="PCM_24"); print(json.dumps({"fichier": a.output, "ambiance": a.mood, "bpm": bpm, "duree_s": a.dur, "licence": "création originale + échantillons CC0"}, ensure_ascii=False))


# ---------- PROFIL DE STYLE ----------
def profile(p):
    d, w, h, fps, _ = probe(p); l = run(["ffmpeg", "-hide_banner", "-i", p, "-vf", "select='gt(scene,0.2)',showinfo", "-an", "-f", "null", "-"]).stderr; c = [float(x) for x in re.findall(r"pts_time:([\d.]+)", l)]
    st = run(["ffmpeg", "-hide_banner", "-i", p, "-vf", "fps=4,signalstats,metadata=print:file=-", "-an", "-f", "null", "-"]).stdout; Y = np.array([float(x) for x in re.findall(r"YAVG=([\d.]+)", st)]); S = np.array([float(x) for x in re.findall(r"SATAVG=([\d.]+)", st)])
    a = run(["ffmpeg", "-hide_banner", "-i", p, "-af", "ebur128=peak=true", "-f", "null", "-"]).stderr; I = re.findall(r"I:\s+(-?[\d.]+) LUFS", a); LRA = re.findall(r"LRA:\s+([\d.]+) LU", a)
    return {"duree_s": round(d, 1), "coupes_par_10s": round(len(c) / d * 10, 1), "premiere_coupe_s": round(c[0], 2) if c else None, "plan_moyen_s": round(d / (len(c) + 1), 2), "luminosite": round(float(Y.mean()), 0), "contraste": round(float(Y.std()), 0), "saturation": round(float(S.mean()), 0), "lufs": float(I[-1]) if I else None, "dynamique_LU": float(LRA[-1]) if LRA else None}


def cmd_style(a):
    P = profile(a.input); R = {"profil": P}
    if a.vs:
        Q = profile(a.vs); R["reference"] = Q; C = []
        if P["coupes_par_10s"] < Q["coupes_par_10s"] * .7: C.append("Rythme plus lent que la référence : ajouter des coupes")
        if P["coupes_par_10s"] > Q["coupes_par_10s"] * 1.4: C.append("Rythme plus rapide que la référence : laisser respirer")
        if abs(P["saturation"] - Q["saturation"]) > 12: C.append("Saturation éloignée de la référence : ajuster le look")
        if abs(P["luminosite"] - Q["luminosite"]) > 25: C.append("Luminosité éloignée de la référence")
        R["conseils"] = C
    print(json.dumps(R, ensure_ascii=False, indent=1))


p = argparse.ArgumentParser(); s = p.add_subparsers(dest="c", required=True)
q = s.add_parser("looks"); q.set_defaults(f=cmd_looks)
q = s.add_parser("lut"); q.add_argument("input"); q.add_argument("name"); q.add_argument("output"); q.add_argument("--force", type=float, default=.7); q.set_defaults(f=cmd_lut)
q = s.add_parser("trans"); q.add_argument("a"); q.add_argument("b"); q.add_argument("output"); q.add_argument("--type", default="smoothleft"); q.add_argument("--d", type=float, default=.3); q.set_defaults(f=cmd_trans)
q = s.add_parser("music"); q.add_argument("output"); q.add_argument("--mood", choices=list(MOODS), default="energique"); q.add_argument("--bpm", type=int); q.add_argument("--dur", type=float, default=30); q.add_argument("--seed", type=int, default=1); q.set_defaults(f=cmd_music)
q = s.add_parser("style"); q.add_argument("input"); q.add_argument("--vs"); q.set_defaults(f=cmd_style)
a = p.parse_args(); a.f(a)
