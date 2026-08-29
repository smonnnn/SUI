#!/usr/bin/env python3
"""Generate procedural media assets for the SUI demo.

Creates:
  assets/logo.png                 static texture (gradient emblem)
  assets/anim/frame_%02d.gif.gif  a looping animated equalizer (24 frames)
  assets/video/frame_%04d.png     a longer, video-like frame sequence (60 frames)

Run once before launching the demo (the demo layout references these paths).
"""
import os, math, shutil, subprocess
import pyray as r

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(HERE, "examples", "assets")
ANIM_DIR = os.path.join(ASSETS_DIR, "anim")
VIDEO_DIR = os.path.join(ASSETS_DIR, "video")

r.set_trace_log_level(4)  # silence INFO logs

def mix(a, b, t):
    return r.Color(int(a.r + (b.r - a.r) * t),
                   int(a.g + (b.g - a.g) * t),
                   int(a.b + (b.b - a.b) * t),
                   int(a.a + (b.a - a.a) * t))

def make_logo(size=256):
    top = r.Color(0, 34, 34, 255)
    bottom = r.Color(237, 163, 90, 255)
    img = r.gen_image_gradient_linear(size, size, 0, top, bottom)
    # emblem ring
    c = size // 2
    r.image_draw_circle(img, c, c, int(size * 0.36), r.Color(20, 40, 40, 255))
    r.image_draw_circle(img, c, c, int(size * 0.30), r.Color(225, 233, 201, 255))
    for i in range(8):
        ang = i * math.pi / 4
        x = c + int(math.cos(ang) * size * 0.18)
        y = c + int(math.sin(ang) * size * 0.18)
        r.image_draw_circle(img, x, y, int(size * 0.07), r.Color(237, 163, 90, 255))
    r.image_draw_circle(img, c, c, int(size * 0.07), r.Color(0, 34, 34, 255))
    return img

def make_equalizer_frame(w, h, t, bars):
    img = r.gen_image_color(w, h, r.Color(0, 34, 34, 255))
    for i in range(bars):
        bx = int((i + 0.5) * w / bars) - int((w / bars) * 0.25)
        bw = max(2, int((w / bars) * 0.5))
        amp = (math.sin(t * 2.0 + i * 0.9) + 1.0) / 2.0
        bh = int((0.15 + 0.8 * amp) * h)
        r.image_draw_rectangle(img, bx, h - bh, bw, bh, r.Color(254, 232, 217, 255))
        r.image_draw_rectangle(img, bx, h - bh - 3, bw, 3, r.Color(237, 163, 90, 255))
    return img

def video_frame(w, h, t):
    a = r.Color(20, 40, 40, 255)
    b = r.Color(237, 163, 90, 255)
    c = r.Color(254, 232, 217, 255)
    img = r.gen_image_gradient_linear(w, h, 0, a, b)
    cx = w * (0.5 + 0.35 * math.sin(t))
    cy = h * (0.5 + 0.2 * math.cos(t * 1.3))
    r.image_draw_circle(img, int(cx), int(cy), int(h * 0.35), mix(c, a, 0.35))
    for i in range(6):
        ang = t * 2 + i * math.pi / 3
        x = int(cx + math.cos(ang) * h * 0.5)
        y = int(cy + math.sin(ang) * h * 0.5)
        r.image_draw_circle(img, x, y, int(h * 0.08), c)
    return img

def _ffmpeg():
    """Locate a usable ffmpeg binary (system ffmpeg, else the bundled one)."""
    exe = os.environ.get("SUI_FFMPEG") or os.environ.get("IMAGEIO_FFMPEG_EXE")
    if exe and os.path.exists(exe):
        return exe
    fd = shutil.which("ffmpeg")
    if fd:
        return fd
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    return None

def _encode_video():
    """Encode the generated video frames into a real H.264 .mp4."""
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        print("ffmpeg not found; skipping video.mp4 (frame fallback still works)")
        return
    out = os.path.join(ASSETS_DIR, "video.mp4")
    src = os.path.join(VIDEO_DIR, "frame_%04d.png")
    cmd = [ffmpeg, "-y", "-framerate", "30", "-i", src,
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
    subprocess.run(cmd, check=False, capture_output=True)
    if os.path.exists(out):
        print("video encoded ->", out)
    else:
        print("video encode failed; frame fallback still works")

def main():
    os.makedirs(ANIM_DIR, exist_ok=True)
    os.makedirs(VIDEO_DIR, exist_ok=True)

    logo = make_logo()
    r.export_image(logo, os.path.join(ASSETS_DIR, "logo.png"))
    r.unload_image(logo)

    n = 24
    for i in range(n):
        t = i / n * math.tau
        img = make_equalizer_frame(320, 120, t, 12)
        r.export_image(img, os.path.join(ANIM_DIR, f"frame_{i:02d}.png"))
        r.unload_image(img)

    n = 60
    for i in range(n):
        t = i / n * math.tau
        img = video_frame(480, 240, t)
        r.export_image(img, os.path.join(VIDEO_DIR, f"frame_{i:04d}.png"))
        r.unload_image(img)

    _encode_video()
    print("assets generated")

if __name__ == "__main__":
    main()
