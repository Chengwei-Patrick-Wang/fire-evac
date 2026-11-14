"""Inspect compact run JSON; hold encoding is opt-in until replay supports it."""
import argparse
from copy import deepcopy
import json
import math
from pathlib import Path


def _bytes(value):
    return len(json.dumps(value, separators=(',', ':')).encode('utf-8'))


def size_report(run):
    parts = {key: _bytes(run.get(key, [])) for key in ('frames', 'smoke', 'events', 'agents')}
    total = _bytes(run)
    parts['other'] = total - sum(parts.values())
    previous = {}
    rows = status0 = repeats = 0
    for frame in run['frames']:
        current = {row[0]: row for row in frame['a']}
        for row in frame['a']:
            rows += 1
            status0 += row[4] == 0
            repeats += previous.get(row[0]) == row
        previous = current
    return dict(mb=round(total / 1e6, 3),
                parts={key: round(value / 1e6, 3) for key, value in parts.items()},
                rows=rows, status0Rows=status0, repeatRows=repeats,
                frames=len(run['frames']),
                smokeFrames=sum(len(s['frames']) for s in run.get('smoke', [])))


def rounding_problems(run):
    problems = []
    def coordinate(value, label):
        if value == 0 and math.copysign(1, value) < 0:
            problems.append(f'{label}: -0.0')
        elif not math.isfinite(value) or abs(value - round(value, 2)) > 1e-9:
            problems.append(f'{label}: off 0.01 grid ({value})')
    interval = run.get('frameInterval', 0.5)
    for i, frame in enumerate(run['frames']):
        # The final empty frame records completion, possibly between samples.
        if not (i == len(run['frames']) - 1 and not frame['a']):
            if abs(frame['t'] / interval - round(frame['t'] / interval)) > 1e-8:
                problems.append(f'frame {i}: time off frameInterval grid')
        for row in frame['a']:
            for key, value in zip(('x', 'y'), row[1:3]):
                coordinate(value, f'frame {i} agent {row[0]} {key}')
    for i, event in enumerate(run.get('events', [])):
        for key in ('t', 'enter', 'arrive', 'until', 'x', 'y'):
            if key in event:
                coordinate(event[key], f'event {i} {key}')
    return problems


def thin_frames(run):
    """Omit unchanged status-0 rows; all moving/transit rows remain explicit.

    Valid run/v0 frames are idx-sorted and agents disappear on exit/trapping.
    The marker must be handled by consumers before using these files.
    """
    result = deepcopy(run)
    if result.get('frameHold'):
        return result
    previous = {}
    for frame in result['frames']:
        rows = frame['a']
        frame['a'] = [row for row in rows if row[4] != 0 or previous.get(row[0]) != row]
        previous = {row[0]: row for row in rows}
    result['frameHold'] = True
    return result


def expand_frames(run):
    result = deepcopy(run)
    if not result.pop('frameHold', False):
        return result
    terminal = sorted((e['t'], e['idx']) for e in result.get('events', [])
                      if e['type'] in ('exit', 'trapped'))
    cursor = 0
    held = {}
    for frame in result['frames']:
        while cursor < len(terminal) and terminal[cursor][0] <= frame['t']:
            held.pop(terminal[cursor][1], None)
            cursor += 1
        for row in frame['a']:
            held.pop(row[0], None)
            if row[4] == 0:
                held[row[0]] = row
        explicit = {row[0]: row for row in frame['a']}
        frame['a'] = [deepcopy(row) for _, row in sorted((held | explicit).items())]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--thin', type=Path)
    args = parser.parse_args()
    run = json.loads(args.run.read_text(encoding='utf-8'))
    print(json.dumps(size_report(run)))
    print(json.dumps({'roundingProblems': rounding_problems(run)}))
    if args.thin:
        thin = thin_frames(run)
        args.thin.write_text(json.dumps(thin, separators=(',', ':')), encoding='utf-8')
        print(json.dumps(size_report(thin)))


if __name__ == '__main__':
    main()
