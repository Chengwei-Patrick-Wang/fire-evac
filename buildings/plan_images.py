"""Draw scale-preserving plan images and a reusable tracer example."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import Polygon
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/buildings/plans'


def layout(building, px_per_m, margin=3.0):
    bounds = unary_union([Polygon(r['polygon']) for f in building['floors'] for r in f['rooms']]).bounds
    x0, y0, x1, y1 = bounds
    w = math.ceil((x1 - x0 + 2 * margin) * px_per_m)
    h = math.ceil((y1 - y0 + 2 * margin) * px_per_m)
    origin = [(margin - x0) * px_per_m, h - (margin - y0) * px_per_m]
    bar = [margin * px_per_m, h - px_per_m]
    return {'pxPerM': px_per_m, 'width': w, 'height': h, 'origin': origin,
            'scaleBar': {'p1': bar, 'p2': [bar[0] + 10 * px_per_m, bar[1]], 'meters': 10}}


def _px(p, rec):
    return [p[0] * rec['pxPerM'] + rec['origin'][0], rec['origin'][1] - p[1] * rec['pxPerM']]


def _draw_shape(draw, shape, rec, fill):
    if shape.is_empty:
        return
    if shape.geom_type == 'Polygon':
        draw.polygon([tuple(_px(p, rec)) for p in shape.exterior.coords], fill=fill)
        for ring in shape.interiors:
            draw.polygon([tuple(_px(p, rec)) for p in ring.coords], fill=255 if fill == 0 else 0)
    elif hasattr(shape, 'geoms'):
        for part in shape.geoms:
            _draw_shape(draw, part, rec, fill)


def render_floor(building, floor_id, out, px_per_m):
    rec = layout(building, px_per_m)
    rec.update(file=Path(out).name, building=building['id'], floor=floor_id)
    f = next(f for f in building['floors'] if f['id'] == floor_id)
    image = Image.new('RGB', (rec['width'], rec['height']), 'white')
    rooms = unary_union([Polygon(r['polygon']) for r in f['rooms']])
    walk = unary_union([Polygon(p['outer'], p['holes']) for p in f['walkable']])
    walls = rooms.buffer(0.2 if building.get('source') == 'ifc' else 0.1, join_style='mitre').difference(walk)
    mask = Image.new('L', image.size, 255)
    _draw_shape(ImageDraw.Draw(mask), walls, rec, 0)
    image.paste(Image.merge('RGB', (mask, mask, mask)))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=max(10, round(px_per_m * .35)))
    for room in f['rooms']:
        poly = Polygon(room['polygon'])
        if room['type'] == 'stair':
            hatch = Image.new('L', image.size, 0)
            ImageDraw.Draw(hatch).polygon([tuple(_px(p, rec)) for p in room['polygon']], fill=255)
            lines = Image.new('RGB', image.size, 'white')
            ld = ImageDraw.Draw(lines)
            step = max(2, round(.3 * px_per_m))
            for x in range(-rec['height'], rec['width'], step):
                ld.line((x, rec['height'], x + rec['height'], 0), fill='#bbbbbb', width=1)
            # Preserve the black walls under the hatch.
            from PIL import ImageChops
            hatch = ImageChops.multiply(hatch, mask)
            image.paste(lines, (0, 0), hatch)
            draw = ImageDraw.Draw(image)
        name = room.get('name', '')
        x0, y0, x1, y1 = poly.bounds
        box = draw.textbbox((0, 0), name, font=font)
        if box[2] - box[0] <= (x1 - x0) * px_per_m * .9:
            c = poly.representative_point()
            draw.text(tuple(_px((c.x, c.y), rec)), name, fill='black', font=font, anchor='mm')
    x, y = rec['scaleBar']['p1']
    for i in range(10):
        draw.rectangle((x+i*px_per_m, y-5, x+(i+1)*px_per_m, y+5), fill='black' if i % 2 == 0 else 'white', outline='black')
    for i, label in ((0, '0'), (5, '5'), (10, '10 m')):
        draw.text((x+i*px_per_m, y+8), label, fill='black', font=font, anchor='mt')
    title = f"{building['name']} - {floor_id} - 1 m = {px_per_m} px"
    draw.text((8, 5), title, fill='black', font=font)
    if building['id'] == 'office':
        index = json.loads((ROOT / 'data/buildings/index.json').read_text(encoding='utf-8'))
        credit = next(b['shortCredit'] for b in index['buildings'] if b['id'] == 'office')
        draw.text((8, 8 + round(px_per_m * .45)), credit, fill='black', font=font)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    image.save(out, optimize=True)
    return rec


def make_trace(building, records):
    floors = []
    for f in building['floors']:
        rec = next(r for r in records if r['building'] == building['id'] and r['floor'] == f['id'])
        rooms = []
        for r in f['rooms']:
            room = {k: r[k] for k in ('id', 'name', 'type')}
            room['polygon'] = [_px(p, rec) for p in r['polygon']]
            if r.get('group'):
                room['group'] = r['group']
            rooms.append(room)
        doors = []
        for d in f['doors']:
            door = {'id': d['id'], 'a': _px(d['a'], rec), 'b': _px(d['b'], rec),
                    'fireDoor': d['fireDoor'], 'state': d['state']}
            if 'outside' in d['connects'] and d.get('name'):
                door['name'] = d['name']
            doors.append(door)
        floors.append({'id': f['id'], 'name': f['id'], 'level': f['level'], 'imageW': rec['width'],
                       'imageH': rec['height'], 'scale': rec['scaleBar'], 'ref': rec['origin'],
                       'rooms': rooms, 'doors': doors})
    return {'version': 'trace/v0', 'id': 'example-traced', 'name': 'Example office (traced)',
            'credits': building['credits'], 'floors': floors}


def trace_to_plan(trace):
    placed = []
    for f in sorted(trace['floors'], key=lambda f: f['level']):
        s = f['scale']['meters'] / math.dist(f['scale']['p1'], f['scale']['p2'])
        def convert(p):
            return [(p[0] - f['ref'][0]) * s, (f['ref'][1] - p[1]) * s]
        rooms = []
        for r in f['rooms']:
            poly = []
            for p in r['polygon']:
                p = [math.floor(v / .25 + .5) * .25 for v in convert(p)]
                if not poly or poly[-1] != p:
                    poly.append(p)
            if len(poly) > 1 and poly[0] == poly[-1]:
                poly.pop()
            rooms.append((r, poly))
        placed.append((f, rooms, [(d, convert(d['a']), convert(d['b'])) for d in f['doors']]))
    points = [p for _, rooms, _ in placed for _, poly in rooms for p in poly]
    minx = min((p[0] for p in points), default=0)
    miny = min((p[1] for p in points), default=0)
    def r3(v): return math.floor(v * 1000 + .5) / 1000
    def shift(p): return [r3(p[0] - minx), r3(p[1] - miny)]
    floors, nr, nd = [], 0, 0
    types = {'office','classroom','kitchen','dining','lounge','bedroom','lab','storage','restroom','corridor','lobby','stair','other'}
    for k, (f, rooms, doors) in enumerate(placed):
        pf = {'id': f['id'].strip() or f'F{k+1}', 'level': f['level'], 'elevation': f['level'] * 3.5, 'height': 3.5, 'rooms': [], 'doors': []}
        for r, poly in rooms:
            nr += 1
            kind = r['type'] if r['type'] in types else 'other'
            room = {'id': f'R{nr}', 'name': r.get('name', '').strip() or f'R{nr}', 'type': kind, 'polygon': [shift(p) for p in poly]}
            if kind == 'stair' and r.get('group', '').strip(): room['group'] = r['group'].strip()
            pf['rooms'].append(room)
        for d, a, b in doors:
            nd += 1
            a, b = shift(a), shift(b)
            door = {'id': f'D{nd}', 'a': a, 'b': b, 'width': r3(math.dist(a, b)), 'fireDoor': bool(d.get('fireDoor')), 'state': d.get('state') if d.get('state') in ('closed', 'propped') else 'open'}
            if d.get('name', '').strip(): door['name'] = d['name'].strip()
            pf['doors'].append(door)
        floors.append(pf)
    return {'version': 'plan/v0', 'id': trace['id'].strip(), 'name': trace['name'].strip() or trace['id'].strip(), 'source': 'trace', 'credits': trace['credits'].strip(), 'floors': floors}


def build(draw=False):
    example = json.loads((ROOT / 'contracts/building.example.json').read_text(encoding='utf-8'))
    office = json.loads((ROOT / 'data/buildings/office.json').read_text(encoding='utf-8'))
    records = []
    for b, prefix, ppm in ((example, 'example', 40), (office, 'office', 30)):
        for f in b['floors']:
            name = f"{prefix}-{f['id']}.png"
            if draw:
                rec = render_floor(b, f['id'], OUT / name, ppm)
            else:
                rec = layout(b, ppm)
                rec.update(file=name, building=b['id'], floor=f['id'])
            records.append(rec)
    trace = make_trace(example, records)
    return {'example.trace.json': trace, 'example.plan.json': trace_to_plan(trace),
            'index.json': {'version': 'plan-images/v0', 'images': records, 'traces': [{'trace': 'example.trace.json', 'plan': 'example.plan.json'}]}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    data = build(draw=not args.check)
    if args.check:
        bad = [name for name, value in data.items() if not (OUT / name).exists() or json.loads((OUT / name).read_text(encoding='utf-8')) != value]
        if bad:
            print('run python -m buildings.plan_images:', ', '.join(bad))
            return 1
    else:
        for name, value in data.items():
            (OUT / name).write_text(json.dumps(value, indent=1) + '\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
