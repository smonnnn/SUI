# Writing `.sui` interfaces — a short guide

SUI layouts are plain text files with a `.sui` extension. A layout is a tree of
**boxes** — every box is a rectangle that can have a colour, text, media, a
shader, children, and Python-driven behaviour. The whole file describes a UI,
nothing to build or compile: run `python box.py yourlayout.sui` and edit the
file to see changes live (the engine hot-reloads on save).

This guide is short on purpose — read `examples/glassurf.sui` next to it; it's
a compact, commented reference.

---

## Anatomy of a file

```
# comments start with #

# 1) named colours (used anywhere a colour is expected)
ACCENT = (120, 210, 235, 255)

# 2) optional Python block: state + helper functions, shared by the whole layout
@python
STATE = {"n": 0}
def bump(box, d):
    STATE["n"] += int(d)
    return True
@end

# 3) the box tree (see below)
[1-root]:
	.vertical
	...
```

---

## Boxes

A box is defined by a header line, and its **children are nested underneath
with tabs**:

```
[1-root]:
	.vertical
	[2-topbar]:
		.horizontal
		[1-title]:
			.text="LENS CONTROL"
```

The header is `[<strength>-<name>]:`.

- **name** — a unique id (`title`, `topbar`). You reference it in `calc()`,
  `click=`, etc.
- **strength** — how much space the box gets *along its parent's axis*
  (a bigger number = more space, shared proportionally). Strength 100 is the
  default. It lives in the header only — `.strength=` is **not** a property.
- **weight** — optional, a **single float**. Makes a child's share responsive to
  the parent's size along the layout axis:

  ```
  effective strength = strength * (parent_axis / 800) ** weight
  ```

  `parent_axis` is the parent's inner height for a vertical parent, inner width
  for a horizontal one, and 800 is a reference size. So:
  - `weight=0` (or unset) — the fixed ratio from the header strengths, unchanged.
  - `weight>0` — the box grows relatively on large parents.
  - `weight<0` — the box grows relatively on small parents (handy for a
    sidebar that takes a modest share on wide windows but dominates when narrow).

  Example — a sidebar that holds 20/80 on wide windows but ~40/60 when the
  parent narrows to 400px:

  ```
  [20-sidebar]:
      .weight=-0.7
  [80-main]: ...
  ```

  A plain number overrides the header strength (`weight=20` → strength 20, and
  `weight=0` collapses the box). Weight applies to normal strength-split
  layout, not `.scroll` containers (which use natural sizes).
- `[5-bp.play]` — the part **before the dot** (`bp`) is a *group*; the part
  after the dot is the member. See *Shared groups* below.

Indentation must be **tabs** (not spaces), and depth = nesting depth.

---

## Attributes

Attributes are lines `.name=value` under a box (a bare `.vertical` is a flag
that means `.vertical=True`). The commonly used ones:

**Appearance**
```
.color=(14, 26, 30, 150)     # r,g,b,a — the alpha makes a box translucent
.color=None                  # no background (transparent)
.color=BG                    # or a named colour
.text_color=TEXT
.border_color=LINE
.radius=10                   # corner radius (px); 0 = square
.border=2                    # border thickness (px)
.segments=10                 # smoothness of rounded corners
```

**Layout / size**
```
.vertical / .horizontal      # stacking direction of children (default horizontal)
.padding=10                  # space inside the box (or .padding=(l,r,t,b))
.margin=4                    # space outside the box (or .margin=(l,r,t,b))
.weight=0.5                  # responsiveness exponent (a single float, see below)
.align_x=center              # left | center | right (within parent)
.align_y=center              # top | center | bottom
.hidden=True                 # skip it (and its children)
.scroll                      # make a container scrollable
```

**Content**
```
.text="Hello"                # label text
.texture=assets/logo.png     # image (texture_fit=cover/contain/stretch/tile/crop)
.anim=assets/anim            # an animation (sequence of frames), .anim_fps=18
.video=assets/video.mp4      # a streaming video
.shader=shaders/glass.frag   # a fragment shader fills the box
.font=path/to/font.ttf       # a custom TTF/OTF for this box's text (all its
                             # glyphs are loaded; paths resolve like media)
.script=my_frame(box)        # python run every frame (e.g. custom drawing)
```

**Behaviour**
```
.click=my_handler(box, 1)    # on mouse click
.hover=my_handler(box)       # on hover
.hover_color=ACCENT_SOFT     # hover highlight colour
.selected_color=LINE         # while pressed/selected
.adjust                      # drag it with the mouse to resize its strength
```

