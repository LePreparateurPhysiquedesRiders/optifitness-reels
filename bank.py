#!/usr/bin/env python3
"""Banque libre de droits Opti' FITNESS : sync (télécharge), find (cherche), stats (compte)."""
import argparse, glob, json, os, re, shutil, subprocess, sys
import soundfile as sf

K = os.environ.get("OPTI_HOME", os.path.expanduser("~/opti")); B = f"{K}/bank"; IDX = f"{B}/index.json"
FR = {"whoosh": "swoosh woosh swish swipe sweep", "swoosh": "whoosh woosh swish swipe", "clic": "click", "souris": "click mouse", "bouton": "button", "impact": "impact hit thud", "choc": "impact hit", "coup": "hit punch", "metal": "metal", "bois": "wood", "pierre": "stone", "verre": "glass",
      "pas": "footstep", "neige": "snow", "vent": "wind air", "souffle": "whoosh air wind", "transition": "whoosh swipe swoosh sweep", "balayage": "swipe sweep", "montee": "rise riser sweep up", "descente": "down drop fall",
      "explosion": "explosion boom", "basse": "bass sub", "batterie": "drum loop", "boucle": "loop", "ambiance": "ambi ambient drone pad", "notification": "notification alert ding", "succes": "success confirmation win", "erreur": "error fail",
      "machine": "typewriter keyboard type", "texte": "typewriter type pop", "cloche": "bell ding chime", "magie": "sparkle magic shimmer"}


def run(c, cwd=None): return subprocess.run(c, cwd=cwd, capture_output=True, text=True)


def sparse(repo, dest, patterns):
    if os.path.isdir(dest): return
    t = dest + ".tmp"; shutil.rmtree(t, ignore_errors=True)
    run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--sparse", f"https://github.com/{repo}", t])
    run(["git", "sparse-checkout", "set", "--no-cone"] + patterns, cwd=t); run(["git", "checkout", "-q"], cwd=t)
    shutil.rmtree(f"{t}/.git", ignore_errors=True); os.rename(t, dest)


def sync():
    os.makedirs(B, exist_ok=True)
    sparse("kapishdima/soundcn", f"{B}/kenney", ["/assets/kenney_*/*"])
    sparse("sonic-pi-net/sonic-pi", f"{B}/sonicpi", ["/etc/samples/*"])
    sparse("gl-transitions/gl-transitions", f"{B}/gl", ["/transitions/*.glsl", "/LICENSE"])
    if not os.path.isdir(f"{B}/uisfx"):
        run(["npm", "pack", "-s", "uisfx"], cwd=B); f = glob.glob(f"{B}/uisfx-*.tgz")[0]; run(["tar", "xzf", f], cwd=B); os.rename(f"{B}/package", f"{B}/uisfx"); os.remove(f)
    I = []
    for src, root in (("Kenney CC0", f"{B}/kenney/assets"), ("Sonic Pi CC0", f"{B}/sonicpi/etc/samples"), ("uisfx CC0", f"{B}/uisfx/sounds")):
        for p in glob.glob(f"{root}/**/*", recursive=True):
            if not re.search(r"\.(wav|ogg|flac)$", p, re.I): continue
            try: d = round(sf.info(p).duration, 2)
            except Exception: d = None
            I.append({"f": p, "d": d, "src": src, "t": re.sub(r"[^a-z0-9]+", " ", re.sub(r"([a-z])([A-Z])", r"\1 \2", os.path.relpath(p, root)).lower()).strip()})
    json.dump(I, open(IDX, "w")); stats()


def stats():
    I = json.load(open(IDX)); c = {}
    for x in I: c[x["src"]] = c.get(x["src"], 0) + 1
    print(json.dumps({"sons": len(I), "par_source": c, "transitions_shader": len(glob.glob(f"{B}/gl/transitions/*.glsl"))}, ensure_ascii=False))


def find(q, n, maxd):
    I = json.load(open(IDX)); W = []
    for w in re.findall(r"[a-z0-9éèêàç]+", q.lower()):
        w = w.translate(str.maketrans("éèêàç", "eeeac")); W.append([w] + FR.get(w, "").split())
    R = []
    for x in I:
        if maxd and x["d"] and x["d"] > maxd: continue
        s = sum(any(a in x["t"] for a in g) for g in W)
        if s: R.append((s, x))
    R.sort(key=lambda z: (-z[0], z[1]["d"] or 99))
    for s, x in R[:n]: print(json.dumps({"fichier": x["f"], "duree_s": x["d"], "licence": x["src"]}, ensure_ascii=False))
    if not R: print("Aucun son trouvé")


p = argparse.ArgumentParser(); s = p.add_subparsers(dest="c", required=True)
s.add_parser("sync"); s.add_parser("stats"); q = s.add_parser("find"); q.add_argument("q"); q.add_argument("--n", type=int, default=10); q.add_argument("--max", type=float)
a = p.parse_args()
if a.c == "sync": sync()
elif a.c == "stats": stats()
else: find(a.q, a.n, a.max)
