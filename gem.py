#!/usr/bin/env python3
"""Critique d'un montage par Gemini : envoie la vidéo, attend l'analyse, supprime le fichier distant."""
import json, mimetypes, os, sys, time
import requests

B = "https://generativelanguage.googleapis.com"
KEY = os.environ["GEMINI_API_KEY"]; H = {"x-goog-api-key": KEY}
MODELS = os.environ.get("GEMINI_MODELS", "gemini-3-flash-preview,gemini-flash-latest,gemini-2.5-flash").split(",")


def upload(p):
    n = os.path.getsize(p); m = mimetypes.guess_type(p)[0] or "video/mp4"
    r = requests.post(f"{B}/upload/v1beta/files", headers={**H, "X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start", "X-Goog-Upload-Header-Content-Length": str(n), "X-Goog-Upload-Header-Content-Type": m, "Content-Type": "application/json"}, json={"file": {"display_name": os.path.basename(p)}}, timeout=60)
    r.raise_for_status(); u = r.headers["X-Goog-Upload-URL"]
    r = requests.post(u, headers={"X-Goog-Upload-Offset": "0", "X-Goog-Upload-Command": "upload, finalize", "Content-Length": str(n)}, data=open(p, "rb"), timeout=600)
    r.raise_for_status(); f = r.json()["file"]
    for _ in range(60):
        if f.get("state") == "ACTIVE": return f
        if f.get("state") == "FAILED": sys.exit("Gemini n'a pas pu lire la vidéo")
        time.sleep(3); f = requests.get(f"{B}/v1beta/{f['name']}", headers=H, timeout=30).json()
    sys.exit("Délai dépassé pendant la préparation de la vidéo")


def ask(f, prompt):
    body = {"contents": [{"parts": [{"file_data": {"mime_type": f["mimeType"], "file_uri": f["uri"]}}, {"text": prompt}]}], "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}}
    last = ""
    for m in MODELS:
        for _ in range(3):
            r = requests.post(f"{B}/v1beta/models/{m}:generateContent", headers=H, json=body, timeout=300)
            if r.status_code == 200:
                d = r.json(); return m, "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"]), d.get("usageMetadata", {})
            last = f"{m}: {r.status_code} {r.text[:200]}"
            if r.status_code in (429, 500, 503): time.sleep(12)
            else: break
    sys.exit(f"Gemini indisponible : {last}")


P = sys.argv[2] if len(sys.argv) > 2 and not os.path.exists(sys.argv[2]) else open(sys.argv[2], encoding="utf-8").read()
f = upload(sys.argv[1])
try:
    m, t, u = ask(f, P); print(json.dumps({"modele": m, "jetons": u.get("totalTokenCount")}, ensure_ascii=False)); print(t)
finally:
    requests.delete(f"{B}/v1beta/{f['name']}", headers=H, timeout=30)
