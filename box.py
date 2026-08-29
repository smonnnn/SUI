from __future__ import annotations
from pyray import *
from typing import Optional, List, Dict, Any
from dataclasses import field, dataclass
import glob, sys, time, os, re, shutil, subprocess, threading
import pyray as _pr
from parser import parse

# ---------------------------------------------------------------------------
# Globals / palette
# ---------------------------------------------------------------------------
BASE_FONT_SIZE = 32
BACKGROUND = Color(202, 220, 174, 255)
FOREGROUND = Color(225, 233, 201, 255)
BUTTON = Color(237, 163, 90, 255)
BUTTON_H = Color(254, 232, 217, 255)
BORDER = Color(0, 34, 34, 255)
TEXT = BLACK
SCROLLBAR_W = 8.0

hovering = None
selected = None
_SCROLL_TARGET = None

_ROOT = None
_BOXES = None
_LAYOUT_FILE = None
_LAYOUT_DIR = None
_RELOAD_REQUEST = threading.Event()


def _resolve_media(path):
    """Resolve a media path relative to the layout file's directory."""
    if not path or os.path.isabs(path) or '{' in path or '*' in path:
        return path
    d = _LAYOUT_DIR or os.getcwd()
    cand = os.path.normpath(os.path.join(d, path))
    return cand if os.path.exists(cand) else path

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Media: static textures, animated images and ffmpeg-decoded video.
# ---------------------------------------------------------------------------
class _StreamPlayer:
    """Threaded ffmpeg decoder: streams RGBA video frames + optional PCM audio."""

    def __init__(self, path, ffmpeg, meta):
        self.path = path
        self.ffmpeg = ffmpeg
        self.width = meta["width"]
        self.height = meta["height"]
        self.fps = meta["fps"] or 24
        self.frame_dur = 1.0 / self.fps
        self.duration = meta["duration"] or 0.0
        self.loop = True
        self.has_audio = meta["has_audio"]
        self._rate = meta["audio_rate"] or 44100
        self._channels = meta["audio_channels"] or 2
        self._bpf = 4 * self._channels   # float32 stereo/mono bytes per sample-frame

        self._lock = threading.Lock()
        self._frame = None
        self._frame_new = False
        self._pos = 0.0
        self._playing = False
        self._volume = 1.0
        self._seek = None
        self._stop = threading.Event()
        self._vproc = None
        self._aproc = None
        self._frames_read = 0
        self._last_t = 0.0
        self._base = 0.0
        self._audio_stream = None
        self._audio_thread = None
        self._audio_buf = bytearray()
        self._throttle = 0.0
        self._audio_cb = _pr.ffi.callback("void(void *, unsigned int)")(self._fill_audio)
        self._thread = threading.Thread(target=self._run, daemon=True)

    # ---- public controls (call from the UI / render thread) ----
    def start(self):
        if self._playing:
            return
        self._playing = True
        self._start_procs(self._pos)
        self._thread.start()
        if self.has_audio:
            self._audio_thread = threading.Thread(target=self._audio_loop, daemon=True)
            self._audio_thread.start()

    def play(self):
        self._playing = True
        if self.has_audio and self._playing:
            try:
                resume_audio_stream(self._audio_stream)
            except Exception:
                pass

    def pause(self):
        self._playing = False
        if self.has_audio:
            try:
                pause_audio_stream(self._audio_stream)
            except Exception:
                pass

    def seek(self, t):
        with self._lock:
            self._seek = max(0.0, float(t))

    def set_volume(self, v):
        self._volume = max(0.0, min(1.0, float(v)))
        if self.has_audio and self._audio_stream is not None:
            try:
                set_audio_stream_volume(self._audio_stream, self._volume)
            except Exception:
                pass

    def _fill_audio(self, buf, frames):
        """raylib audio callback: copy decoded float32 PCM into the stream
        buffer. Runs on the miniaudio thread; fills the remainder with silence."""
        need = frames * self._channels * 4
        with self._lock:
            data = bytes(self._audio_buf[:need])
            del self._audio_buf[:need]
        n = len(data)
        if n:
            try:
                _pr.ffi.memmove(buf, _pr.ffi.from_buffer(data), n)
            except Exception:
                n = 0
        if n < need:
            try:
                _pr.ffi.memset(_pr.ffi.cast("char *", buf) + n, 0, need - n)
            except Exception:
                pass

    def position(self):
        return self._pos

    def stop(self):
        self._stop.set()
        self._playing = False
        self._kill()

    # ---- render-thread hooks ----
    def take_frame(self):
        with self._lock:
            frame = self._frame
            new = self._frame_new
            self._frame_new = False
        return frame, new

    def unload(self):
        self._stop.set()
        self._kill()
        if self._thread.is_alive():
            self._thread.join(timeout=0.5)
        if self._audio_thread is not None and self._audio_thread.is_alive():
            self._audio_thread.join(timeout=0.5)
        if self._audio_stream is not None:
            try:
                stop_audio_stream(self._audio_stream)
            except Exception:
                pass
            try:
                unload_audio_stream(self._audio_stream)
            except Exception:
                pass
            self._audio_stream = None

    # ---- internals ----
    def _kill(self):
        for p in (self._vproc, self._aproc):
            if p is not None:
                try:
                    p.kill()
                except Exception:
                    pass
        self._vproc = None
        self._aproc = None

    def _start_procs(self, start):
        self._kill()
        self._frames_read = 0
        self._last_t = 0.0
        self._base = start
        with self._lock:
            self._pos = start
            self._audio_buf.clear()
            self._last_feed = time.time()
        self._vproc = subprocess.Popen(
            [self.ffmpeg, "-v", "error", "-ss", f"{start:.3f}", "-i", self.path,
             "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        if self.has_audio:
            self._aproc = subprocess.Popen(
                [self.ffmpeg, "-v", "error", "-re", "-ss", f"{start:.3f}", "-i", self.path,
                 "-vn", "-f", "f32le", "-ac", str(self._channels), "-ar", str(self._rate), "-"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def _read_exact(self, f, n):
        out = bytearray()
        while len(out) < n:
            b = f.read(n - len(out))
            if not b:
                return None
            out.extend(b)
        return bytes(out)

    def _run(self):
        need = self.width * self.height * 4
        while not self._stop.is_set():
            with self._lock:
                seek = self._seek
                self._seek = None
            if seek is not None and not self._playing:
                # remember the seek until playback resumes
                time.sleep(0.004)
                continue
            if seek is not None:
                self._start_procs(seek)
            if not self._playing:
                time.sleep(0.004)
                continue
            if self._vproc is None or self._vproc.poll() is not None:
                if self.loop:
                    self._start_procs(0.0)
                else:
                    self._playing = False
                    with self._lock:
                        self._pos = 0.0
                    continue
            data = self._read_exact(self._vproc.stdout, need)
            if data is None:
                if self.loop:
                    self._start_procs(0.0)
                else:
                    self._playing = False
                    with self._lock:
                        self._pos = 0.0
                    continue
            with self._lock:
                self._frame = data
                self._frame_new = True
            self._frames_read += 1
            with self._lock:
                self._pos = self._base + self._frames_read * self.frame_dur
            now = time.time()
            if self._last_t:
                dt = now - self._last_t
                if dt < self.frame_dur:
                    time.sleep(self.frame_dur - dt)
            self._last_t = time.time()

    def _audio_loop(self):
        # Decode PCM only and buffer it; never call raylib from this thread.
        maxbuf = int(self._rate * self._bpf * 0.5)      # keep ~0.5s buffered
        chunk = 512 * self._bpf
        while not self._stop.is_set():
            if not self._playing:
                time.sleep(0.004)
                continue
            aproc = self._aproc
            if aproc is None or aproc.poll() is not None:
                # video thread may be mid-seek/loop restarting the procs
                time.sleep(0.004)
                continue
            with self._lock:
                if len(self._audio_buf) >= maxbuf:
                    time.sleep(0.004)
                    continue
            data = aproc.stdout.read(chunk)
            if not data:
                if self.loop:
                    time.sleep(0.02)
                    continue
                return
            with self._lock:
                self._audio_buf.extend(data)


class Media:
    def __init__(self, kind, textures, fps=24, loop=True, player=None, size=None):
        self.kind = kind       # 'texture' | 'anim' | 'video'
        self.textures = textures
        self.fps = max(1, fps)
        self.loop = loop
        self.start = time.time()
        self._index = -1
        self.player = player          # _StreamPlayer for streamed video
        self._size = size

    def current(self):
        # ---- streamed video: upload the latest decoded frame ----
        if self.player is not None:
            frame, new = self.player.take_frame()
            if new and frame:
                buf = _pr.ffi.cast("void*", _pr.ffi.from_buffer(frame))
                update_texture(self.textures[0], buf)
            return self.textures[0]

        # ---- texture / frame-array animation ----
        if self.kind == 'texture' or len(self.textures) <= 1:
            return self.textures[0]
        idx = int((time.time() - self.start) * self.fps) % len(self.textures)
        self._index = idx
        return self.textures[idx]

    @property
    def active(self):
        return bool(self.textures) and self.textures[0].id != 0

    def frame_size(self):
        if self._size:
            return self._size
        t = self.textures[0]
        return t.width, t.height

    # ---- playback controls exposed to the UI ----
    def play(self):
        if self.player:
            self.player.play()
    def pause(self):
        if self.player:
            self.player.pause()
    def toggle(self):
        if self.player:
            if self.player._playing:
                self.player.pause()
            else:
                self.player.play()
    def seek(self, t):
        if self.player:
            self.player.seek(t)
    @property
    def position(self):
        return self.player.position() if self.player else 0.0
    @property
    def duration(self):
        return self.player.duration if self.player else 0.0
    @property
    def playing(self):
        return bool(self.player and self.player._playing)
    def set_volume(self, v):
        if self.player:
            self.player.set_volume(v)

    def unload(self):
        if self.player is not None:
            self.player.unload()
            self.player = None
        for t in self.textures:
            try:
                unload_texture(t)
            except Exception:
                pass
        self.textures = []


def _find_ffmpeg():
    """Locate a working ffmpeg binary. Prefer the system one, then the
    bundled static binary from imageio-ffmpeg (fallback)."""
    exe = os.environ.get("SUI_FFMPEG") or os.environ.get("IMAGEIO_FFMPEG_EXE")
    if exe and os.path.exists(exe):
        return exe
    fd = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if fd:
        return fd
    try:
        import imageio_ffmpeg  # bundled static binary (last resort)
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    return None


_VIDEO_EXTS = (".mp4", ".m4v", ".avi", ".mov", ".webm", ".mkv", ".mpg", ".mpeg",
               ".wmv", ".flv", ".ts", ".3gp", ".gif", ".ogv")

def _is_video_file(path):
    if os.path.isdir(path) or any(ch in path for ch in "*?["):
        return False
    return os.path.splitext(path)[1].lower() in _VIDEO_EXTS


def _video_meta(path, ffmpeg):
    """Return (width, height, fps, frame_count) hints by parsing ``ffmpeg -i``."""
    try:
        out = subprocess.run([ffmpeg, "-i", path], capture_output=True, text=True,
                             timeout=20).stderr
    except Exception:
        return None
    m = re.search(r",\s*(\d{2,5})x(\d{2,5})", out)
    height = width = 0
    if m:
        width, height = int(m.group(1)), int(m.group(2))
    fps = 0.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*fps", out)
    if m:
        fps = float(m.group(1))
    duration = 0.0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", out)
    if m:
        duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    if width and height:
        count = int(round(duration * fps)) if (duration and fps) else 0
        return width, height, fps, count
    return None


def _probe_video(path, ffmpeg):
    """Probe a video's metadata (+ audio presence) via ``ffmpeg -i``."""
    try:
        out = subprocess.run([ffmpeg, "-i", path], capture_output=True, text=True,
                             timeout=20).stderr
    except Exception:
        return None
    meta = {}
    m = re.search(r",\s*(\d{2,5})x(\d{2,5})", out)
    meta["width"] = int(m.group(1)) if m else 0
    meta["height"] = int(m.group(2)) if m else 0
    m = re.search(r"(\d+(?:\.\d+)?)\s*fps", out)
    meta["fps"] = float(m.group(1)) if m else 0
    duration = 0.0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", out)
    if m:
        duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    meta["duration"] = duration
    m = re.search(r"Audio:\s*(.*)", out)
    if m:
        meta["has_audio"] = True
        ar = re.search(r"(\d+)\s*Hz", m.group(1))
        meta["audio_rate"] = int(ar.group(1)) if ar else 44100
        ch = re.search(r"\b(stereo|mono|5\.1|7\.1)\b", m.group(1))
        meta["audio_channels"] = 2 if (ch and ch.group(1) == "stereo") else (1 if (ch and ch.group(1) == "mono") else 2)
    else:
        meta["has_audio"] = False
        meta["audio_rate"] = 44100
        meta["audio_channels"] = 2
    if meta["width"] and meta["height"]:
        return meta
    return None


class MediaDB:
    """Loads and caches media by descriptor so several boxes can share one."""
    def __init__(self):
        self._cache = {}
        self._spawned = []

    def _resolve_frames(self, path):
        if os.path.isdir(path):
            files = sorted(glob.glob(os.path.join(path, "*")))
        elif any(ch in path for ch in "*?["):
            files = sorted(glob.glob(path))
        elif os.path.exists(path):
            files = [path]
        else:
            files = []
        return [f for f in files if os.path.isfile(f)]

    def get(self, kind, path, fps=24):
        key = (kind, path, fps)
        if key in self._cache:
            return self._cache[key]
        med = None
        if kind == 'texture' and os.path.exists(path) and '*' not in path:
            med = Media('texture', [load_texture(path)], fps, True)
        elif kind == 'video' and _is_video_file(path):
            med = self._make_video(path, fps)
            if med is None:
                frames = [load_texture(f) for f in self._resolve_frames(path)]
                med = Media('video', frames, fps, True) if frames else None
        else:
            frames = [load_texture(f) for f in self._resolve_frames(path)]
            med = Media(kind, frames, fps, True) if frames else None
        if med:
            self._cache[key] = med
        return med

    def spawn_video(self, path, fps=0):
        """Load an uncached, streamed video and register it for cleanup."""
        med = self._make_video(path, fps)
        if med:
            self._spawned.append(med)
        return med

    def _make_video(self, path, fps_hint=0):
        ffmpeg = _find_ffmpeg()
        if not ffmpeg:
            return None
        meta = _probe_video(path, ffmpeg)
        if not meta:
            return None
        if fps_hint:
            meta["fps"] = fps_hint
        want_audio = meta["has_audio"]
        meta["has_audio"] = False
        if want_audio:
            try:
                if not is_audio_device_ready():
                    init_audio_device()
                meta["has_audio"] = True
            except Exception:
                meta["has_audio"] = False
        img = gen_image_color(meta["width"], meta["height"], (0, 0, 0, 255))
        tex = load_texture_from_image(img)
        unload_image(img)
        player = _StreamPlayer(path, ffmpeg, meta)
        if meta["has_audio"]:
            try:
                ok_audio = True
                try:
                    ok_audio = is_audio_device_ready()
                except Exception:
                    ok_audio = True
                if ok_audio:
                    s = load_audio_stream(player._rate, 512, player._channels)
                    if is_audio_stream_valid(s):
                        set_audio_stream_callback(s, player._audio_cb)
                        player._audio_stream = s
                        play_audio_stream(s)
                        set_audio_stream_volume(s, 1.0)
                    else:
                        player.has_audio = False
                else:
                    player.has_audio = False
            except Exception:
                player.has_audio = False
                player._audio_stream = None
        med = Media('video', [tex], meta["fps"], True, player=player, size=(meta["width"], meta["height"]))
        player.start()
        return med

    def unload_all(self):
        for med in self._cache.values():
            med.unload()
        for med in self._spawned:
            med.unload()
        self._cache.clear()
        self._spawned.clear()

    def _ref_keys(self, boxes_dict):
        """Media keys still referenced by the (new) layout, matching dict_to_box."""
        refs = set()
        for d in boxes_dict.values():
            if d.get('texture'):
                refs.add(('texture', d['texture'], 24))
            if d.get('anim'):
                refs.add(('anim', d['anim'], d.get('anim_fps', 8)))
            if d.get('video'):
                refs.add(('video', d['video'], d.get('video_fps', 24)))
        return refs

    def keep_referenced(self, boxes_dict):
        """Destroy media no longer referenced by the (new) layout, keeping the
        rest so their textures/audio streams are re-attached on reload.
        Returns True if any audio stream was destroyed."""
        refs = self._ref_keys(boxes_dict)
        destroyed_audio = False
        for key in list(self._cache.keys()):
            if key not in refs:
                med = self._cache.pop(key)
                if med.player and med.player.has_audio:
                    destroyed_audio = True
                med.unload()
        for med in self._spawned:
            if med.player and med.player.has_audio:
                destroyed_audio = True
            med.unload()
        self._spawned.clear()
        return destroyed_audio


MEDIA = MediaDB()

# ---------------------------------------------------------------------------
# Box
# ---------------------------------------------------------------------------
@dataclass
class Box:
    text: str = ""
    name: str = ""
    rect: Rectangle = field(default_factory=lambda: Rectangle(0, 0, 0, 0))
    color: Optional[Color] = None
    border_color: Optional[Color] = BORDER
    hover_color: Optional[Color] = None
    selected_color: Optional[Color] = None
    text_color: Optional[Color] = BLACK
    strength: int = 100
    hidden: bool = False
    vertical: bool = False          # False = horizontal, True = vertical.
    padding: Vector4 = field(default_factory=lambda: Vector4(0, 0, 0, 0))  # l,r,t,b
    margin: Vector4 = field(default_factory=lambda: Vector4(1, 1, 1, 1))    # l,r,t,b
    border: Vector4 = field(default_factory=lambda: Vector4(0, 0, 0, 0))    # l,r,t,b
    radius: float = 0.0              # corner radius
    segments: int = 8                # rounded-rect segments
    align_x: str = "left"            # left | center | right
    align_y: str = "top"             # top | center | bottom
    scroll: bool = False             # scrollable container
    scroll_offset: Vector2 = field(default_factory=lambda: Vector2(0, 0))
    scroll_speed: float = 60.0
    content_extent: float = 0.0      # natural content length along scroll axis
    size: Vector2 = field(default_factory=lambda: Vector2(0, 0))  # 0 = auto
    onclick: Any = field(default_factory=lambda: (lambda: False))
    onhover: Any = field(default_factory=lambda: (lambda: False))
    parent: Optional[Box] = None
    children: List[Box] = field(default_factory=list)
    texture_fit: str = "stretch"     # stretch | contain | cover | tile | crop
    texture: Texture = None
    shader: str = ""                 # fragment-shader file rendered to a texture
    script: str = ""                 # inline python executed every frame
    functions: dict = field(default_factory=lambda: {})
    _media: Media = None
    _desired: Vector2 = field(default_factory=lambda: Vector2(0, 0))

    @property
    def media(self):
        """The (optional) media/player attached to this box, for UI control."""
        return self._media


# ---- media/playback helpers available to layout callbacks and calc() ----
def media_play(box):
    m = box.media
    if m:
        m.play()
    return True

def media_pause(box):
    m = box.media
    if m:
        m.pause()
    return True

def media_toggle(box):
    m = box.media
    if m:
        m.toggle()
    return True

def media_seek(box, t):
    m = box.media
    if m:
        m.seek(float(t))
    return True

def media_seek_click(box, target):
    """Seek `target`'s media to the fraction of the scrub-bar `box` clicked."""
    m = target.media
    if m and box.rect.width > 0:
        mx = get_mouse_position().x
        frac = (mx - box.rect.x) / box.rect.width
        m.seek(max(0.0, min(1.0, frac)) * m.duration)
    return True

def media_pos(box):
    m = box.media
    return m.position if m else 0.0

def media_dur(box):
    m = box.media
    return m.duration if m else 0.0

def media_playing(box):
    m = box.media
    return bool(m and m.playing)

def media_vol(box, v):
    m = box.media
    if m:
        m.set_volume(float(v))
    return True

def media_vol_toggle(box):
    m = box.media
    if m:
        m.set_volume(0.0 if m.player._volume > 0.0 else 1.0)
    return True

_scrub_last = {}

def media_scrub_drag(box, target):
    """While dragging over scrub-bar `box`, throttle-seek `target`'s media."""
    m = target.media
    if not m or box.rect.width <= 0:
        return True
    mp = get_mouse_position()
    if not (box.rect.x <= mp.x <= box.rect.x + box.rect.width and
            box.rect.y <= mp.y <= box.rect.y + box.rect.height):
        return True
    if not is_mouse_button_down(MouseButton.MOUSE_BUTTON_LEFT):
        return True
    frac = max(0.0, min(1.0, (mp.x - box.rect.x) / box.rect.width))
    now = time.time()
    if now - _scrub_last.get(id(box), 0.0) < 0.10:
        return True
    _scrub_last[id(box)] = now
    want = frac * m.duration
    if abs(want - m.position) > 0.05:
        m.seek(want)
    return True

def open_file_dialog():
    """Open a native file picker (tkinter), returning a path or None."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            title="Open video",
            filetypes=[("Videos", "*.mp4 *.avi *.mov *.mkv *.webm *.m4v *.wmv *.gif *.ogv"),
                       ("All files", "*.*")])
        root.destroy()
        return path or None
    except Exception as e:
        print("[SUI] file dialog unavailable:", e)
        return None

def load_video_into(box, path, fps=0):
    """Swap a box's video for the one at `path` (streams via ffmpeg)."""
    path = _resolve_media(path)
    if not path or not (os.path.exists(path) and _is_video_file(path)):
        return False
    try:
        med = MEDIA.spawn_video(path, fps)
    except Exception as e:
        print("[SUI] failed to load:", path, e)
        return False
    if med is None:
        return False
    old = box._media
    if old is med:
        return True
    box._media = med
    if old is not None:
        old.unload()
    return True

def media_open(box, target=None):
    """Queue a file-picker to run after the current frame (tkinter can't
    run inside a raylib drawing frame without breaking GLFW)."""
    global _PENDING_OPEN
    _PENDING_OPEN = box
    return True

_PENDING_OPEN = None

def _run_pending_open():
    global _PENDING_OPEN
    if _PENDING_OPEN is None:
        return
    box = _PENDING_OPEN
    _PENDING_OPEN = None
    try:
        path = open_file_dialog()
        if path:
            load_video_into(box, path)
    except Exception as e:
        print("[SUI] open failed:", e)


def add_children(parent, *children):
    for child in children:
        parent.children.append(child)
        child.parent = parent

def set_children(parent, *children):
    for child in parent.children:
        child.parent = None
    parent.children = []
    for child in children:
        parent.children.append(child)
        child.parent = parent

def apply(box: Box, functions):
    for fn in functions:
        fn(box)
    for c in box.children:
        apply(c, functions)

def is_visible(box):
    h = box.hidden
    if isinstance(h, str):
        try:
            return not eval(h, _eval_globals())
        except Exception:
            return True
    return not bool(h)

def _eval_globals():
    return _EVAL

# ---------------------------------------------------------------------------
# Text wrapping (kept from original, made tolerance aware)
# ---------------------------------------------------------------------------
def wrap_text(text, font, font_size, spacing, max_width, max_height, shrink_font=True):
    original_text = text
    wrap_chars = [" ", ".", "-"]
    while True:
        text = original_text
        lines = []
        while text:
            nlpos = len(text)
            while nlpos > 0:
                t = text[:nlpos]
                text_size = measure_text_ex(font, t, font_size, spacing)
                if text_size.x < max_width:
                    break
                nlpos -= 1
            if nlpos == 0:
                nlpos = 1
            wrap_pos = nlpos
            if nlpos < len(text) and nlpos > 1:
                for i, c in enumerate(reversed(text[:nlpos])):
                    if c in wrap_chars:
                        wrap_pos = nlpos - i
                        break
            lines.append(text[:wrap_pos])
            text = text[wrap_pos:].lstrip()
        wrapped_text = "\n".join(lines)
        text_size = measure_text_ex(font, wrapped_text, font_size, spacing)
        longest_word = max(
            (measure_text_ex(font, w, font_size, spacing).x
             for w in original_text.replace("-", " ").split()),
            default=0.0)
        # shrink when too tall, or when the longest word can't fit on one line
        fits_height = text_size.y <= max_height
        fits_width = longest_word <= max_width
        if (fits_height and fits_width) or font_size <= 1 or not shrink_font:
            return (wrapped_text, font_size)
        font_size -= 1


FONT = None
SPACING = 2.5
_FONT_SIZE = 48

def _find_font():
    candidates = [
        "/usr/share/fonts/Fira_Sans/FiraSans-Regular.ttf",
        "/usr/share/fonts/Adwaita/AdwaitaSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/cantarell/Cantarell-Regular.ttf",
        "/usr/share/fonts/noto/NotoSans-Regular.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/segoeui.ttf",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    for pat in ("/usr/share/fonts/**/Fira*.ttf", "/usr/share/fonts/**/DejaVu*.ttf",
                "/usr/share/fonts/**/*Sans-Regular.ttf", "/usr/share/fonts/**/*Sans*.ttf"):
        hits = glob.glob(pat, recursive=True)
        if hits:
            return hits[0]
    return None

def _get_font():
    global FONT
    if FONT is None:
        path = _find_font()
        try:
            FONT = load_font_ex(path, _FONT_SIZE, _pr.ffi.NULL, 0)
            set_texture_filter(FONT.texture, TextureFilter.TEXTURE_FILTER_BILINEAR)
        except Exception:
            FONT = get_font_default()
    return FONT


# ---------------------------------------------------------------------------
# Script/expression evaluation with a rich namespace
# ---------------------------------------------------------------------------
_EVAL: Dict[str, Any] = {}

def _refresh_ctx():
    try:
        _EVAL.update({
            "mouse": get_mouse_position(),
            "time": time.time(),
            "width": get_screen_width(),
            "height": get_screen_height(),
            "ratio": get_screen_width() / max(1, get_screen_height()),
        })
    except Exception:
        pass

def eval_in(box, expr):
    _refresh_ctx()
    _EVAL["box"] = box
    try:
        return eval(expr, _EVAL, _EVAL)
    except Exception as e:
        print(f"[SUI] eval error in {box.name or box.text!r}: {e}")
        return None

def script_run(box):
    if not box.script:
        return
    _refresh_ctx()
    _EVAL["box"] = box
    try:
        exec(box.script, _EVAL, _EVAL)
    except Exception as e:
        print(f"[SUI] script error in {box.name or box.text!r}: {e}")

def apply_functions(box: Box):
    for fnname, expr in box.functions.items():
        value = eval_in(box, expr)
        name = fnname
        if fnname == "click":
            name = "onclick"
        elif fnname == "hover":
            name = "onhover"
        elif fnname == "horizontal":
            name = "vertical"
            value = not value
        elif fnname in ("padding", "margin", "border"):
            value = parse_vector4(value)
        elif fnname == "align_x":
            value = str(value)
        elif fnname == "align_y":
            value = str(value)
        elif fnname == "text":
            value = str(value)
        try:
            setattr(box, name, value)
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Value parsers
# ---------------------------------------------------------------------------
def parse_color(value):
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        if len(value) >= 4:
            return Color(value[0], value[1], value[2], value[3])
        if len(value) == 3:
            return Color(value[0], value[1], value[2], 255)
    return None

def parse_vector4(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return Vector4(value, value, value, value)
    if isinstance(value, (list, tuple)) and len(value) == 4:
        return Vector4(value[0], value[1], value[2], value[3])
    return None


# ---------------------------------------------------------------------------
# Natural-size measurement (for scroll containers)
# ---------------------------------------------------------------------------
def _text_block(box, width, height=100000):
    if not box.text:
        return "", BASE_FONT_SIZE, 0, 0
    # Per-(width,height) cache so the natural-size (measure) and fit-height
    # (draw) wrappings don't clobber each other (which caused per-frame misses).
    d = getattr(box, "_tbc", None)
    if d is None:
        d = {}
        box._tbc = d
    key = (round(width), round(height))
    hit = d.get(key)
    if hit is not None and hit[0] == box.text:
        return hit[1], hit[2], hit[3], hit[4]
    wrapped, fs = wrap_text(box.text, _get_font(), BASE_FONT_SIZE, SPACING, width, height)
    sz = measure_text_ex(_get_font(), wrapped, fs, SPACING)
    d[key] = (box.text, wrapped, fs, sz.x, sz.y)
    return wrapped, fs, sz.x, sz.y

def measure(box: Box, width) -> Vector2:
    """Natural (width, height) of a box constrained to `width`."""
    font = _get_font()
    # Geometry that mirrors drawing: border -> padding -> rounded-safe content.
    rr = box.radius if box.radius > 0 else 0.0
    bw = max(1.0, width - box.border.x - box.border.y)
    pw = max(1.0, bw - box.padding.x - box.padding.y)
    inner_w = max(1.0, pw - 2 * rr)
    ins_x = box.padding.x + box.padding.y + box.border.x + box.border.y + 2 * rr
    ins_y = box.padding.z + box.padding.w + box.border.z + box.border.w + 2 * rr

    want = Vector2(0, 0)

    # explicit size hint (authoritative over text/media natural size)
    if box.size.x > 0:
        want.x = box.size.x
    if box.size.y > 0:
        want.y = box.size.y
    size_fixed_x = box.size.x > 0
    size_fixed_y = box.size.y > 0

    # text block
    if box.text:
        _, fs, tw, th = _text_block(box, inner_w)
        if fs > 0 and not size_fixed_y:
            want.y = max(want.y, th)
        if not size_fixed_x:
            want.x = max(want.x, min(tw, inner_w))

    # media
    if (box.texture or (box._media and box._media.active)):
        if box._media and box._media.active:
            mw, mh = box._media.frame_size()
        else:
            mw, mh = box.texture.width, box.texture.height
        if not size_fixed_y:
            if box.texture_fit == "contain":
                scale = min(inner_w / max(1, mw), 1.0)
                want.y = max(want.y, mh * scale)
            else:
                want.y = max(want.y, mh)
        if not size_fixed_x:
            want.x = max(want.x, mw)

    # children
    if box.children:
        vert = box.vertical
        if isinstance(vert, str):
            vert = bool(eval_in(box, vert))
        if vert:
            child_w = 0.0
            child_h = 0.0
            for c in box.children:
                if not is_visible(c):
                    continue
                s = measure(c, inner_w - c.margin.x - c.margin.y)
                child_h += s.y + c.margin.z + c.margin.w
                child_w = max(child_w, s.x + c.margin.x + c.margin.y)
            want.y = max(want.y, child_h)
            want.x = max(want.x, child_w)
        else:
            child_w = 0.0
            child_h = 0.0
            for c in box.children:
                if not is_visible(c):
                    continue
                s = measure(c, inner_w - c.margin.x - c.margin.y)
                child_w += s.x + c.margin.x + c.margin.y
                child_h = max(child_h, s.y + c.margin.z + c.margin.w)
            want.x = max(want.x, child_w)
            want.y = max(want.y, child_h)

    return Vector2(want.x + ins_x, want.y + ins_y)


# ---------------------------------------------------------------------------
# Clipping stack implemented in Python (rectangle intersection)
# ---------------------------------------------------------------------------
_CLIP_STACK: List[Rectangle] = []

def push_clip(rect):
    _CLIP_STACK.append(rect)

def pop_clip():
    if _CLIP_STACK:
        _CLIP_STACK.pop()

def current_clip():
    """Intersection of the clip stack, or None if nothing is clipped."""
    if not _CLIP_STACK:
        return None
    r = _CLIP_STACK[-1]
    for r2 in _CLIP_STACK[:-1]:
        x = max(r.x, r2.x)
        y = max(r.y, r2.y)
        ex = min(r.x + r.width, r2.x + r2.width)
        ey = min(r.y + r.height, r2.y + r2.height)
        r = Rectangle(x, y, max(0, ex - x), max(0, ey - y))
        if r.width <= 0 or r.height <= 0:
            return None
    return r

def clip_state():
    """Return (active, rect).  active is True if any clip is pushed; rect is
    the effective clipping rectangle, or None if the content is fully culled
    (i.e. outside every ancestor clip)."""
    if not _CLIP_STACK:
        return (False, None)
    return (True, current_clip())

def overlaps(a, b):
    return not (a.x + a.width <= b.x or b.x + b.width <= a.x or
                a.y + a.height <= b.y or b.y + b.height <= a.y)

def _clip_with(rect, fn):
    """Run fn() with a scissor clipped to rect (if rect is not None)."""
    r = rect
    if r is not None and r.width > 0 and r.height > 0:
        begin_scissor_mode(int(r.x), int(r.y), int(r.width), int(r.height))
        fn()
        end_scissor_mode()
    else:
        fn()

def intersect(ra, rb):
    if ra is None:
        return rb
    if rb is None:
        return ra
    x0, y0 = max(ra.x, rb.x), max(ra.y, rb.y)
    x1, y1 = min(ra.x + ra.width, rb.x + rb.width), min(ra.y + ra.height, rb.y + rb.height)
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        return None
    return Rectangle(x0, y0, x1 - x0, y1 - y0)

def _scissor(rect):
    if rect is None:
        return None
    return Rectangle(int(rect.x), int(rect.y), int(rect.width), int(rect.height))


# ---- shader-backed media ("procedural video") ----
_SHADERS = {}
_SHADER_RTS = []
_SHADER_BOXES = []
_SCENE_RT = None          # screen-sized backdrop for u_backdrop sampling
_STATIC_PASS = False      # when True we are rendering the backdrop (glass omitted)

def _get_shader(path):
    if path not in _SHADERS:
        try:
            _SHADERS[path] = load_shader(_pr.ffi.NULL, path)
        except Exception as e:
            print("[SUI] shader load failed:", path, e)
            _SHADERS[path] = None
    return _SHADERS[path]

def _unload_shaders():
    for s in _SHADERS.values():
        if s is not None and s.id:
            try:
                unload_shader(s)
            except Exception:
                pass
    _SHADERS.clear()
    for rt in _SHADER_RTS:
        try:
            unload_render_texture(rt)
        except Exception:
            pass
    _SHADER_RTS.clear()
    _SHADER_BOXES.clear()
    global _SCENE_RT
    if _SCENE_RT is not None:
        try:
            unload_render_texture(_SCENE_RT)
        except Exception:
            pass
        _SCENE_RT = None


def _ensure_scene_rt(w, h):
    global _SCENE_RT
    if _SCENE_RT is None or _SCENE_RT.texture.width != int(w) or _SCENE_RT.texture.height != int(h):
        if _SCENE_RT is not None:
            try:
                unload_render_texture(_SCENE_RT)
            except Exception:
                pass
        _SCENE_RT = load_render_texture(int(w), int(h))
    return _SCENE_RT

def _draw_shader(box, x, y, w, h, clip):
    """Blit the box's shader render-texture. The actual render happens in the
    post-frame pass (raylib's shader+BeginTextureMode needs to run outside the
    render frame)."""
    if w < 2 or h < 2:
        return
    box._shader_area = (x, y, w, h)
    if box not in _SHADER_BOXES:
        _SHADER_BOXES.append(box)
    rt = getattr(box, "_shader_rt", None)
    if rt is None or rt.texture.width != int(w) or rt.texture.height != int(h):
        return  # render happens this frame's post-pass; blit next frame
    r = _scissor(clip)
    if r:
        begin_scissor_mode(int(r.x), int(r.y), int(r.width), int(r.height))
    draw_texture_pro(rt.texture, Rectangle(0, 0, int(w), int(h)),
                     Rectangle(float(x), float(y), float(w), float(h)),
                     Vector2(0, 0), 0, WHITE)
    if r:
        end_scissor_mode()

def _render_shader_pass():
    """Render every shader box to its RenderTexture (outside the frame)."""
    for box in _SHADER_BOXES:
        try:
            _render_one_shader(box)
        except Exception as e:
            print("[SUI] shader render error:", e)
    _SHADER_BOXES.clear()

def _render_one_shader(box):
    if not box.shader:
        return
    sh = _get_shader(box.shader)
    if sh is None or not sh.id:
        return
    area = getattr(box, "_shader_area", None)
    if area is None:
        area = (box.rect.x, box.rect.y, box.rect.width, box.rect.height)
    x, y, w, h = area
    wt, ht = int(w), int(h)
    if wt < 2 or ht < 2:
        return
    rt = getattr(box, "_shader_rt", None)
    if rt is None or rt.texture.width != wt or rt.texture.height != ht:
        if rt is not None:
            try:
                unload_render_texture(rt)
            except Exception:
                pass
        rt = load_render_texture(wt, ht)
        box._shader_rt = rt
        _SHADER_RTS.append(rt)
    try:
        loc_t = get_shader_location(sh, b"iTime")
        loc_r = get_shader_location(sh, b"iResolution")
        loc_m = get_shader_location(sh, b"iMouse")
        loc_b = get_shader_location(sh, b"u_backdrop")
    except Exception:
        loc_t = loc_r = loc_m = loc_b = -1
    box._glass = loc_b >= 0
    tf = _pr.ffi.new("float *", get_time())
    rv = _pr.ffi.new("float[2]", [float(wt), float(ht)])
    mp = get_mouse_position()
    mv = _pr.ffi.new("float[2]", [mp.x - x, mp.y - y])
    if loc_t >= 0:
        set_shader_value(sh, loc_t, tf, 0)
    if loc_r >= 0:
        set_shader_value_v(sh, loc_r, rv, 1, 1)
    if loc_m >= 0:
        set_shader_value_v(sh, loc_m, mv, 1, 1)
    # the backdrop texture (scene rendered without this glass box) so the
    # shader can sample/refract what is visually underneath it.
    if loc_b >= 0 and _SCENE_RT is not None:
        try:
            set_shader_value_texture(sh, loc_b, _SCENE_RT.texture)
        except Exception:
            pass
    begin_texture_mode(rt)
    clear_background(BLACK)
    begin_shader_mode(sh)
    draw_rectangle(0, 0, wt, ht, WHITE)
    end_shader_mode()
    end_texture_mode()



# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------
def _rounded(box, rect, color):
    x, y, w, h = int(rect.x), int(rect.y), int(rect.width), int(rect.height)
    if w <= 0 or h <= 0:
        return
    if box.radius > 0:
        rr = Rectangle(float(x), float(y), float(w), float(h))
        # raylib's roundness is a 0..1 fraction of the half of the shorter
        # side, so convert our pixel radius accordingly (and clamp).
        half = max(1.0, min(w, h) / 2.0)
        roundness = max(0.0, min(1.0, box.radius / half))
        segments = max(box.segments, 10)
        draw_rectangle_rounded(rr, roundness, segments, color)
    else:
        draw_rectangle(x, y, w, h, color)


def _draw_media(box, x, y, w, h, clip):
    if w <= 0 or h <= 0:
        return
    med = box._media
    tex = med.current() if (med and med.active) else (box.texture if box.texture and box.texture.id else None)
    if tex is None:
        return
    tw = float(tex.width)
    th = float(tex.height)
    if tw <= 0 or th <= 0:
        return
    src = Rectangle(0, 0, tw, th)
    fit = box.texture_fit
    r = _scissor(clip)
    if r:
        begin_scissor_mode(int(r.x), int(r.y), int(r.width), int(r.height))
    try:
        if fit == "tile":
            yy = y
            while yy < y + h:
                xx = x
                while xx < x + w:
                    draw_texture_ex(tex, Vector2(xx, yy), 0, 1.0, WHITE)
                    xx += tw
                yy += th
        elif fit in ("stretch", "fill"):
            dst = Rectangle(float(x), float(y), float(w), float(h))
        elif fit == "contain":
            scale = min(w / tw, h / th)
            dw, dh = tw * scale, th * scale
            dst = Rectangle(float(x + (w - dw) / 2), float(y + (h - dh) / 2), dw, dh)
        else:  # cover / crop
            scale = max(w / tw, h / th)
            dw, dh = tw * scale, th * scale
            dst = Rectangle(float(x + (w - dw) / 2), float(y + (h - dh) / 2), dw, dh)
        if fit != "tile":
            draw_texture_pro(tex, src, dst, Vector2(0, 0), 0, WHITE)
    finally:
        if r:
            end_scissor_mode()


def _draw_text(box, x, y, w, h, clip):
    if not box.text:
        return
    # fit the text to BOTH the box width and height (so it never overflows/clips)
    wrapped, fs, tw, th = _text_block(box, w, h)
    if tw <= 0 or th <= 0:
        return
    color = box.text_color or BLACK
    ax = box.align_x
    ay = box.align_y
    if ax == "center":
        tx = x + (w - tw) / 2
    elif ax == "right":
        tx = x + (w - tw)
    else:
        tx = x
    if ay == "center":
        ty = y + (h - th) / 2
    elif ay == "bottom":
        ty = y + (h - th)
    else:
        ty = y
    # clamp so text never lies partly outside its box (e.g. low-height headers)
    tx = max(x, min(tx, x + w - tw))
    ty = max(y, min(ty, y + h - th))
    r = _scissor(clip)
    if r:
        begin_scissor_mode(int(r.x), int(r.y), int(r.width), int(r.height))
    draw_text_ex(_get_font(), wrapped, Vector2(float(tx), float(ty)), fs, SPACING, color)
    if r:
        end_scissor_mode()


# ---------------------------------------------------------------------------
# Layout + render
# ---------------------------------------------------------------------------
def _child_layout_normal(box, inner_x, inner_y, inner_w, inner_h):
    total_margin_w = sum((c.margin.x + c.margin.y) if is_visible(c) else 0 for c in box.children)
    total_margin_h = sum((c.margin.z + c.margin.w) if is_visible(c) else 0 for c in box.children)
    available_w = inner_w - total_margin_w
    available_h = inner_h - total_margin_h
    divisor = sum(c.strength if is_visible(c) else 0 for c in box.children)
    offset = 0.0
    vert = box.vertical
    if isinstance(vert, str):
        vert = bool(eval_in(box, vert))
    for c in box.children:
        apply_functions(c)
        if not is_visible(c):
            c.rect = Rectangle(-100000, -100000, 0, 0)
            continue
        fraction = c.strength / divisor if divisor > 0 else 0.0
        if vert:
            allocated_h = (available_h * fraction) + c.margin.z + c.margin.w
            c.rect.x = inner_x + c.margin.x
            c.rect.y = inner_y + offset + c.margin.z
            c.rect.width = inner_w - c.margin.x - c.margin.y
            c.rect.height = allocated_h - c.margin.z - c.margin.w
            offset += allocated_h
        else:
            allocated_w = (available_w * fraction) + c.margin.x + c.margin.y
            c.rect.x = inner_x + offset + c.margin.x
            c.rect.y = inner_y + c.margin.z
            c.rect.width = allocated_w - c.margin.x - c.margin.y
            c.rect.height = inner_h - c.margin.z - c.margin.w
            offset += allocated_w


def _child_layout_scroll(box, inner_x, inner_y, inner_w, inner_h):
    vert = box.vertical
    if isinstance(vert, str):
        vert = bool(eval_in(box, vert))
    off = 0.0
    extent = 0.0
    max_cross = 0.0
    for c in box.children:
        apply_functions(c)
        if not is_visible(c):
            c.rect = Rectangle(-100000, -100000, 0, 0)
            continue
        s = measure(c, inner_w - c.margin.x - c.margin.y)
        if vert:
            cw = inner_w - c.margin.x - c.margin.y
            ch = s.y
            c.rect.x = inner_x + c.margin.x
            c.rect.y = inner_y + off + c.margin.z
            c.rect.width = cw
            c.rect.height = ch
            off += ch + c.margin.z + c.margin.w
            max_cross = max(max_cross, c.rect.width + c.margin.x + c.margin.y)
        else:
            cw = s.x
            ch = inner_h - c.margin.z - c.margin.w
            c.rect.x = inner_x + off + c.margin.x
            c.rect.y = inner_y + c.margin.z
            c.rect.width = cw
            c.rect.height = ch
            off += cw + c.margin.x + c.margin.y
            max_cross = max(max_cross, c.rect.height + c.margin.z + c.margin.w)
    extent = off
    box.content_extent = extent

    # Scroll input while hovered — only the deepest scrollable under the
    # cursor consumes the wheel, so nested containers cancel their parent.
    if extent > (inner_h if vert else inner_w):
        mp = get_mouse_position()
        over = (inner_x <= mp.x <= inner_x + inner_w and inner_y <= mp.y <= inner_y + inner_h)
        if over and box is _SCROLL_TARGET:
            wheel = get_mouse_wheel_move()
            if vert:
                limit = extent - inner_h
                box.scroll_offset.y = max(0.0, min(limit, box.scroll_offset.y - wheel * box.scroll_speed))
            else:
                limit = extent - inner_w
                box.scroll_offset.x = max(0.0, min(limit, box.scroll_offset.x - wheel * box.scroll_speed))
    else:
        box.scroll_offset = Vector2(0, 0)

    return vert


def _draw_self(box, clip):
    if box.parent is None:
        return  # root is drawn by clear_background
    rect = box.rect
    if rect.width <= 0 or rect.height <= 0:
        return

    # ---- background: border fill + hover/selected highlight (clipped) ----
    def _paint():
        if box.hover_color is not None and box is hovering:
            _rounded(box, Rectangle(rect.x - 1, rect.y - 1, rect.width + 2, rect.height + 2), box.hover_color)
        if box.selected_color is not None and box is selected:
            _rounded(box, Rectangle(rect.x - 1, rect.y - 1, rect.width + 2, rect.height + 2), box.selected_color)
        if box.border_color and box.color:
            _rounded(box, rect, box.border_color)
        if box.color:
            _rounded(box, Rectangle(rect.x + box.border.x, rect.y + box.border.z,
                                    rect.width - box.border.x - box.border.y,
                                    rect.height - box.border.z - box.border.w), box.color)

    # ---- content area is inset by border AND padding (matches child layout) ----
    bx = rect.x + box.border.x
    by = rect.y + box.border.z
    bw = rect.width - box.border.x - box.border.y
    bh = rect.height - box.border.z - box.border.w
    x = bx + box.padding.x
    y = by + box.padding.z
    w = bw - box.padding.x - box.padding.y
    h = bh - box.padding.z - box.padding.w

    # For rounded boxes the scissor is rectangular, so keep content inside the
    # square inscribed by the corners; otherwise media/text poke past the arcs.
    rr = box.radius if box.radius > 0 else 0.0
    cx = x + rr
    cy = y + rr
    cw = max(0.0, w - 2 * rr)
    ch = max(0.0, h - 2 * rr)

    # Cull boxes that are entirely outside every ancestor's clip (e.g. a
    # scrolled child moved out of its scroll container's viewport).
    active, container_clip = clip_state()
    box_area = Rectangle(rect.x, rect.y, rect.width, rect.height)
    if active and (container_clip is None or not overlaps(box_area, container_clip)):
        return

    # media/text are clipped to the box content area AND the container clip
    content_clip = intersect(container_clip, Rectangle(cx, cy, cw, ch))

    _clip_with(container_clip, _paint)
    if content_clip is not None and content_clip.width > 0 and content_clip.height > 0:
        if box.shader:
            # backdrop pass omits 'glass' shaders (those that sample u_backdrop)
            # so the backdrop shows the scene behind them for blur/refraction.
            if not (_STATIC_PASS and getattr(box, '_glass', False)):
                _draw_shader(box, cx, cy, cw, ch, content_clip)
        else:
            _draw_media(box, cx, cy, cw, ch, content_clip)
        _draw_text(box, cx, cy, cw, ch, content_clip)
    # inline python overlay (drawn unclipped so scripts can draw freehand)
    if not _STATIC_PASS:
        script_run(box)


def _render(box, clip):
    apply_functions(box)
    if box.parent is not None:
        _draw_self(box, clip)
    inner_x = box.rect.x + box.padding.x
    inner_y = box.rect.y + box.padding.z
    inner_w = box.rect.width - box.padding.x - box.padding.y
    inner_h = box.rect.height - box.padding.z - box.padding.w

    if box.scroll:
        vert = box.vertical
        if isinstance(vert, str):
            vert = bool(eval_in(box, vert))
        # reserve a gutter for the scrollbar so it never covers the children
        ckw = max(1.0, inner_w - (SCROLLBAR_W if vert else 0))
        ckh = max(1.0, inner_h - (0 if vert else SCROLLBAR_W))
        vert = _child_layout_scroll(box, inner_x, inner_y, ckw, ckh)
        limit = box.content_extent - (ckh if vert else ckw)
        sc = box.scroll_offset
        # bake scroll offset into child rects
        for c in box.children:
            if not is_visible(c):
                continue
            if vert:
                c.rect.y -= sc.y
            else:
                c.rect.x -= sc.x
        if limit > 0:
            push_clip(Rectangle(inner_x, inner_y, ckw, ckh))
            for c in box.children:
                if not is_visible(c):
                    continue
                _render(c, current_clip())
            pop_clip()
            # drawn clipped to the parent clip so a container scrolled out of
            # bounds doesn't leave its scrollbar floating over other content
            _clip_with(current_clip(), lambda: _draw_scrollbar(box, inner_x, inner_y, inner_w, inner_h, vert))
        else:
            for c in box.children:
                if not is_visible(c):
                    continue
                _render(c, current_clip())
    else:
        _child_layout_normal(box, inner_x, inner_y, inner_w, inner_h)
        for c in box.children:
            if not is_visible(c):
                continue
            _render(c, current_clip())


def _draw_scrollbar(box, x, y, w, h, vert):
    thumb = ACCENT if False else fade(WHITE, 0.55)
    if vert:
        track_h = h
        content = box.content_extent
        if content <= 0 or content <= track_h:
            return
        thumb_h = max(24.0, track_h * track_h / content)
        ratio = box.scroll_offset.y / max(1.0, content - track_h)
        ty = y + ratio * (track_h - thumb_h)
        tx = x + w - SCROLLBAR_W
        draw_rectangle(int(tx), int(y), int(SCROLLBAR_W), int(track_h), fade(WHITE, 0.08))
        draw_rectangle_rounded(Rectangle(float(tx), float(ty), SCROLLBAR_W, float(thumb_h)), SCROLLBAR_W / 2, 8, thumb)
    else:
        track_w = w
        content = box.content_extent
        if content <= 0 or content <= track_w:
            return
        thumb_w = max(24.0, track_w * track_w / content)
        ratio = box.scroll_offset.x / max(1.0, content - track_w)
        tx = x + ratio * (track_w - thumb_w)
        ty = y + h - SCROLLBAR_W
        draw_rectangle(int(x), int(ty), int(track_w), int(SCROLLBAR_W), fade(WHITE, 0.08))
        draw_rectangle_rounded(Rectangle(float(tx), float(ty), float(thumb_w), SCROLLBAR_W), SCROLLBAR_W / 2, 8, thumb)


def draw(box: Box):
    global _SCROLL_TARGET
    apply_functions(box)
    if box.parent is None:
        box.rect.x = 0
        box.rect.y = 0
        box.rect.width = get_screen_width()
        box.rect.height = get_screen_height()
    _SCROLL_TARGET = _deepest_scrollable(box, get_mouse_position())
    _eval_globals()["box"] = box
    _render(box, None)


def _deepest_scrollable(box, point):
    """Return the deepest scrollable box under `point`, else None."""
    if not (box.rect.x <= point.x <= box.rect.x + box.rect.width and
            box.rect.y <= point.y <= box.rect.y + box.rect.height):
        return None
    for c in box.children:
        if not is_visible(c):
            continue
        r = _deepest_scrollable(c, point)
        if r:
            return r
    return box if box.scroll else None


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
def is_child_of(box: Box, pparent: Box):
    while box and box is not pparent:
        box = box.parent
    return box is None


def _run_callback(fn, box):
    if fn is None:
        return False
    try:
        return bool(fn())
    except Exception as e:
        print(f"[SUI] callback error: {e}")
        return False


def click(box: Box):
    while box and not _run_callback(box.onclick, box):
        box = box.parent


def hover(box: Box, until: Box):
    while box and not (box is until) and not _run_callback(box.onhover, box):
        box = box.parent


def _point_in_view(box, p):
    # A hovered box is only valid if visible within every scrollable ancestor.
    a = box
    while a is not None:
        if a.scroll:
            inner_x = a.rect.x + a.padding.x
            inner_y = a.rect.y + a.padding.z
            inner_w = a.rect.width - a.padding.x - a.padding.y
            inner_h = a.rect.height - a.padding.z - a.padding.w
            if not (inner_x <= p.x <= inner_x + inner_w and inner_y <= p.y <= inner_y + inner_h):
                return False
        a = a.parent
    return True


def trace_mouse(box: Box, point=None) -> Optional[Box]:
    if point is None:
        point = get_mouse_position()
    if not (box.rect.x <= point.x <= (box.rect.x + box.rect.width) and
            box.rect.y <= point.y <= (box.rect.y + box.rect.height)):
        return None
    for c in box.children:
        if not is_visible(c):
            continue
        r = trace_mouse(c, point)
        if r:
            return r
    most = box
    if not _point_in_view(most, point):
        return None
    return most


# ---------------------------------------------------------------------------
# Construction from parsed layout
# ---------------------------------------------------------------------------
def _make_callback(fn_name, params, boxes):
    def call_boxes_set(picked):
        picks = []
        for p in picked:
            # support nested set_children params resolved via boxes
            if isinstance(p, str) and p in boxes:
                picks.append(boxes[p])
            else:
                picks.append(p)
        set_children(*picks)
        return True

    if fn_name == "set_children":
        def cb():
            picks = [_resolve_param(p, boxes) for p in params]
            picks = [p for p in picks if p is not None]
            call_boxes_set(picks)
            return True
        return cb

    def cb():
        fn = _resolve_func(fn_name)
        if fn is None:
            return False
        args = [_resolve_param(p, boxes) for p in params]
        res = fn(*args)
        return True
    return cb


def _resolve_func(name):
    if not name:
        return None
    if name in _EVAL:
        return _EVAL[name]
    return globals().get(name)


def _resolve_param(p, boxes):
    if p in boxes:
        return boxes[p]
    if p in _EVAL:
        return _EVAL[p]
    try:
        return int(p)
    except ValueError:
        pass
    try:
        return float(p)
    except ValueError:
        pass
    return p


def dict_to_box(box_dict: Dict[str, Any], boxes: Dict[str, Box]) -> Box:
    box = Box()
    box.strength = box_dict.get('strength', 100)
    box.text = box_dict.get('text', '')
    box.hidden = box_dict.get('hidden', False)
    box.name = box_dict.get("name", "")
    box.functions = box_dict.get("functions", {})
    box.script = box_dict.get("script", "")

    if 'horizontal' in box_dict:
        box.vertical = not bool(box_dict['horizontal'])
    if 'vertical' in box_dict:
        box.vertical = bool(box_dict['vertical'])

    if 'color' in box_dict:
        box.color = parse_color(box_dict['color'])
    if 'border_color' in box_dict:
        box.border_color = parse_color(box_dict['border_color'])
    if 'hover_color' in box_dict:
        box.hover_color = parse_color(box_dict['hover_color'])
    if 'selected_color' in box_dict:
        box.selected_color = parse_color(box_dict['selected_color'])
    if 'text_color' in box_dict:
        box.text_color = parse_color(box_dict['text_color'])

    if 'padding' in box_dict:
        v = parse_vector4(box_dict['padding']); box.padding = v or box.padding
    if 'margin' in box_dict:
        v = parse_vector4(box_dict['margin']); box.margin = v or box.margin
    if 'border' in box_dict:
        v = parse_vector4(box_dict['border']); box.border = v or box.border

    if 'radius' in box_dict:
        box.radius = float(box_dict['radius'])
    if 'segments' in box_dict:
        box.segments = int(box_dict['segments'])
    if 'align_x' in box_dict:
        box.align_x = str(box_dict['align_x']).lower()
    if 'align_y' in box_dict:
        box.align_y = str(box_dict['align_y']).lower()
    if 'scroll' in box_dict:
        box.scroll = bool(box_dict['scroll'])
    if 'scroll_speed' in box_dict:
        box.scroll_speed = float(box_dict['scroll_speed'])
    if 'texture_fit' in box_dict:
        box.texture_fit = str(box_dict['texture_fit']).lower()
    if 'size' in box_dict:
        s = box_dict['size']
        if isinstance(s, (list, tuple)) and len(s) >= 2:
            box.size.x = float(s[0]) if isinstance(s[0], (int, float)) else 0.0
            box.size.y = float(s[1]) if isinstance(s[1], (int, float)) else 0.0
        elif isinstance(s, (int, float)):
            box.size = Vector2(float(s), float(s))

    # media
    if 'texture' in box_dict and box_dict['texture']:
        box.texture = MEDIA.get('texture', _resolve_media(box_dict['texture'])).textures[0]
    if 'video' in box_dict and box_dict['video']:
        box._media = MEDIA.get('video', _resolve_media(box_dict['video']), fps=box_dict.get('video_fps', 24))
    elif 'anim' in box_dict and box_dict['anim']:
        box._media = MEDIA.get('anim', _resolve_media(box_dict['anim']), fps=box_dict.get('anim_fps', 8))
    if 'shader' in box_dict and box_dict['shader']:
        box.shader = _resolve_media(box_dict['shader'])

    # callbacks
    for key in ('click', 'hover'):
        cb = box_dict.get(key)
        if isinstance(cb, dict):
            if key == 'click':
                box.onclick = _make_callback(cb['function'], cb['params'], boxes)
            else:
                box.onhover = _make_callback(cb['function'], cb['params'], boxes)
    return box


def build_box_hierarchy(boxes_dict: Dict[str, Dict], ns) -> Dict[str, Box]:
    default_dict = boxes_dict.pop("default", {}).copy()
    default_dict.pop("strength", None)
    default_dict.pop("name", None)
    default_dict.pop("parent", None)
    default_dict.pop("indent", None)

    box_objects = {}
    for name, d in boxes_dict.items():
        merged = default_dict.copy()
        merged.update(d)
        box = dict_to_box(merged, box_objects)
        box.name = name
        box_objects[name] = box

    for name, d in boxes_dict.items():
        parent_name = d.get('parent', '')
        if parent_name and parent_name in box_objects:
            add_children(box_objects[parent_name], box_objects[name])

    return box_objects


# ---------------------------------------------------------------------------
# Program entry
# ---------------------------------------------------------------------------
def _make_engine_ns(layout_file):
    global _EVAL
    # base = module globals (pyray star-imported) merged with the layout's python
    boxes, ns = parse(layout_file, {})
    if isinstance(ns, dict):
        # also expose raylib + this module's globals for calc/script
        ns.setdefault("__builtins__", __builtins__)
        for k, v in globals().items():
            if k.startswith('_') and k not in ("Box", "Media", "MediaDB", "_resolve_media"):
                continue
            ns.setdefault(k, v)
        _EVAL = ns
    return boxes, ns


_shot_count = 0

def save_screenshot():
    """Save the current frame to a PNG (used by the F12 hotkey)."""
    global _shot_count
    _shot_count += 1
    path = os.path.join(os.getcwd(), f"sui_shot_{_shot_count:02d}.png")
    try:
        img = load_image_from_screen()
        ok = export_image(img, path)
        unload_image(img)
        print(f"[SUI] screenshot saved -> {path}")
        return ok
    except Exception as e:
        print(f"[SUI] screenshot failed: {e}")
        return False


def _handle_dropped_video(boxes):
    """Load a dropped video file into the player page's media box."""
    try:
        fl = load_dropped_files()
        paths = []
        if hasattr(fl, "count") and hasattr(fl, "paths"):
            for i in range(fl.count):
                try:
                    p = _pr.ffi.string(fl.paths[i]).decode("utf-8", "replace")
                except Exception:
                    p = str(fl.paths[i])
                paths.append(p)
        elif isinstance(fl, (list, tuple)):
            paths = [p.decode() if isinstance(p, (bytes, bytearray)) else str(p) for p in fl]
        try:
            unload_dropped_files(fl)
        except Exception:
            pass
        for p in paths:
            if _is_video_file(p):
                target = boxes.get("pvideo") or boxes.get("herovideo")
                if target:
                    load_video_into(target, p)
                break
    except Exception as e:
        print("[SUI] drop failed:", e)


def _watch_sig(p):
    st = os.stat(p)
    return (st.st_mtime, st.st_size)

def _on_file_changed(p):
    base = os.path.basename(p)
    if base in ("box.py", "parser.py"):
        print(f"[SUI] {base} changed -> restart to apply engine changes", flush=True)
        return
    print(f"[SUI] change detected -> reloading layout ({p})", flush=True)
    _RELOAD_REQUEST.set()

def _watch_loop(paths):
    snap = {p: _watch_sig(p) for p in paths if os.path.exists(p)}
    while True:
        time.sleep(0.4)
        for p in paths:
            try:
                if os.path.exists(p) and snap.get(p) != _watch_sig(p):
                    snap[p] = _watch_sig(p)
                    _on_file_changed(p)
            except Exception:
                pass

def _collect_watch_paths(layout_file):
    here = os.path.dirname(os.path.abspath(__file__))
    base = _LAYOUT_DIR or here
    paths = [os.path.abspath(layout_file), os.path.abspath(__file__),
             os.path.join(here, "parser.py"), os.path.join(here, "make_assets.py")]
    for pat in ("assets/*", "assets/**/*"):
        paths += [p for p in glob.glob(os.path.join(base, pat), recursive=True) if os.path.isfile(p)]
    return paths

def _reload_layout(ns):
    """Re-parse the layout and rebuild the tree live (for development)."""
    global _ROOT, _BOXES, _LAYOUT_DIR
    _LAYOUT_DIR = os.path.dirname(os.path.abspath(_LAYOUT_FILE))
    try:
        boxes_dict, ns = parse(_LAYOUT_FILE, ns)
        # keep media still referenced by the new layout (re-attach streams);
        # only destroy the ones the layout no longer uses.
        destroyed_audio = MEDIA.keep_referenced(boxes_dict)
        if destroyed_audio:
            # reset the audio device so a later fresh stream creation won't
            # hit PulseAudio's stale-context pa_stream_cork assertion
            try:
                close_audio_device()
            except Exception:
                pass
        boxes = build_box_hierarchy(boxes_dict, ns)
        if "root" not in boxes:
            raise RuntimeError("layout has no 'root' box")
        _BOXES = boxes
        _ROOT = boxes["root"]
        _EVAL["boxes"] = boxes
        print("[SUI] layout reloaded", flush=True)
    except Exception as e:
        print(f"[SUI] reload failed (keeping current layout): {e}", flush=True)


def main():
    global _ROOT, _BOXES, _LAYOUT_FILE, hovering, selected
    layout_file = sys.argv[1] if len(sys.argv) > 1 else None
    if layout_file is None:
        for cand in ("./examples/demo.txt", "./demo.txt", "./examples/test_layout_2.txt"):
            if os.path.exists(cand):
                layout_file = cand
                break
        else:
            layout_file = "./examples/demo.txt"
    if not os.path.exists(layout_file):
        print(f"Layout not found: {layout_file}")
        sys.exit(1)
    _LAYOUT_FILE = layout_file
    global _LAYOUT_DIR
    _LAYOUT_DIR = os.path.dirname(os.path.abspath(layout_file))

    set_config_flags(ConfigFlags.FLAG_WINDOW_RESIZABLE)
    init_window(800, 450, "SUI")
    fps = 180
    set_target_fps(fps)

    boxes_dict, ns = _make_engine_ns(layout_file)
    boxes = build_box_hierarchy(boxes_dict, ns)
    _BOXES = boxes
    _ROOT = boxes["root"]
    _EVAL["boxes"] = boxes   # let calc/script reference boxes by name

    # watch for file changes so the layout hot-reloads during development
    watched = _collect_watch_paths(layout_file)
    threading.Thread(target=_watch_loop, args=(watched,), daemon=True).start()

    max_frames = int(os.environ.get("SUI_MAX_FRAMES", "0"))

    hovering = _ROOT
    selected = _ROOT
    i = 0

    while not window_should_close():
        i += 1
        _refresh_ctx()

        # backdrop pass: render the scene (glass shaders omitted) into a
        # screen-sized texture so glass boxes can sample/blur what's behind.
        global _STATIC_PASS
        if any(getattr(b, "_glass", False) for b in _BOXES):
            sw, sh = int(get_screen_width()), int(get_screen_height())
            if _ensure_scene_rt(sw, sh) is not None:
                _STATIC_PASS = True
                begin_texture_mode(_SCENE_RT)
                clear_background(WHITE)
                draw(_ROOT)
                end_texture_mode()
        _STATIC_PASS = False

        begin_drawing()
        clear_background(WHITE)

        draw(_ROOT)
        if is_key_pressed(KeyboardKey.KEY_F12):
            save_screenshot()
        if is_file_dropped():
            _handle_dropped_video(_BOXES)
        h = trace_mouse(_ROOT)
        if h is not hovering:
            if not is_child_of(h, hovering):
                hover(h, hovering)
            hovering = h
        if h and _point_in_view(h, get_mouse_position()):
            if is_mouse_button_pressed(MouseButton.MOUSE_BUTTON_LEFT):
                selected = h
                click(selected)
        end_drawing()

        _render_shader_pass()   # render shaders to their textures (out of frame)
        _run_pending_open()   # native file dialog, safely outside the frame

        if _RELOAD_REQUEST.is_set():
            _RELOAD_REQUEST.clear()
            _reload_layout(ns)
            hovering = _ROOT
            selected = _ROOT

        if max_frames and i >= max_frames:
            break

    MEDIA.unload_all()
    _unload_shaders()
    try:
        close_audio_device()
    except Exception:
        pass
    close_window()

if __name__ == "__main__":
    main()
