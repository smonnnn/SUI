from __future__ import annotations
from pyray import *
from typing import Optional, List
from dataclasses import field, dataclass
from typing import Dict, Any
from parser import load

# Start with this font size, auto resize based on confinement.
BASE_FONT_SIZE = 32
BACKGROUND = Color(202, 220, 174, 255)
FOREGROUND = Color(225, 233, 201, 255)
BUTTON = Color(237, 163, 90, 255)
BUTTON_H = Color(254, 232, 217, 255)
BORDER = Color(0, 34, 34, 255)
TEXT = BLACK

@dataclass
class Box:
    text: str = ""
    name: str = ""
    rect: Rectangle = field(default_factory=lambda: Rectangle(0, 0, 0, 0))
    color: Optional[Color] = None
    border_color: Optional[Color] = BORDER
    strength: int = 100
    hidden: bool = False
    vertical: bool = False  # False for horizontal, True for vertical.
    padding: Vector4 = field(default_factory=lambda: Vector4(0, 0, 0, 0))  # left, right, top, bottom
    margin: Vector4 = field(default_factory=lambda: Vector4(1, 1, 1, 1))  # left, right, top, bottom
    border: Vector4 = field(default_factory=lambda: Vector4(0, 0, 0, 0))  # left, right, top, bottom
    onclick: function = field(default_factory=lambda: (lambda: False))  # Default empty function, return false by default to make it transmit to paren boxes.
    onhover: function = field(default_factory=lambda: (lambda: False))
    parent: Optional[Box] = None
    children: List[Box] = field(default_factory=list)
    texture: Texture = None
    scroll: Vector2 = field(default_factory=lambda: Vector2(0, 0))
    functions: dict = field(default_factory=lambda: {})

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

def wrap_text(text, font, font_size, spacing, max_width, max_height, shrink_font=True):
    original_text = text
    wrap_chars = [" ", ".", "-"]
    
    # Outer loop: shrink font size if height exceeds max
    while True:
        text = original_text
        lines = []
        
        # Inner loop: wrap text into lines without recursion
        while text:
            # Find how much fits on one line
            nlpos = len(text)
            while nlpos > 0:
                t = text[:nlpos]
                text_size = measure_text_ex(font, t, font_size, spacing)
                if text_size.x < max_width:
                    break
                nlpos -= 1
            
            # If nothing fits, force at least one character
            if nlpos == 0:
                nlpos = 1
            
            # Look for wrap opportunity (space, dot, dash)
            wrap_pos = nlpos
            if nlpos < len(text) and nlpos > 1:
                for i, c in enumerate(reversed(text[:nlpos])):
                    if c in wrap_chars:
                        wrap_pos = nlpos - i
                        break
            
            # Add line
            lines.append(text[:wrap_pos])
            text = text[wrap_pos:].lstrip()  # Remove leading spaces from next line
        
        # Join lines and check height
        wrapped_text = "\n".join(lines)
        text_size = measure_text_ex(font, wrapped_text, font_size, spacing)
        
        # Check if height fits or can't shrink further
        if text_size.y <= max_height or font_size <= 1 or not shrink_font:
            return (wrapped_text, font_size)
        
        # Shrink font and try again
        font_size -= 1

