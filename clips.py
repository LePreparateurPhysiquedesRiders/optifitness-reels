#!/usr/bin/env python3
"""Clips libres de droits Pixabay : cherche (résultats + planche d'aperçus) et prend (télécharge un clip)."""
import argparse, io, json, os, sys
import requests
from PIL import Image, ImageDraw

API = "https://pixabay.com/api/videos/"


def key():
    k = os.environ.get("PIXABAY_API_KEY")
    if not k: sys.exit("Clé Pixabay manquante : définir PIXABAY_API_KEY.")
    return k


def api(**p):
    r = requests.get(API, params={"key": key(), "safesearch": "true", **p}, timeout=30)
    if r.status_code != 200: sys.exit(f"Pixabay a refusé la demande (code {r.status_code}).")
    return r.json()


def best(v):
    for s in ("large", "medium", "small", "tiny"):
        x = v["videos"].get(s) or {}
        if x.get("url"): return s, x
    return None, {}


def cherche(a):
    d = api(q=a.q, per_page=min(200, a.n * 4), order=a.ordre, video_type="film"); R = []
    for v in d.get("hits", []):
        s, x = best(v)
        if not s or x.get("width", 0) < a.min or v["duration"] < a.duree: continue
        if a.vertical and x["height"] <= x["width"]: continue
        R.append({"id": v["id"], "duree_s": v["duration"], "format": f"{x['width']}x{x['height']}", "tags": v["tags"], "auteur": v["user"], "page": v["pageURL"], "vues": v["views"], "apercu": x.get("thumbnail")})
        if len(R) >= a.n: break
    if a.planche and R:
        W, H = 320, 180; c = 4; S = Image.new("RGB", (c * W, (len(R) + c - 1) // c * H), "black")
        for i, r in enumerate(R):
            try: m = Image.open(io.BytesIO(requests.get(r["apercu"], timeout=20).content)).convert("RGB"); m.thumbnail((W, H))
            except Exception: m = Image.new("RGB", (W, H), "gray")
            g = ImageDraw.Draw(m); g.rectangle([0, 0, 150, 14], fill="black"); g.text((3, 1), f"{r['id']} {r['duree_s']}s", fill="white"); S.paste(m, (i % c * W, i // c * H))
        S.save(a.planche)
    for r in R: r.pop("apercu")
    print(json.dumps({"total_pixabay": d.get("totalHits"), "clips": R}, ensure_ascii=False, indent=1))


def prend(a):
    h = api(id=a.id).get("hits", [])
    if not h: sys.exit("Clip introuvable")
    v = h[0]; s, x = best(v)
    with requests.get(x["url"], stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(a.sortie, "wb") as f:
            for b in r.iter_content(1 << 20): f.write(b)
    print(json.dumps({"fichier": a.sortie, "format": f"{x['width']}x{x['height']}", "duree_s": v["duration"], "auteur": v["user"], "page": v["pageURL"], "licence": "Pixabay Content License"}, ensure_ascii=False))


p = argparse.ArgumentParser(); s = p.add_subparsers(dest="c", required=True)
q = s.add_parser("cherche"); q.add_argument("q"); q.add_argument("--n", type=int, default=12); q.add_argument("--min", type=int, default=1280); q.add_argument("--duree", type=int, default=3); q.add_argument("--vertical", action="store_true"); q.add_argument("--ordre", default="popular", choices=["popular", "latest"]); q.add_argument("--planche"); q.set_defaults(f=cherche)
q = s.add_parser("prend"); q.add_argument("id", type=int); q.add_argument("sortie"); q.set_defaults(f=prend)
a = p.parse_args(); a.f(a)
