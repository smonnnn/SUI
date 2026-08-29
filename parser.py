from collections import defaultdict

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

def load(layout_filename):
    with open(layout_filename, "r") as f:
        layout_lines = f.readlines()

    colors = {}
    last_at_indent = {}
    boxes = defaultdict(dict)

    for line in layout_lines:
        # Remove comments
        if '#' in line:
            line = line[:line.index('#')]
        line = line.rstrip()
        if not line:
            continue

        # Compute indent (tabs)
        stripped = line.lstrip('\t')
        indent = len(line) - len(stripped)
        line = stripped.strip()

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

        elif line.startswith('.'):        # attribute line
            if '=' in line:
                eq_pos = line.find('=')
                param_name = line[1:eq_pos].strip()
                param_string = line[eq_pos+1:].strip()
            else:
                # flag like .vertical (no value) -> set to True
                param_name = line[1:].strip()
                param_string = "True"

            # Parse the value
            if param_string.startswith('('):
                param_value = parse_ints(param_string)
            elif param_string.startswith('"'):
                param_value = param_string[1:-1]
            elif param_string in ("True", "False"):
                param_value = param_string == "True"
            elif param_string == "None":
                param_value = None
            elif param_string.isdigit():
                param_value = int(param_string)
            elif param_name.startswith("click"):
                fn_name = param_string[:param_string.find("(")]
                prms = param_string[param_string.find("(")+1:param_string.rfind(")")]
                prms = [p.strip() for p in prms.split(",") if p.strip()]
                param_value = {"function":fn_name, "params":prms}
            else:
                # Assume it's a color name; look it up
                param_value = colors.get(param_string, [0,0,0,0])

            # Store the attribute in the most recent box at this indent
            current_box = last_at_indent.get(indent-1, "")
            if current_box:
                if param_string.startswith("calc"):
                    param_value = param_string[param_string.find("(")+1:param_string.rfind(")")]
                    boxes[current_box]["functions"][param_name] = param_value
                else:
                    boxes[current_box][param_name] = param_value

        else:                             # color definition line
            if '=' in line:
                eq_pos = line.find('=')
                name = line[:eq_pos].strip()
                color_string = line[eq_pos+1:].strip()
                colors[name] = parse_ints(color_string)

    # --- Group merging for shared attributes ---
    # Group boxes by prefix before first dot
    groups = defaultdict(list)
    for name in boxes:
        if '.' in name:
            prefix = name.split('.')[0]
            groups[prefix].append(name)

    for prefix, names in groups.items():
        # Collect all attribute keys that are not structural
        all_keys = set()
        for name in names:
            all_keys.update(k for k in boxes[name].keys()
                            if k not in ('name', 'parent', 'indent', 'strength'))

        # Count occurrences of each key
        key_counts = {}
        key_src = {}  # for keys with count 1, store (source_box, value)
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

        # Apply shared attributes to all boxes in the group
        for name in names:
            for key, (src, val) in key_src.items():
                if key not in boxes[name]:  # add only if missing
                    boxes[name][key] = val
    return boxes