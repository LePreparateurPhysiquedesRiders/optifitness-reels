#!/usr/bin/env python3
"""Montage type 1 Opti' FITNESS (8-9 s) : clip rider + « Rideur, Rideuse ? » + hook + voix CTA + CTA abonnement.

Usage :
  python3 render_type1.py --clip rush.mp4 --hook "Tes genoux rentrent ?\\n*C'est déjà trop tard*" \
     --cover "3 EXOS POUR *GENOUX EN BÉTON* AVANT TA SAISON" --voice voix.m4a --avatar avatar.jpg \
     --out reel.mp4 [--start 0] [--duration 8.5]
Les mots entre *étoiles* sont mis en couleur d'accent #009691.
Produit reel.mp4 (couverture intégrée) et reel_cover.jpg.
"""
import argparse, os, re, subprocess, math, json
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
W, H, FPS = 1080, 1920, 30
ACCENT = (0, 150, 145)
F = lambda w, s: ImageFont.truetype(os.path.join(HERE, f"Poppins-{w}.ttf"), s)


def ease_out_back(t):
    c1, c3 = 1.70158, 2.70158
    t = max(0.0, min(1.0, t))
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def parse_rich(line):
    """'abc *def* ghi' -> [(mot, accent?)]"""
    out = []
    for i, part in enumerate(re.split(r"\*", line)):
        for w in [x for x in part.split(" ") if x.strip()]:  # espace insécable conservée (« mot ? »)
            out.append((w, i % 2 == 1))
    return out


def wrap_rich(text, font, maxw, draw):
    lines = []
    for raw in text.split("\n"):
        words, cur = parse_rich(raw), []
        for w in words:
            test = " ".join(x for x, _ in cur + [w])
            if cur and draw.textlength(test, font=font) > maxw:
                lines.append(cur); cur = [w]
            else:
                cur.append(w)
        if cur:
            lines.append(cur)
    return lines


def draw_rich_block(img, text, font, cy, maxw, stroke, base=(255, 255, 255), lh=1.18, shadow=True):
    d = ImageDraw.Draw(img)
    lines = wrap_rich(text, font, maxw, d)
    asc = font.getbbox("Hg")[3]
    total = len(lines) * asc * lh
    y = cy - total / 2
    sp = d.textlength(" ", font=font) + stroke * 1.3
    for ln in lines:
        lw = sum(d.textlength(w, font=font) for w, _ in ln) + sp * (len(ln) - 1)
        x = (W - lw) / 2
        for w, acc in ln:
            if shadow:
                d.text((x + 3, y + 5), w, font=font, fill=(0, 0, 0, 110), stroke_width=stroke, stroke_fill=(0, 0, 0, 110))
            d.text((x, y), w, font=font, fill=ACCENT + (255,) if acc else base + (255,),
                   stroke_width=stroke, stroke_fill=(10, 20, 22, 255))
            x += d.textlength(w, font=font) + sp
        y += asc * lh
    return y


def layer(fn):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); fn(im); return im


def scaled(im, s, alpha=1.0, cx=W / 2, cy=H / 2):
    """Applique un zoom s autour de (cx,cy) et une opacité à un calque plein cadre."""
    if s <= 0.01 or alpha <= 0.01:
        return None
    if abs(s - 1) > 1e-3:
        nw, nh = int(W * s), int(H * s)
        small = im.resize((nw, nh), Image.LANCZOS)
        out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        out.paste(small, (int(cx - cx * s), int(cy - cy * s)), small)
        im = out
    if alpha < 1:
        a = im.split()[3].point(lambda v: int(v * alpha))
        im = im.copy(); im.putalpha(a)
    return im


