"""Build a deterministic public index of normalized buildings."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from shapely.geometry import Polygon


def vertex_count(floor: dict) -> int:
    return sum(len(piece['outer']) + sum(map(len, piece.get('holes', [])))
               for piece in floor['walkable'])


def summarize(building: dict, file: str) -> dict:
    path = Path(file)
    floors = building['floors']
    per_floor = []
    points = []
    total_area = 0.0
    groups = set()
    for floor in floors:
        area = sum(Polygon(p['outer'], p.get('holes', [])).area for p in floor['walkable'])
        total_area += area
        points.extend(point for p in floor['walkable'] for point in p['outer'])
        groups.update(s['group'] for s in floor['stairs'])
        per_floor.append({'id': floor['id'], 'level': floor['level'],
                          'rooms': len(floor['rooms']), 'doors': len(floor['doors']),
                          'exits': len(floor['exits']), 'stairs': len(floor['stairs']),
                          'walkableArea': round(area, 1), 'vertices': vertex_count(floor)})
    size = ([round(max(p[i] for p in points) - min(p[i] for p in points), 1)
             for i in (0, 1)] if points else [0.0, 0.0])
    scenario = path.with_name(path.stem + '.scenario.json')
    credits = building.get('credits', '')
    return {'id': building['id'], 'name': building.get('name', building['id']),
            'source': building.get('source'), 'credits': credits,
            'shortCredit': credits.split(';', 1)[0].strip(), 'file': path.name,
            'scenario': scenario.name if scenario.is_file() else None,
            'floors': len(floors),
            'rooms': sum(len(f['rooms']) for f in floors),
            'doors': sum(len(f['doors']) for f in floors),
            'exits': sum(len(f['exits']) for f in floors),
            'stairGroups': sorted(groups), 'walkableArea': round(total_area, 1),
            'vertices': sum(vertex_count(f) for f in floors), 'size': size,
            'perFloor': per_floor}


def _private(path: Path) -> bool:
    return any('private' in part.lower() for part in path.resolve().parts)


def build_index(folder: Path = Path('data/buildings')) -> dict:
    folder = Path(folder)
    buildings = []
    for path in sorted(folder.glob('*.json'), key=lambda p: p.name):
        if _private(path):
            print(f'Skipping {path}: private path')
            continue
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        if data.get('version') != 'building/v0' or data.get('private') is True:
            print(f'Skipping {path}: not a public building/v0')
            continue
        buildings.append(summarize(data, str(path)))
        print(f"{path.name}: {data['id']}")
    return {'version': 'buildings-index/v0', 'buildings': buildings}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', nargs='?', type=Path, default=Path('data/buildings'))
    parser.add_argument('--out', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if _private(args.folder):
        parser.exit(1, f'Refusing private folder: {args.folder}\n')
    output = args.out or args.folder / 'index.json'
    contents = json.dumps(build_index(args.folder), indent=1) + '\n'
    if args.check:
        if not output.is_file() or output.read_text(encoding='utf-8') != contents:
            print(f'{output} is stale: run python -m buildings.summary')
            return 1
    else:
        output.write_text(contents, encoding='utf-8', newline='\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
