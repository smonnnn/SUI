# SUI — box layout language for VS Code

Syntax highlighting, language configuration and snippets for **SUI**'s declarative
box layout language (`.sui` files — the `box.py`/`parser.py` engine in the repo
root).

## Features

- **Syntax highlighting** for:
  - box definitions: `[1-name]:` and shared groups like `[1-bp.play]`
  - attributes: `.color=(14,26,30,150)`, `.text="hi"`, `.click=bump(a, 1)`,
    flags like `.vertical`, and `calc(...)` expressions
  - named color definitions: `ACCENT = (120, 210, 235, 255)`
  - line comments (`# ...`)
  - directives and embedded Python: `@python ... @end`, `@import module`
    (the block gets real Python highlighting if the Python extension is active)
- **Snippets**: root, container, text, button, color, python block, shader box,
  media box, shared group, scroll container.
- Folding of `@python` / `@end` blocks, comment/bracket handling.

## Install / develop

1. Open this folder (`sui-extension/`) in VS Code.
2. Press `F5` to launch an Extension Development Host, then open any `.sui`
   layout (e.g. `../examples/glassurf.sui`) to see highlighting + snippets.

To package for personal/team use:

```sh
npm i -g @vscode/vsce
vsce package
code --install-extension sui-language-*.vsix
```

> Set a unique `publisher` in `package.json` before publishing to the
> Marketplace.

## Language at a glance

```
# a named color
ACCENT = (120, 210, 235, 255)

# a box definition: [<strength>-<name>]:   (dots form a shared group)
[1-root]:
    .vertical
    .margin=0
    .padding=0
    [10-card]:
        .shader=shaders/glass.frag
        .radius=14
        .text="Glass"
        .click=bump(card, 1)
        [1-inline]: .color=(10, 24, 26, 140) .align_x=center
```