def circle_avatar(path, size):
    av = Image.open(path).convert("RGB")
    s = min(av.size); av = av.crop(((av.width - s) // 2, (av.height - s) // 2, (av.width + s) // 2, (av.height + s) // 2))
    av = av.resize((size, size), Image.LANCZOS)
    m = Image.new("L", (size * 4, size * 4), 0); ImageDraw.Draw(m).ellipse((0, 0, size * 4, size * 4), fill=255)
    m = m.resize((size, size), Image.LANCZOS)
    ring = Image.new("RGBA", (size + 16, size + 16), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((0, 0, size + 15, size + 15), fill=(255, 255, 255, 255))
    ring.paste(av, (8, 8), m)
    return ring


def cursor_img(scale=1.0):
    s = int(64 * scale)
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    pts = [(0, 0), (0, 0.78), (0.2, 0.6), (0.34, 0.92), (0.46, 0.86), (0.32, 0.55), (0.58, 0.55)]
    P = [(4 + x * (s - 10), 4 + y * (s - 10)) for x, y in pts]
    d.polygon(P, fill=(255, 255, 255, 255), outline=(0, 0, 0, 255), width=max(2, s // 16))
    return im


def build_overlays(hook, avatar, dur):
    title = layer(lambda im: draw_rich_block(im, "Rideur, Rideuse ?", F("800", 84), 330, 980, 6,
                                             base=ACCENT, shadow=True))
    hookl = layer(lambda im: draw_rich_block(im, hook, F("700", 62), 880, 920, 5))
    av = circle_avatar(avatar, 230)
    btn_font = F("700", 46)
    cur = cursor_img(1.3)
    # Calé sur la vidéo modèle : le hook disparaît ~3,1 s avant la fin, la photo
    # et le bouton arrivent juste après, pendant que la voix CTA parle.
    t_end_text = dur - 3.1
    cta0 = dur - 2.9
    click = cta0 + 1.15
    frames = int(round(dur * FPS))
    avx, avy = 240, 860
    bx, by, bw, bh = 520, 935, 330, 96

    for i in range(frames):
        t = i / FPS
        fr = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        # Titre (calé sur la vidéo modèle) : pop-in 0,07-0,32 s avec léger rebond,
        # tenu jusqu'à ~2,55 s puis sortie fondu + montée + léger rétrécissement (0,25 s)
        t_in, t_out = 0.07, min(2.55, t_end_text)
        if t_in <= t < t_out + 0.25:
            if t < t_in + 0.25:
                u = (t - t_in) / 0.25
                s, a = 0.5 + 0.5 * ease_out_back(u), min(1, u * 2.5)
                dy = 0
            elif t < t_out:
                s, a, dy = 1.0, 1.0, 0
            else:
                u = (t - t_out) / 0.25
                s, a, dy = 1 - 0.06 * u, max(0, 1 - u), -int(18 * ease_out(u))
            im = scaled(title, s, a, cy=330)
            if im:
                fr.alpha_composite(im, (0, dy)) if dy == 0 else fr.alpha_composite(im.crop((0, -dy, W, H)), (0, 0))

        # Hook : arrive à 0,25 s (glissé + fondu)
        if 0.25 <= t < t_end_text + 0.25:
            k = ease_out((t - 0.25) / 0.3)
            a = k if t < t_end_text else max(0, 1 - (t - t_end_text) / 0.25)
            im = scaled(hookl, 0.92 + 0.08 * k, a, cy=880)
            if im: fr.alpha_composite(im)
        # CTA : photo de profil + bouton S'abonner + souris qui clique
        if t >= cta0:
            k = ease_out_back((t - cta0) / 0.4)
            sz = max(1, int(av.width * k))
            a2 = av.resize((sz, sz), Image.LANCZOS)
            fr.alpha_composite(a2, (int(avx + (av.width - sz) / 2), int(avy + (av.height - sz) / 2)))
            kb = ease_out((t - cta0 - 0.2) / 0.35)
            if kb > 0:
                d = ImageDraw.Draw(fr)
                done = t >= click
                press = 0.92 if click <= t < click + 0.12 else 1.0
                ww, hh = bw * press, bh * press
                x0 = bx + (bw - ww) / 2 + (1 - kb) * 60; y0 = by + (bh - hh) / 2
                d.rounded_rectangle((x0 + 4, y0 + 8, x0 + ww + 4, y0 + hh + 8), radius=hh / 2, fill=(0, 0, 0, int(90 * kb)))
                d.rounded_rectangle((x0, y0, x0 + ww, y0 + hh), radius=hh / 2,
                                    fill=(235, 240, 240, int(255 * kb)) if done else ACCENT + (int(255 * kb),))
                label = "Abonné" if done else "S'abonner"
                tw = d.textlength(label, font=btn_font)
                d.text((x0 + (ww - tw) / 2, y0 + hh / 2 - 31), label, font=btn_font,
                       fill=(20, 30, 32, int(255 * kb)) if done else (255, 255, 255, int(255 * kb)))
            # souris
            km = ease_out((t - cta0 - 0.35) / 0.8)
            if t >= cta0 + 0.35:
                sx, sy = 980, 1350
                tx, ty = bx + bw * 0.62, by + bh * 0.55
                cx, cy = sx + (tx - sx) * km, sy + (ty - sy) * km
                c = cur if not (click <= t < click + 0.12) else cur.resize((int(cur.width * 0.85),) * 2)
                fr.alpha_composite(c, (int(cx), int(cy)))
        yield fr


def cover(frame_path, text, out_jpg):
    bg = Image.open(frame_path).convert("RGB").resize((W, H))
    g = np.zeros((H, W), np.float32)
    ys = np.linspace(0, 1, H)[:, None]
    g[:] = np.clip(1 - np.abs(ys - 0.5) / 0.42, 0, 1) * 0.62
    dark = Image.fromarray((g * 255).astype(np.uint8))
    bg = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), bg, dark).convert("RGBA")
    txt = text.upper()
    size = 104
    while size > 60:
        f = F("800", size)
        d = ImageDraw.Draw(bg)
        if len(wrap_rich(txt, f, 940, d)) <= 5: break
        size -= 6
    draw_rich_block(bg, txt, F("800", size), H / 2, 940, 8)
    bg.convert("RGB").save(out_jpg, quality=92)


def probe_dur(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", p], capture_output=True, text=True)
    return float(json.loads(r.stdout)["format"]["duration"])


def has_audio(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", p], capture_output=True, text=True)
    return bool(r.stdout.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", required=True); ap.add_argument("--hook", required=True)
    ap.add_argument("--cover", required=True); ap.add_argument("--voice", required=True)
    ap.add_argument("--avatar", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--start", type=float, default=0.0); ap.add_argument("--duration", type=float, default=8.5)
    ap.add_argument("--voice_at", type=float, default=None)
    ap.add_argument("--bg", default=None, help="son d'ambiance si le rush n'a pas d'audio")
    a = ap.parse_args()
    a.hook = a.hook.replace("\\n", "\n"); a.cover = a.cover.replace("\\n", "\n")
    dur = a.duration
    tmp = a.out + ".tmp"; os.makedirs(tmp, exist_ok=True)
    loop = ["-stream_loop", "-1"] if probe_dur(a.clip) - a.start < dur else []

    # 1) base vidéo 1080x1920, couleurs naturelles légèrement relevées
    base = os.path.join(tmp, "base.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", *loop, "-ss", str(a.start), "-i", a.clip, "-t", str(dur),
                    "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},eq=saturation=1.06:contrast=1.03,format=yuv420p",
                    "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", base], check=True)

    # 2) couverture : image la plus nette parmi 8 candidates
    best, bscore = None, -1
    for k in range(8):
        fp = os.path.join(tmp, f"c{k}.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(dur * (k + 0.5) / 8), "-i", base, "-frames:v", "1", fp], check=True)
        im = np.asarray(Image.open(fp).convert("L").filter(ImageFilter.FIND_EDGES), np.float32)
        if im.var() > bscore: best, bscore = fp, im.var()
    cover_jpg = os.path.splitext(a.out)[0] + "_cover.jpg"
    cover(best, a.cover, cover_jpg)

    # 3) calques animés envoyés en flux brut à ffmpeg
    over = os.path.join(tmp, "over.mov")
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}", "-r", str(FPS),
                          "-i", "-", "-c:v", "qtrle", over], stdin=subprocess.PIPE)
    for fr in build_overlays(a.hook, a.avatar, dur):
        p.stdin.write(fr.tobytes())
    p.stdin.close(); p.wait()

    # 4) audio : voix CTA + son d'origine discret, normalisé ~ -14 LUFS
    vdur = probe_dur(a.voice)
    # la voix CTA se termine ~0,15 s avant la fin (comme sur la vidéo modèle)
    vat = a.voice_at if a.voice_at is not None else max(1.2, dur - vdur - 0.15)
    inputs = ["-i", base, "-i", over, "-i", a.voice]
    bg_src = a.clip if has_audio(a.clip) else (a.bg if a.bg and os.path.exists(a.bg) else None)
    if bg_src:
        # son d'ambiance du rush pendant toute la vidéo, baissé (ducking) sous la voix
        inputs += [*(loop if bg_src == a.clip else ["-stream_loop", "-1"]), "-ss", str(a.start if bg_src == a.clip else 0), "-i", bg_src]
        v0, v1 = vat - 0.25, vat + vdur + 0.1
        amix = (f"[2:a]aformat=channel_layouts=stereo,adelay={int(vat*1000)}|{int(vat*1000)},volume=1.0[v];"
                f"[3:a]aformat=channel_layouts=stereo,atrim=0:{dur},asetpts=N/SR/TB,"
                f"volume='if(between(t,{v0:.2f},{v1:.2f}),0.12,0.45)':eval=frame[bg];"
                f"[v][bg]amix=inputs=2:duration=longest:normalize=0,")
    else:
        amix = f"[2:a]aformat=channel_layouts=stereo,adelay={int(vat*1000)}|{int(vat*1000)},"
    fc = (f"[0:v][1:v]overlay=0:0:format=auto,format=yuv420p[vout];"
          f"{amix}apad,atrim=0:{dur},loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[aout]")
    noc = os.path.join(tmp, "nocover.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", fc, "-map", "[vout]", "-map", "[aout]",
                    "-t", str(dur), "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-profile:v", "high",
                    "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", noc], check=True)
    # 5) couverture intégrée comme miniature du MP4
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", noc, "-i", cover_jpg, "-map", "0", "-map", "1", "-c", "copy",
                    "-c:v:1", "mjpeg", "-disposition:v:1", "attached_pic", "-movflags", "+faststart", a.out], check=True)
    subprocess.run(["rm", "-rf", tmp])
    print(json.dumps({"video": a.out, "cover": cover_jpg, "voice_at": round(vat, 2)}))


if __name__ == "__main__":
    main()
