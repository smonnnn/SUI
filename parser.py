from collections import defaultdict
import textwrap
import importlib

def get_int(string):
    """Extract the first integer from a string."""
    for i, ch in enumerate(string):
        if ch.isdigit():
            start = i
            break
    else:
        return 0
    num = ""
    for ch in string[start:]:
        if ch.isdigit():
            num += ch
        else:
            break
    return int(num)

def parse_ints(string):
    """Parse a string like '(5,5,0,5)' into a list of ints."""
    ints = []
    content = string.strip('()')
    if content:
        parts = content.split(',')
        for p in parts:
            p = p.strip()
            if p:
                ints.append(int(p))
    return ints

def _norm_value(param_name, param_string, colors):
    """Normalise a raw attribute value into a Python value."""
    if param_name in ("script", "texture", "anim", "video", "shader"):
        return param_string
    if param_name in ("align_x", "align_y", "texture_fit"):
        return param_string
    if param_string.startswith('('):
        return parse_ints(param_string)
    if param_string.startswith('"'):
        return param_string[1:-1]
    if param_string in ("True", "False"):
        return param_string == "True"
    if param_string == "None":
        return None
    if param_string.isdigit() or (param_string.startswith('-') and param_string[1:].isdigit()):
        return int(param_string)
    if param_name.startswith("click") or param_name in ("hover", "onclick", "onhover"):
        fn_name = param_string[:param_string.find("(")] if "(" in param_string else param_string
        prms = param_string[param_string.find("(")+1:param_string.rfind(")")] if "(" in param_string else ""
        prms = [p.strip() for p in prms.split(",") if p.strip()]
        return {"function": fn_name, "params": prms}
    # Assume it's a color name; look it up
    return colors.get(param_string, [0, 0, 0, 0])

def _store_attr(boxes, current_box, param_name, param_string, colors):
    if not current_box:
        return
    if param_string.startswith("calc"):
        inner = param_string[param_string.find("(")+1:param_string.rfind(")")]
        boxes[current_box]["functions"][param_name] = inner
        return
    boxes[current_box][param_name] = _norm_value(param_name, param_string, colors)

def _tokenize_inline(s):
    """Split a ``.key=value .key2=value2'' tail (after ``]:``) into pairs."""
    tokens = []
    i, n = 0, len(s)
    while i < n:
        while i < n and s[i].isspace():
            i += 1
        if i >= n:
            break
        if s[i] != '.':
            i += 1
            continue
        j = i + 1
        while j < n and (s[j].isalnum() or s[j] == '_'):
            j += 1
        key = s[i + 1:j]
        i = j
        while i < n and s[i].isspace():
            i += 1
        if i < n and s[i] == '=':
            i += 1
            while i < n and s[i].isspace():
                i += 1
            if i < n and s[i] == '"':
                i += 1
                start = i
                while i < n and s[i] != '"':
                    i += 1
                raw = s[start:i]
                if i < n and s[i] == '"':
                    i += 1
                raw = '"' + raw + '"'
            else:
                start = i
                while i < n and not s[i].isspace():
                    i += 1
                raw = s[start:i]
            tokens.append((key, raw))
        else:
            tokens.append((key, "True"))
    return tokens


def _exec_imports(imports, ns):
    for mod in imports:
        module = importlib.import_module(mod)
        for key in dir(module):
            if not key.startswith('_'):
                ns.setdefault(key, getattr(module, key))

def _exec_python_code(blocks, ns):
    for block in blocks:
        code = textwrap.dedent(block)
        exec(compile(code, "<layout-python>", "exec"), ns, ns)

def load(layout_filename, ns=None):
    """Backwards-compatible wrapper returning only the boxes dict."""
    boxes, _ = parse(layout_filename, ns)
    return boxes