def draw(box: Box):
    apply_functions(box)
    if box.parent is None:
        box.rect.x = 0
        box.rect.y = 0
        box.rect.width = get_screen_width()
        box.rect.height = get_screen_height()
    
    inner_x = box.rect.x + box.padding.x
    inner_y = box.rect.y + box.padding.z
    inner_w = box.rect.width - box.padding.x - box.padding.y
    inner_h = box.rect.height - box.padding.z - box.padding.w
    
    # Available space AFTER subtracting all children's margins
    total_margin_w = sum((c.margin.x + c.margin.y) if not (eval(c.hidden) if isinstance(c.hidden, str) else c.hidden) else 0 for c in box.children)
    total_margin_h = sum((c.margin.z + c.margin.w) if not (eval(c.hidden) if isinstance(c.hidden, str) else c.hidden) else 0 for c in box.children)
    
    available_w = inner_w - total_margin_w
    available_h = inner_h - total_margin_h
    
    divisor = sum(c.strength if not (eval(c.hidden) if isinstance(c.hidden, str) else c.hidden) else 0 for c in box.children)
    offset = 0.0
    
    for c in box.children:
        apply_functions(c)
        if not c.color and not c.border_color or (eval(c.hidden) if isinstance(c.hidden, str) else c.hidden):
            continue
        
        fraction = c.strength / divisor if divisor > 0 else 0

        v = box.vertical 
        if isinstance(box.vertical, str):
            v = eval(box.vertical)

        if v:
            # Height includes top+bottom margins, so we subtract them for the rect
            allocated_h = (available_h * fraction) + c.margin.z + c.margin.w
            
            c.rect.x = inner_x + c.margin.x
            c.rect.y = inner_y + offset + c.margin.z
            c.rect.width = inner_w - c.margin.x - c.margin.y
            c.rect.height = allocated_h - c.margin.z - c.margin.w  # net height
            
            offset += allocated_h  # ← includes margins!
        else:
            # Width includes left+right margins
            allocated_w = (available_w * fraction) + c.margin.x + c.margin.y
            
            c.rect.x = inner_x + offset + c.margin.x
            c.rect.y = inner_y + c.margin.z
            c.rect.width = allocated_w - c.margin.x - c.margin.y
            c.rect.height = inner_h - c.margin.z - c.margin.w
            
            offset += allocated_w
        

        # Draw border and fill (unchanged) DEBUG_STUFF
        if c is hovering or c is selected:
            bc = ORANGE if c is hovering else RED
            draw_rectangle(int(c.rect.x - 1), int(c.rect.y - 1), 
                         int(c.rect.width + 2), int(c.rect.height + 2), bc)
        if c.border_color and c.color:
            draw_rectangle(int(c.rect.x), int(c.rect.y), 
                         int(c.rect.width), int(c.rect.height), c.border_color)
        x = int(c.rect.x + c.border.x)
        y = int(c.rect.y + c.border.z)
        w = int(c.rect.width - c.border.x - c.border.y)
        h = int(c.rect.height - c.border.z - c.border.w)
        if c.color:
            draw_rectangle(x, y, w, h, c.color)
        
        if c.texture:
            source = Rectangle(c.scroll.x, c.scroll.y, w, h)
            begin_scissor_mode(x, y, w, h)
            draw_texture_rec(c.texture, source, x, y, WHITE)
            end_scissor_mode()

        text, font_size = wrap_text(c.text, get_font_default(), BASE_FONT_SIZE, 2.5, w, h)
        if len(text) > 0: 
            begin_scissor_mode(x, y, w, h)
            draw_text(text, x, y, font_size, BLACK)
            end_scissor_mode()

def is_child_of(box:Box, pparent:Box):
    while box and box is not pparent:
        box = box.parent
    return box is None

def click(box:Box):
    while box and not box.onclick():
        box = box.parent

def hover(box:Box, until:Box):
    while box and not (box is until) and not box.onhover():
        box = box.parent

def trace_mouse(box: Box) -> Optional[Box]:
    mouse_pos = get_mouse_position()
    hover = (box.rect.x <= mouse_pos.x <= (box.rect.x + box.rect.width) and 
             box.rect.y <= mouse_pos.y <= (box.rect.y + box.rect.height))
    if not hover: 
        return None
    for c in box.children:
        if (eval(c.hidden) if isinstance(c.hidden, str) else c.hidden): continue
        r = trace_mouse(c)
        if r: 
            return r
    return box

