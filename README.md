# SUI

A tiny, declarative UI shell for **raylib** written in Python. Layouts are plain
text — boxes with strengths, margins, padding, borders, rounded corners, scroll
containers, textures/animations/video, and first-class Python integration
(`@python`, `@import`, `calc()`, per-frame `script()` and click callbacks).

```txt
[1-item.home]:
    .text="Home"
    .click=set_children(swap, content.home)
```

---

## Features

- **Box layout** — nested boxes with `strength` (flex), `margin`, `padding`,
  `border`, `color`, `border_color`, horizontal/vertical orientation.
- **Rounded corners** — `.radius` (converted to raylib's roundness fraction).
- **Text** — wrapping, font auto-shrink to fit the box, `align_x` / `align_y`
  (left/center/right, top/center/bottom), `text_color`.
- **Scrolling** — `.scroll` containers (vertical or horizontal) with wheel
  scrolling, natural-size measurement, a reserved scrollbar gutter, and nested
  scroll (a scrollable child cancels its parent).
- **Media** — `.texture=`, `.anim=` (frame loops), `.video=` (real video files),
  with `texture_fit` = `stretch | contain | cover | tile`. Video streams via
  ffmpeg (system binary, or the one bundled with `imageio-ffmpeg`), including
  audio playback, play/pause, seek and mute.
- **Shaders** — `.shader=file.frag` renders a GLSL fragment shader into a
  RenderTexture every frame (a GPU-generated "video"), with `iTime`,
  `iResolution` and `iMouse` uniforms. Write your own `.frag` and point a box
  at it (`examples/shaders/*`).
- **Frame feedback (ping-pong)** — any shader that declares `uniform float
  u_feedback;` is rendered with framebuffer feedback: the engine keeps two
  textures per box, binds the previous frame as `texture0`, then swaps, so a
  shader can read its own last frame and accumulate (trails, flow fields, smoke,
  sand, growth effects). Generic `u_<name>` uniforms can be driven by matching
  box attributes (`.speed=calc(…)`, `.fade=…`, etc.). `shaders/flow.frag` uses
  this for a GPU flow field with fading, hue-shifting trails.
- **Glass lens** — `shaders/glass.frag` is a real refracting lens (rounded-box
  SDF that matches the box's `.radius`, Schlick fresnel, chromatic aberration,
  gaussian blur, drop shadow). Any box whose shader declares `uniform float
  u_glass;` becomes a "lens": the engine renders the scene *behind* it into an
  offscreen texture and binds it as `texture0` (via `set_shader_value_texture`),
  so the lens samples/refracts exactly what's underneath. The box's `.refrac`,
  `.frost` and `.opacity` attributes (e.g. `.refrac=calc(mycount())`) drive the
  refraction strength, frosting (blur + milky turbidity) and alpha.
  `glassurf.txt` puts one over the Waves wallpaper with -/+ controls for each.
- **Hover / selected colors** — `.hover_color` and `.selected_color`.
- **Shared attribute groups** — boxes named like `item.home` form an `item` group;
  attributes appearing on only one member are inherited by the rest, while
  attributes set on several stay unique per box.
- **Python everywhere** — `@python ... @end` blocks, `@import module`, `calc()`
  expressions, per-frame `script()` and `click=`/`hover=` callbacks share one
  namespace (which also exposes every box by name via `boxes[...]`).
- **Live hot-reload** — the engine watches the layout (and `assets/`) and
  reloads it in place on change; media that's still referenced is re-attached.
- **F12** — save a screenshot of the current frame.

---

## Requirements

- Python 3.9+
- A GPU/display (raylib desktop, OpenGL)
- `ffmpeg` on `PATH` for video playback, **or** the self-contained binary that
  `imageio-ffmpeg` provides

## Quick start

```bash
./setup.sh
```

`setup.sh` creates a virtualenv, installs `raylib` and `imageio-ffmpeg`, generates
the procedural demo artwork (`assets/`), and launches the demo:

```bash
python box.py examples/demo.txt
```

To run a different layout: `python box.py path/to/layout.txt`

### Manual setup

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install raylib==6.0.1.0 imageio-ffmpeg
python make_assets.py
python box.py examples/demo.txt
```

---

## Project structure

```
box.py            the engine (media, layout, rendering, events, hot-reload)
parser.py         the layout-language parser (boxes, attributes, @python/@import)
make_assets.py    generates the demo artwork (logo, animation, video frames, .mp4)
suifx.py          an example @import helper module
setup.sh          venv + deps + asset generation + run
README.md
examples/
  demo.txt        the main showcase layout (sidebar, pages, video player)
  flow.txt        "Flow Field" — a GPU flow field via frame feedback (fbm trails)
  shader.txt      "Shader Lab" — GPU fragment shaders rendered to a texture
  shadertop.txt   a live shader wallpaper behind translucent widgets
  glassurf.txt    "Lens Control" — glassy lenses over the Waves wallpaper
  shaders/        shader sources (plasma, swirl, mandelbrot, waves, glass, frosted, flow)
  test_layout_2.txt  a minimal original example
  assets/         final artwork committed here: logo.png + video.mp4
  shaders/        .frag shaders (plasma, swirl, mandelbrot)
```

Media paths in a layout are resolved relative to the layout file, so
`examples/demo.txt` can refer to `assets/logo.png` and it points at
`examples/assets/logo.png`.

---

## The layout language

### Colors

```txt
ACCENT = (237, 163, 90, 255)
```

### Boxes

```txt
[<strength>-<name>]:
    .property=value
```

The first number is the box's `strength` (used to divide space). `-` separates
it from the name. Indentation (tabs) defines parent/child nesting. One property
per line.

### Attributes

| attribute        | example                    | notes |
|------------------|----------------------------|-------|
| `strength`/`number` | `[2-name]:`             | relative space |
| `text`           | `.text="Hello"`            | wrapped & auto-shrunk |
| `color`          | `.color=PANEL`             | fill (or `None`) |
| `border_color`   | `.border_color=LINE`       | |
| `hover_color`    | `.hover_color=ACCENT_SOFT` | border on hover |
| `selected_color` | `.selected_color=LINE`     | border on click |
| `text_color`     | `.text_color=TEXT`         | |
| `padding`/`margin`/`border` | `.padding=(l,r,t,b)` | 4-tuple, or a single int = all sides |
| `radius`         | `.radius=10`               | corner radius |
| `horizontal`/`vertical` | `.vertical`          | flag → True |
| `align_x`/`align_y` | `.align_x=center`      | left/center/right, top/center/bottom |
| `scroll`         | `.scroll`                  | scrollable container |
| `scroll_speed`   | `.scroll_speed=45`         | |
| `size`           | `.size=(0,290)`            | `(width,height)` hint |
| `texture`        | `.texture=assets/logo.png` | still image |
| `anim`           | `.anim=assets/anim`        | frame-loop animation (`.anim_fps`) |
| `video`          | `.video=assets/video.mp4`  | streamed video (`.video_fps`) |
| `shader`         | `.shader=shaders/plasma.frag` | fragment shader → texture (GPU video) |
| `texture_fit`    | `.texture_fit=contain`     | stretch/contain/cover/tile |
| `click`          | `.click=set_children(swap, content.home)` | click callback |
| `hover`          | `.hover=...`               | hover callback |
| `script`         | `.script=draw_circle(...)` | Python run every frame |
| `hidden`         | `.hidden=calc(ratio < 1.0)` | visible/calc |

### Shared attribute groups

Boxes whose names share a prefix before the first `.` form a group:

```txt
[1-item.home]:      # defines shared styling + its own text/click
    .text="Home"
    .color=ACCENT
    .hover_color=ACCENT_SOFT
    .padding=16
    .click=set_children(swap, content.home)
[1-item.stats]:     # inherits color/hover_color/padding from the group
    .text="Stats"   # unique per box
    .click=set_children(swap, content.stats)
```

### Python

```txt
@python
import datetime
def clk():
    return datetime.datetime.now().strftime("%H:%M:%S")
@end

[1-clock]:
    .text=calc(clk())
```

- `@python ... @end` — a block of real Python, available in the shared namespace.
- `@import module` — import a module (e.g. `suifx`) and expose its public names.
- `calc(expr)` — evaluate an expression (with `box`, `mouse`, `time`, `width`,
  `height`, `ratio`, `boxes[...]` and all helpers in scope) and use the result.
- `script=...` — run statements each frame (can call raylib draw functions via
  `box.rect`, `draw_rectangle`, ...).
- `click=`/`hover=` — call a function; box names resolve to the live `Box`
  object (e.g. `click=bump(ctrLabel)`).

---

## Dev hot-reload

The app watches the layout file and `assets/`. Edit a layout and it reloads
live; referenced media is kept (textures/audio streams are re-attached) and only
unused media is released. Engine files (`box.py`/`parser.py`) print a hint to
restart instead of hot-swapping.

---

## F12 screenshots

Press **F12** to save `sui_shot_01.png`, `sui_shot_02.png`, ... in the current
directory.
