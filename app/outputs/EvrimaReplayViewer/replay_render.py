"""Software projection of recorded actor transforms, shared by the app and exports."""
from dataclasses import dataclass, field
import colorsys
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def font(size=14):
    for path in (Path('C:/Windows/Fonts/segoeui.ttf'), Path('C:/Windows/Fonts/arial.ttf')):
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            pass
    return ImageFont.load_default()


SMALL, NORMAL, LARGE = font(12), font(15), font(23)
try:
    PLAYER_NAME_FONT = ImageFont.truetype('C:/Windows/Fonts/seguisym.ttf', 15)
except OSError:
    PLAYER_NAME_FONT = NORMAL


def short_name(actor):
    return actor['name'].removeprefix('Default__').removeprefix('BP_').removesuffix('_C')


def color(guid):
    rgb = colorsys.hsv_to_rgb((guid * .61803398875) % 1, .48, .95)
    return tuple(round(v * 255) for v in rgb)


def clock(seconds):
    minutes, seconds = divmod(max(0, seconds), 60)
    hours, minutes = divmod(int(minutes), 60)
    return f'{hours:02}:{minutes:02}:{seconds:06.3f}'


@dataclass
class Camera:
    center: list = field(default_factory=lambda: [0., 0., 0.])
    yaw: float = -35
    pitch: float = 60
    span: float = 5000

    def basis(self):
        y, p = math.radians(self.yaw), math.radians(self.pitch)
        # Gateway overview: positive X is screen-right; negative Y is screen-up.
        # Reflect only screen-right, preserving north/south, height and depth.
        return ((math.cos(y), math.sin(y), 0),
                (math.sin(y) * math.sin(p), -math.cos(y) * math.sin(p), math.cos(p)),
                (-math.sin(y) * math.cos(p), math.cos(y) * math.cos(p), math.sin(p)))

    def project(self, point, width, height):
        delta = [point[i] - self.center[i] for i in range(3)]
        right, up, depth = self.basis()
        scale = min(width, height) / max(1, self.span)
        return (width / 2 + sum(a*b for a, b in zip(delta, right)) * scale,
                height / 2 - sum(a*b for a, b in zip(delta, up)) * scale,
                sum(a*b for a, b in zip(delta, depth)))

    def pan(self, dx, dy, width, height):
        right, up, _ = self.basis()
        scale = self.span / max(1, min(width, height))
        self.center = [c - dx * r * scale + dy * u * scale for c, r, u in zip(self.center, right, up)]

    def fit(self, points):
        if not points:
            return
        lo = [min(p[i] for p in points) for i in range(3)]
        hi = [max(p[i] for p in points) for i in range(3)]
        self.center = [(a+b)/2 for a, b in zip(lo, hi)]
        self.span = max(500, max(b-a for a, b in zip(lo, hi)) * 1.55)