Inline attributes are allowed after a header: `[1-inline]: .color=(0,0,0,255) .align_x=center`

---

## Colours

`(r, g, b, a)` — all 0–255. `a` (alpha) below 255 makes the box translucent
(handy for floating cards, HUDs, glassy panels).

Define named colours once at the top and reuse them:

```
BG    = (10, 18, 20, 255)
ACCENT = (120, 210, 235, 255)
```

---

## Python, live values, and events

- **State & helpers** live in a `@python … @end` block. Everything defined
  there is available layout-wide.
- **`calc(expr)`** — evaluate an expression every frame and use the result as
  the value of an attribute:

  ```
  .text=calc(clk())          # a live clock
  .text=calc(count())        # a live counter
  .refrac=calc(refn())       # drive a shader parameter
  ```

- **`click=` / `hover=`** call a Python function. The **first argument is
  always the box itself**:

  ```
  .click=bump(plus.refract, 1)
  ```

  Return `True` to consume the event.

- **`@import module`** brings in an external module (see `suifx.py`).

Keep your state in a plain dict (e.g. `STATE`) so `calc()` and handlers share
it. `clampv`-style helpers are your friend for slider/step controls.

---

## Shared groups (the key to tidy files)

Boxes whose name contains a dot share the prefix as a **group**. Any attribute
written on **only one** member is inherited by the rest; attributes written on
several stay per-box. This is how `glassurf.sui` keeps three control rows
(Frost / Opacity / Refraction) with almost no repetition:

```
# 'label' group: styling lives on label.refract, others inherit it
[30-label.refract]:
	.text="Refraction"
	.color=None
	.text_color=TEXT
	.align_y=center
[30-label.frost]:
	.text="Frost"          # only what differs
[30-label.opacity]:
	.text="Opacity"
```

The same trick powers the `btn.*` pills — the pill styling is written once and
inherited by every button.

### Groups are recursive

Every dot-segment of a name is a group, and the most specific one wins. So you
can give *variants* their own shared values: the minus buttons are a `btn.m`
group and the plus buttons a `btn.p` group, nested inside the shared `btn`
group:

```
# 'btn' group: shared styling (color, radius, padding, …) for all buttons
[5-btn.m.refract]:
	.color=ACCENT
	.radius=10
	.text="-"
	.click=bump(btn.m.refract, -1)
[5-btn.m.frost]:
	.click=set_frost(btn.m.frost, -0.12)   # inherits '-' + styling from btn.m.refract
[5-btn.m.opacity]:
	.click=set_opacity(btn.m.opacity, -0.10)

[5-btn.p.refract]:
	.text="+"
	.click=bump(btn.p.refract, 1)          # 'btn.p' group shares '+'
[5-btn.p.frost]:
	.click=set_frost(btn.p.frost, 0.12)
[5-btn.p.opacity]:
	.click=set_opacity(btn.p.opacity, 0.10)
```

Here `btn.m` shares `text="-"` and the pill styling; `btn.p` shares `text="+"`;
and because the subgroups merge before the outer `btn` group, the styling is
inherited everywhere and each variant keeps its own text. `.click` is unique
per member, so it's never shared.

**`calc(...)` values are exempt from sharing.** A `calc(...)` value is stored
separately (a *function*), so it is *never* inherited or shared between group
members — every member's `calc(...)` stays its own. Only plain values
(`.text="x"`, `.color=…`, `.padding=…`) participate in sharing.

> Tip: because inherited attributes are picked from whichever member declares
> them, put the *shared* attributes on the **first** member of each group (and
> reference a box by its full dotted name in `click=`/`hover=`).

---

## Shaders

Any box can be filled by a GLSL fragment shader:

```
[1-card]:
	.shader=shaders/glass.frag
	.color=None
	.radius=14
```

The engine gives every shader these optional parameters — declare any you need:

- `iTime`, `iResolution`, `iMouse` — always provided.
- `u_origin`, `u_screenRes` — this box's screen footprint (for mapping textures).
- `u_<name>` — fed from the box attribute of the same name (`.refract` →
  `u_refract`, `.frost` → `u_frost`, `.speed` → `u_speed`, …), so you can drive
  a shader from the UI:

  ```
  .refrac=calc(refn())
  .frost=calc(frost_val())
  ```

- `u_background` *(sampler2D)* — the scene *behind* this box (rendered into a
  backdrop pass). Declaring it makes the box a "lens" that samples
  what's underneath.
