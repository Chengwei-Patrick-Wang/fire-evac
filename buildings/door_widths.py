"""Report clear door widths and the corresponding walkable cuts."""
import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import median

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union


def leaves(operation):
    operation = operation or ''
    if operation.startswith('DOUBLE_DOOR_'):
        return 2
    if operation.startswith(('SINGLE_SWING_', 'DOUBLE_SWING_')):
        return 1
    return 0


def clear_width(overall, operation, thickness):
    return overall - leaves(operation) * (0.05 if thickness is None else thickness)


def cut_width(floor, door):
    a, b = door['a'], door['b']
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = (dx * dx + dy * dy) ** 0.5
    ux, uy = dx / length, dy / length
    center = Polygon(door['rect']).centroid
    walk = unary_union([Polygon(p['outer'], p.get('holes', [])) for p in floor['walkable']])
    widths = []
    for offset in (-0.02, 0, 0.02):
        x, y = center.x - uy * offset, center.y + ux * offset
        line = LineString([(x - ux * (length / 2 + 1), y - uy * (length / 2 + 1)),
                           (x + ux * (length / 2 + 1), y + uy * (length / 2 + 1))])
        clipped = walk.intersection(line)
        pieces = list(clipped.geoms) if hasattr(clipped, 'geoms') else [clipped]
        widths.append(max((p.length for p in pieces if p.distance(Point(x, y)) < 1e-7), default=0.0))
    return min(widths)


def door_report(building):
    return [{'floor': f['id'], 'id': d['id'], 'name': d.get('name', ''),
             'leaves': d.get('leaves', 0), 'overall': d.get('overallWidth', d['width']),
             'width': d['width'], 'cut': cut_width(f, d)}
            for f in building['floors'] for d in f['doors']]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('buildings', nargs='+', type=Path)
    for path in parser.parse_args().buildings:
        building = json.loads(path.read_text(encoding='utf-8'))
        rows = door_report(building)
        counts = Counter((round(r['overall'], 2), round(r['width'], 2), round(r['cut'], 2)) for r in rows)
        print(f'{path}:\noverall width cut count')
        for values, count in sorted(counts.items()):
            print(' '.join(f'{v:.2f}' for v in values), count)
        interior = {d['id'] for f in building['floors'] for d in f['doors'] if 'outside' not in d['connects']}
        diffs = [r['cut'] - r['width'] for r in rows if r['id'] in interior]
        if diffs:
            print(f'interior cut - width: median {median(diffs):.3f} m, maximum {max(diffs):.3f} m')


if __name__ == '__main__':
    main()