def parse_color(value):
    """Convert a list or tuple of ints to a Color, or return None."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        if len(value) >= 4:
            return Color(value[0], value[1], value[2], value[3])
        elif len(value) == 3:
            return Color(value[0], value[1], value[2], 255)
    return None

def parse_vector4(value):
    """Convert a single int or a list of 4 ints to a Vector4."""
    if value is None:
        return None
    if isinstance(value, int):
        return Vector4(value, value, value, value)
    if isinstance(value, (list, tuple)) and len(value) == 4:
        return Vector4(value[0], value[1], value[2], value[3])
    return None

def dict_to_box(box_dict: Dict[str, Any]) -> Box:
    """Convert a dictionary to a Box object."""
    box = Box()
    # Basic properties
    box.strength = box_dict.get('strength', 100)
    box.text = box_dict.get('text', '')
    box.hidden = box_dict.get('hidden', False)
    box.name = box_dict.get("name", "")
    box.functions = box_dict.get("functions", {})

    # Handle horizontal/vertical
    if 'horizontal' in box_dict:
        box.vertical = not box_dict['horizontal']
    if 'vertical' in box_dict:
        box.vertical = box_dict['vertical']

    # Colors
    if 'color' in box_dict:
        box.color = parse_color(box_dict['color'])
    if 'border_color' in box_dict:
        box.border_color = parse_color(box_dict['border_color'])

    # Vectors
    if 'padding' in box_dict:
        v = parse_vector4(box_dict['padding'])
        if v:
            box.padding = v
    if 'margin' in box_dict:
        v = parse_vector4(box_dict['margin'])
        if v:
            box.margin = v
    if 'border' in box_dict:
        v = parse_vector4(box_dict['border'])
        if v:
            box.border = v

    if 'click' in box_dict:
        box.onclick = lambda: set_children(*[boxes.get(n) for n in box_dict['click']["params"]])

    return box

def apply_functions(box:Box):
    for fnname, fn in box.functions.items():
        res = eval(fn)
        if fnname == "click": fnname = "onclick"
        if fnname == "hover": fnname = "onhover"
        if fnname == "horizontal": 
            fnname = "vertical"
            res = not res        
        if fnname in ["padding", "margin", "border"]:
            res = parse_vector4(res)
        setattr(box, fnname, res)

def build_box_hierarchy(boxes_dict: Dict[str, Dict]) -> Dict[str, Box]:
    """Convert all dicts to Box objects, apply default inheritance, and link parent-child."""
    # Separate default box if it exists
    default_dict = boxes_dict.pop("default", {}).copy()
    # Remove keys that should not be inherited
    default_dict.pop("strength", None)
    default_dict.pop("name", None)
    default_dict.pop("parent", None)
    default_dict.pop("indent", None)

    box_objects = {}
    # First pass: create boxes, merging with default
    for name, d in boxes_dict.items():
        merged = default_dict.copy()
        merged.update(d)
        box = dict_to_box(merged)
        # Store the original name if needed (optional)
        box.name = name  # add name attribute dynamically
        box_objects[name] = box

    # Second pass: link children
    for name, d in boxes_dict.items():
        parent_name = d.get('parent', '')
        if parent_name and parent_name in box_objects:
            add_children(box_objects[parent_name], box_objects[name])

    return box_objects

boxes = load("./sui/test_layout_2.txt")
boxes = build_box_hierarchy(boxes)
root = boxes["root"]

# Initialize window
set_config_flags(ConfigFlags.FLAG_WINDOW_RESIZABLE)
init_window(800, 450, "Bombus")
fps = 180
set_target_fps(fps)

hovering = root
selected = root

i = 0
while not window_should_close():
    i+=1
    seconds = i / fps
    begin_drawing()
    clear_background(WHITE)
    height = get_screen_height()
    width = get_screen_width()
    ratio = width / height

    apply(root, [draw])
    h = trace_mouse(root)
    if h is not hovering:  # Should be done with some sort of hover stack, only triggering the new ones.
        if not is_child_of(h, hovering):
            hover(h, hovering)
        hovering = h
    if is_mouse_button_pressed(MouseButton.MOUSE_BUTTON_LEFT): 
        selected = hovering
        click(selected)
    end_drawing()
close_window()