- `u_prev` *(sampler2D)* — this box's own previous frame (ping-pong feedback),
  for flow fields / trails (`shaders/flow.frag`).

Both samplers are detected just by being used in the shader; no extra marker
needed.

---

## Tips & gotchas

- **Tabs, not spaces** for nesting. Mixing breaks the tree.
- **Reuse named colours** — don't repeat magic `(r,g,b,a)` everywhere.
- **`calc()` for anything live** — clocks, counters, shader params, even
  `.hidden=calc(ready())`.
- **Click handlers take the box first** — pass the box's *own* name
  (`bump(plus.refract, 1)`) even if your function ignores it; it's clearer and
  stays correct if you later use `box`.
- **Inheritance gotcha**: in a shared group, `.text` on one member is *shared*.
  If members need different text, set `.text` on **each** member (as above).
- **Translucency** = alpha in the colour. `.color=None` = invisible background
  (just text / shader / children).
- **Strength distributes the parent's axis**. `[5-...]` vs `[30-...]` is a 5:30
  split — use it to make a sidebar vs. main content.
- **Order = z-order**: a box listed after its siblings draws on top. For an
  overlay, put it last.
- **Media & shader paths are relative to the layout file's folder**.
- **Edit and it reloads** — the engine watches the file. Iterate live.
- **Missing value → string**: an undefined param (like a stray `rplus`) is
  passed through as a string, so a handler that ignores its `box` arg still
  works — but name it right anyway (`plus.refract`).
- **VS Code**: the `sui-extension/` in this repo gives highlighting + snippets
  for `.sui` files.

---

## Good to know (deeper gotchas)

These are the non-obvious parts that cost real time if you don't know them:

- **The `time` module is not shadowed** — the frame timestamp is exposed to
  `calc()` as **`now`**, and the real `time` module stays importable, so
  `time.time()` works in `@python`. Don't rely on a `time` variable in `calc`
  (use `now`).
- **Colour names are layout-only.** `ACCENT = (...)` is usable in attributes
  (`.color=ACCENT`) but is *not* visible to `calc()`/`script=` — use a
  `Color(r,g,b,a)` literal there.
- **Box names in `script=`/`calc=`** — only `click=`/`hover=` resolve names to
  Box objects. In a script use `box` (the box the script is on) or
  `boxes["name"]`.
- **The default font is ASCII-only.** `measure_text`/`draw_text` and
  `load_font_ex(..., NULL, 0)` only rasterise ASCII — non-ASCII glyphs measure
  width 0 and render as nothing. For symbols/emoji/accents set `.font=path`
  (loads all the font's glyphs), and in scripts measure/draw with
  `measure_text_ex`/`draw_text_ex` on that font. Note `measure_text` (default
  font) won't match text the engine draws with a custom font.
- **The root box is never painted** — the frame clears to white, so any gap not
  covered by an opaque box (root padding, margins, transparent boxes) shows
  white. Make the outermost box opaque and give it 0 margin/padding.
- **`#` comments**: a `#` starts a comment except inside a quoted value
  (`.text="50% # off"` is fine) and inside `@python` blocks.
- **Render-thread discipline.** raylib texture creation / `load_video_into` /
  `MEDIA.spawn_video` must happen on the render thread (a per-frame `.script`
  is a good spot). Long/blocking work (ffmpeg, torrent downloads) goes on a
  daemon thread that sets a flag the render thread polls. Native dialogs
  (tkinter) can't open mid-frame — queue them with `after_frame(fn)`.
- **Hot-reload resets spawned media.** Editing the layout keeps cached media
  but *unloads* spawned ones — so an active torrent or a temp audio remux
  resets to the default file. Editing `box.py`/`parser.py` needs a restart.
- **`SUI_CAPTURE` screenshots are vertically flipped** (RenderTexture is
  bottom-up); F12 screenshots are correct.

---

## A minimal complete example

```
BG = (9, 15, 17, 255)
ACCENT = (237, 163, 90, 255)

@python
COUNT = {"n": 0}
def bump(box, d):
    COUNT["n"] += int(d)
    return True
def show():
    return "count %d" % COUNT["n"]
@end

[1-root]:
	.vertical
	.color=BG
	[1-title]:
		.color=None
		.text_color=ACCENT
		.text=calc(show())
	[1-row]:
		.horizontal
		[1-btn.minus]:
			.text="-"
			.color=ACCENT
			.padding=12
			.radius=10
			.click=bump(btn.minus, -1)
		[1-btn.plus]:
			.text="+"
			.click=bump(btn.plus, 1)
```