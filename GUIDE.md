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
  default.
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
.strength=30                 # proportional space along the parent's axis
.padding=10                  # space inside the box (or .padding=(l,r,t,b))
.margin=4                    # space outside the box (or .margin=(l,r,t,b))
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
.script=my_frame(box)        # python run every frame (e.g. custom drawing)
```

**Behaviour**
```
.click=my_handler(box, 1)    # on mouse click
.hover=my_handler(box)       # on hover
.hover_color=ACCENT_SOFT     # hover highlight colour
.selected_color=LINE         # while pressed/selected
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

The engine gives every shader `iTime`, `iResolution`, `iMouse`. Box attributes
map to `u_<name>` uniforms (`.refract` → `u_refract`, `.frost` → `u_frost`,
`.speed` → `u_speed`, …), so you can drive a shader from the UI:

```
.refrac=calc(refn())
.frost=calc(frost_val())
```

Two built-in shader modes:
- **`u_sample_background`** — a "lens" box that samples the scene *behind* it
  (rendered into `texture0`) and refracts it.
- **`u_feedback`** — frame feedback (ping-pong), for flow fields / trails
  (`shaders/flow.frag`).

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