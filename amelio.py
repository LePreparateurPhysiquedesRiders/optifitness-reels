#!/usr/bin/env python3
"""Amélioration vidéo automatique : prepare (chiffre et dépose), verifie (contrôle), nettoie (supprime le dépôt temporaire)."""
import argparse, base64, json, os, re, secrets, shutil, subprocess, sys, tempfile
import numpy as np
from PIL import Image

REPO = "LePreparateurPhysiquedesRiders/optifitness-reels"; BR = "relais-temp"; ID = ["-c", "user.name=Opti Kit", "-c", "user.email=opti-kit@users.noreply.github.com"]


def git(*a, cwd=None):
    r = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)
    if r.returncode: sys.exit(r.stderr[-400:])
    return r.stdout.strip()


def prepare(a):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    n = os.path.getsize(a.input)
    if n > 95_000_000: sys.exit("Fichier trop lourd pour le relais (95 Mo maximum) : couper la vidéo en plusieurs parties.")
    k = AESGCM.generate_key(256); iv = os.urandom(12); name = secrets.token_hex(16) + ".bin"; d = tempfile.mkdtemp()
    git("init", "-q", "-b", BR, d); open(f"{d}/{name}", "wb").write(iv + AESGCM(k).encrypt(iv, open(a.input, "rb").read(), None))
    git("add", "-A", cwd=d); git(*ID, "commit", "-q", "-m", "Fichier chiffré temporaire", cwd=d); git("push", "-q", "-f", f"https://github.com/{REPO}", f"{BR}:{BR}", cwd=d)
    s = git("rev-parse", "HEAD", cwd=d); shutil.rmtree(d, ignore_errors=True)
    print(json.dumps({"url": f"https://raw.githubusercontent.com/{REPO}/{s}/{name}", "cle": base64.b64encode(k).decode(), "nom": os.path.basename(a.input)}, ensure_ascii=False))


def nette(p):
    t = tempfile.mktemp(suffix=".png"); subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "1", "-i", p, "-frames:v", "1", "-vf", "scale=1080:1920", t], check=True)
    g = np.asarray(Image.open(t).convert("L"), float); os.remove(t); return float((g[1:-1, 1:-1] * -4 + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]).var())


def verifie(a):
    def info(p):
        d = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", p], capture_output=True, text=True).stdout); v = next(s for s in d["streams"] if s["codec_type"] == "video")
        return v["width"], v["height"], float(d["format"]["duration"]), any(s["codec_type"] == "audio" for s in d["streams"])
    s, o = info(a.sortie), info(a.original); w, h = o[:2]; l = subprocess.run(["ffmpeg", "-hide_banner", "-i", a.sortie, "-i", a.original, "-lavfi", f"[0]scale={w}:{h}[a];[a][1]ssim", "-f", "null", "-"], capture_output=True, text=True).stderr
    m = re.search(r"All:([\d.]+)", l); ss = float(m.group(1)) if m else 0; n0, n1 = nette(a.original), nette(a.sortie); bad = []
    if abs(s[2] - o[2]) > .2: bad.append("Durée différente de l'original")
    if o[3] and not s[3]: bad.append("Son perdu")
    if ss < .9: bad.append("Image trop différente de l'original")
    if n1 < n0: bad.append("Pas de gain de netteté")
    print(json.dumps({"format": f"{s[0]}x{s[1]}", "duree_s": round(s[2], 2), "fidelite_ssim": round(ss, 3), "nettete_avant": round(n0, 1), "nettete_apres": round(n1, 1), "verdict": "OK" if not bad else "A CORRIGER", "problemes": bad}, ensure_ascii=False))


def nettoie(a): subprocess.run(["git", "push", "-q", f"https://github.com/{REPO}", "--delete", BR], capture_output=True); print("Relais supprimé")


p = argparse.ArgumentParser(); s = p.add_subparsers(dest="c", required=True)
q = s.add_parser("prepare"); q.add_argument("input"); q.set_defaults(f=prepare)
q = s.add_parser("verifie"); q.add_argument("sortie"); q.add_argument("original"); q.set_defaults(f=verifie)
q = s.add_parser("nettoie"); q.set_defaults(f=nettoie)
a = p.parse_args(); a.f(a)