def parse(layout_filename, ns=None):
    """Parse a layout file.

    Returns (boxes, namespace).  The namespace is populated with any
    ``@import`` modules and ``@python`` / ``@end`` blocks defined in the
    layout so that user Python code is a first-class part of the language.
    """
    if ns is None:
        ns = {}

    with open(layout_filename, "r") as f:
        raw_lines = f.readlines()

    # Strip trailing newlines but keep tabs so python blocks can be dedented.
    lines = [l.rstrip('\n') for l in raw_lines]

    colors = {}
    last_at_indent = {}
    boxes = defaultdict(dict)
    imports = []
    python_blocks = []
    capturing_python = False
    python_buf = []
    base_indent = 0

    i = 0
    while i < len(lines):
        line = lines[i]

        # --- Handle raw python capture mode ---
        if capturing_python:
            if line.strip() == '@end':
                python_blocks.append("\n".join(python_buf))
                python_buf = []
                capturing_python = False
                i += 1
                continue
            # Strip the common base indent so the code block stays valid Python.
            if base_indent:
                line = line[base_indent:]
            python_buf.append(line)
            i += 1
            continue

        # Remove comments (only outside python blocks)
        if '#' in line:
            line = line[:line.index('#')]
        line = line.rstrip()
        if not line:
            i += 1
            continue

        stripped = line.lstrip('\t')
        indent = len(line) - len(stripped)
        line = stripped.strip()

        # --- Directives: @import / @python ---
        if line.startswith('@'):
            if line.startswith('@import'):
                mod = line[len('@import'):].strip()
                if mod:
                    imports.append(mod)
            elif line.startswith('@python'):
                rest = line[len('@python'):].strip()
                if rest:
                    # one-line python statement
                    python_blocks.append(rest)
                else:
                    # block mode: capture until @end
                    capturing_python = True
                    python_buf = []
                    base_indent = indent
            i += 1
            continue

        if line.startswith('['):          # new box definition
            strength = get_int(line)
            name_start = line.find('-') + 1
            name_end = line.rfind(']')
            name = line[name_start:name_end].strip()
            parent = last_at_indent.get(indent - 1, "")
            boxes[name] = {
                "indent": indent,
                "strength": strength,
                "name": name,
                "parent": parent,
                "functions": {}
            }
            last_at_indent[indent] = name
            # inline attributes on the same line after ``]:``
            tail = line[name_end + 1:]
            if tail.strip():
                for key, val in _tokenize_inline(tail):
                    _store_attr(boxes, name, key, val, colors)

        elif line.startswith('.'):        # attribute line
            if '=' in line:
                eq_pos = line.find('=')
                param_name = line[1:eq_pos].strip()
                param_string = line[eq_pos+1:].strip()
            else:
                # flag like .vertical (no value) -> set to True
                param_name = line[1:].strip()
                param_string = "True"

            # Store the attribute in the most recent box at this indent
            current_box = last_at_indent.get(indent - 1, "")
            _store_attr(boxes, current_box, param_name, param_string, colors)

        else:                             # color definition line
            if '=' in line:
                eq_pos = line.find('=')
                name = line[:eq_pos].strip()
                color_string = line[eq_pos+1:].strip()
                colors[name] = parse_ints(color_string)

        i += 1

    # If python capture never terminated, still keep what we gathered.
    if python_buf:
        python_blocks.append("\n".join(python_buf))

    # --- Group merging for shared attributes ---
    groups = defaultdict(list)
    for name in boxes:
        if '.' in name:
            prefix = name.split('.')[0]
            groups[prefix].append(name)

    for prefix, names in groups.items():
        all_keys = set()
        for name in names:
            all_keys.update(k for k in boxes[name].keys()
                            if k not in ('name', 'parent', 'indent', 'strength'))

        key_counts = {}
        key_src = {}
        for key in all_keys:
            count = 0
            src = None
            for name in names:
                if key in boxes[name]:
                    count += 1
                    src = name
            key_counts[key] = count
            if count == 1:
                key_src[key] = (src, boxes[src][key])

        for name in names:
            for key, (src, val) in key_src.items():
                if key not in boxes[name]:
                    boxes[name][key] = val

    # --- Run python integration after the whole file is understood ---
    _exec_imports(imports, ns)
    _exec_python_code(python_blocks, ns)

    return boxes, ns