def render(scene, seconds, camera, width=1100, height=650, anchor=-1,
           group='Dinosaurs', selected=None, show_closed=False, trails=True, mesh_guids=None,
           background=None, draw_grid=True, label_anchors=None, show_names=True):
    width, height = max(320, int(width)), max(240, int(height))
    image = Image.new('RGB', (width, height), '#101921') if background is None else background.copy()
    draw = ImageDraw.Draw(image)
    states, hidden = scene.visible_states(seconds, anchor, group, show_closed)
    project = lambda p: camera.project(p, width, height)
    step = 10 ** math.floor(math.log10(max(camera.span / 6, 1)))
    if camera.span / step > 20:
        step *= 5
    elif camera.span / step > 10:
        step *= 2
    extent = camera.span * 2
    z = camera.center[2]
    def line(a, b, fill, width=1):
        x1, y1, _ = project(a)
        x2, y2, _ = project(b)
        if max(abs(x1), abs(y1), abs(x2), abs(y2)) < 1e7:
            draw.line((x1, y1, x2, y2), fill=fill, width=width)
    for axis in ((0, 1) if draw_grid else ()):
        start = math.floor((camera.center[axis] - extent) / step) * step
        for i in range(int(extent * 2 / step) + 1):
            value = start + i * step
            if axis == 0:
                a, b = [value, camera.center[1]-extent, z], [value, camera.center[1]+extent, z]
            else:
                a, b = [camera.center[0]-extent, value, z], [camera.center[0]+extent, value, z]
            line(a, b, '#21313d')
    if trails and selected in scene.actors:
        actor = scene.actors[selected]
        earlier = None
        for sample in actor['samples']:
            if not seconds - 12 <= sample[0] <= seconds:
                continue
            if anchor >= 0 and sample[0] < scene.anchors[anchor]['seconds']:
                continue
            state = scene.state(selected, sample[0], anchor)
            if not state or state['location'] is None or state['attachment'] == 'attached':
                earlier = None
                continue
            point = state['location']
            if earlier:
                line(earlier, point, '#d8b870', 2)
            earlier = point
    hits = []
    labels = []
    projected = [(project(state['location']), state) for state in states]
    for (x, y, depth), state in sorted(projected, key=lambda item: item[0][2]):
        if not -40 <= x <= width+40 or not -40 <= y <= height+40:
            continue
        guid = state['guid']
        is_selected = guid == selected
        fill = '#ffd485' if is_selected else color(guid)
        if state['closed']:
            fill = '#657382'
        if is_selected:
            draw.ellipse((x-15, y-15, x+15, y+15), outline='#695d43', width=2)
        rotation = state['rotation']
        if guid in (mesh_guids or set()):
            pass
        elif rotation is not None:
            yaw = math.radians(rotation[1])
            nose = [state['location'][0]+math.cos(yaw)*camera.span/30,
                    state['location'][1]+math.sin(yaw)*camera.span/30, state['location'][2]]
            nx, ny, _ = project(nose)
            dx, dy = nx-x, ny-y
            length = max(1e-6, math.hypot(dx, dy))
            dx, dy = dx/length, dy/length
            polygon = [(x+dx*12, y+dy*12), (x-dx*7-dy*6, y-dy*7+dx*6),
                       (x-dx*4, y-dy*4), (x-dx*7+dy*6, y-dy*7-dx*6)]
            draw.polygon(polygon, fill=fill)
        else:
            draw.ellipse((x-5, y-5, x+5, y+5), outline=fill, width=2)
        actor = scene.actors[guid]
        if show_names and actor['dinosaur']:
            from replay_identity import display_name
            identity = scene.identities.player(guid, seconds, anchor)
            name = display_name(identity['name']) if identity['name'] else 'Name not recorded'
            detail = f"{identity['steam_id'] or 'Steam ID not recorded'} | {short_name(actor)}"
            lx, bottom = (label_anchors or {}).get(guid, (x, y-20))
            labels.append((guid, lx, bottom, name, detail))
        elif not actor['dinosaur'] and (is_selected or len(states) <= 20):
            name = f"{short_name(scene.actors[guid])} · {guid}"
            bounds = draw.textbbox((x+15, y-12), name, font=SMALL)
            draw.rectangle((bounds[0]-4, bounds[1]-3, bounds[2]+4, bounds[3]+3), fill='#101921')
            draw.text((x+15, y-12), name, fill=fill, font=SMALL)
        hits.append((x, y, guid))
    label_boxes = []
    for guid, x, bottom, name, detail in sorted(labels, key=lambda row: (row[0] != selected, row[0])):
        widths = [draw.textlength(text, font=face) for text, face in ((name, PLAYER_NAME_FONT), (detail, SMALL))]
        limit = max(80, width-24)
        while widths[0] > limit and len(name) > 1:
            name = name[:-2] + '…'
            widths[0] = draw.textlength(name, font=PLAYER_NAME_FONT)
        half = max(widths)/2 + 3
        x = min(width-half-4, max(half+4, x))
        target_x, target_bottom = x, bottom
        bottom = min(height-48, bottom)
        while True:
            overlaps = [r['box'] for r in label_boxes if x+half+5 > r['box'][0] and x-half-5 < r['box'][2]
                        and bottom+5 > r['box'][1] and bottom-37 < r['box'][3]+5]
            if not overlaps:
                break
            bottom = min(box[1] for box in overlaps)-7
        if bottom < 133:
            continue
        top = bottom-35
        if target_bottom-bottom > 8:
            draw.line((target_x,target_bottom,x,bottom+2),fill='#9facb5',width=1)
        draw.text((x, top), name, anchor='mt', font=PLAYER_NAME_FONT, fill='#ffffff', stroke_width=1, stroke_fill='#101921')
        draw.text((x, top+19), detail, anchor='mt', font=SMALL, fill='#ffffff', stroke_width=2, stroke_fill='#101921')
        label_boxes.append({'guid': guid, 'name': name, 'detail': detail, 'box': [x-half, top-2, x+half, bottom]})
    draw.rectangle((0, 0, width, 93), fill='#101921')
    draw.text((22, 16), scene.data['source'], font=LARGE, fill='#e5edf3')
    draw.text((22, 51), 'RECORDED MOTION  /  symbolic actors · no terrain or dinosaur meshes', font=SMALL, fill='#99a9b7')
    draw.text((22, 72), f'{len(hits)} in view / {len(states)} in filter  ·  grid {step:,.0f} recorded units  ·  {group}', font=SMALL, fill='#8397a7')
    label = clock(seconds)
    bounds = draw.textbbox((0, 0), label, font=LARGE)
    draw.text((width - (bounds[2]-bounds[0]) - 24, 18), label, font=LARGE, fill='#ffd485')
    draw.rectangle((0, height-42, width, height), fill='#101921')
    caption = 'Drag: orbit   ·   Right drag: pan   ·   Wheel: zoom   ·   Click: select'
    draw.text((22, height-28), caption, font=SMALL, fill='#8299aa')
    axes_origin = (width-66, height-87)
    right, up, _ = camera.basis()
    for i, (name, fill) in enumerate((('X','#e78680'),('Y','#86c599'),('Z','#80b2e7'))):
        end = (axes_origin[0]+right[i]*30, axes_origin[1]-up[i]*30)
        draw.line((*axes_origin, *end), fill=fill, width=2)
        draw.text((end[0]+2, end[1]-6), name, font=SMALL, fill=fill)
    return image, hits, {'visible': len(states), 'drawn': len(hits), 'player_labels': label_boxes, **hidden}
