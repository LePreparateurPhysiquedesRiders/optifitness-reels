#!/usr/bin/env python3
"""Publie un trial reel Instagram via l'API Graph (Content Publishing).

Usage : IG_TOKEN=... python3 ig_publish.py --video URL --cover URL --caption-file FICHIER
Affiche un JSON {ok, mediaId, permalink} ou {ok:false, error}.
"""
import argparse, json, os, sys, time, urllib.parse, urllib.request, urllib.error

IG_USER = os.environ.get("IG_USER_ID", "17841402643449604")
API = "https://graph.facebook.com/v23.0"


def call(method, path, params):
    params = dict(params, access_token=os.environ["IG_TOKEN"])
    data = urllib.parse.urlencode(params).encode()
    if method == "GET":
        req = urllib.request.Request(f"{API}/{path}?{data.decode()}")
    else:
        req = urllib.request.Request(f"{API}/{path}", data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"error": json.loads(e.read() or b"{}").get("error", str(e))}


def publish(video, cover, caption, graduation="MANUAL", classic=False):
    params = {
        "media_type": "REELS",
        "video_url": video,
        "caption": caption,
    }
    if classic:
        params["share_to_feed"] = "true"
    else:
        params["share_to_feed"] = "false"
        params["trial_params"] = json.dumps({"graduation_strategy": graduation})
    if cover:
        params["cover_url"] = cover
    c = call("POST", f"{IG_USER}/media", params)
    if "id" not in c:
        return {"ok": False, "step": "container", "error": c.get("error")}
    cid = c["id"]
    print(json.dumps({"containerId": cid}), file=sys.stderr, flush=True)
    for _ in range(40):  # jusqu'à ~6-7 min
        s = call("GET", cid, {"fields": "status_code,status"})
        code = s.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            return {"ok": False, "step": "processing", "error": s}
        time.sleep(10)
    else:
        return {"ok": False, "step": "processing", "error": "timeout", "containerId": cid}
    p = call("POST", f"{IG_USER}/media_publish", {"creation_id": cid})
    if "id" not in p:
        return {"ok": False, "step": "publish", "error": p.get("error"), "containerId": cid}
    m = call("GET", p["id"], {"fields": "permalink,timestamp"})
    return {"ok": True, "mediaId": p["id"], "permalink": m.get("permalink"), "timestamp": m.get("timestamp")}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--cover")
    ap.add_argument("--caption-file", required=True)
    ap.add_argument("--graduation", default="MANUAL", choices=["MANUAL", "SS_PERFORMANCE"])
    ap.add_argument("--classic", action="store_true", help="reel classique au lieu d'un trial reel")
    a = ap.parse_args()
    cap = open(a.caption_file, encoding="utf-8").read()
    res = publish(a.video, a.cover, cap, a.graduation, a.classic)
    print(json.dumps(res, ensure_ascii=False))
    sys.exit(0 if res.get("ok") else 1)
