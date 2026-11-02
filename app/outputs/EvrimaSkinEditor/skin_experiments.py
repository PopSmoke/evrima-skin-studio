"""Small, deterministic skin experiments. No assets, graphics, or disk cache."""
import copy
import math
import random
from skin_document import SLOTS, raw_number, validate

MAX_RESULTS = 24
STYLES = ('Subtle variations', 'Negative cutouts', 'Opposing extremes')
SWEEP_MODES = ('Single section', 'Same shader together', 'Choose sections together', 'Two-section grid')
BODY_SECTIONS = ('md', 'm', 'b', 'f', 'u', 'd')


def shader_sections(section):
    if section not in SLOTS: raise ValueError('Choose a color section.')
    # SkinAssets.body_texture feeds these six slots into the decoded body
    # color kernel; eye_texture evaluates a separate material. Sharing a kernel
    # does not establish overlapping masks in every species/pattern/sex/growth.
    return ('e',) if section == 'e' else BODY_SECTIONS


def active_channels(locks, section, channels):
    if section not in SLOTS or not channels or any(type(c) is not int or c not in (0,1,2) for c in channels):
        raise ValueError('Choose a section and at least one RGB channel.')
    return [c for c in dict.fromkeys(channels) if not locks[section][c]]


def sweep_values(values):
    if not 1 <= len(values) <= MAX_RESULTS or not all(type(v) in (int,float) and math.isfinite(v) for v in values):
        raise ValueError(f'Use 1–{MAX_RESULTS} finite sweep values.')
    return list(dict.fromkeys(values))


def linked_sweep(source, locks, sections, channels, values):
    """Assign each value to unlocked channels across selected body sections."""
    validate(source); checked_locks(locks)
    sections = list(dict.fromkeys(sections))
    if not sections: raise ValueError('Select at least one section to sweep.')
    group = shader_sections(sections[0])
    if any(s not in group for s in sections):
        raise ValueError('Eyes use a separate material. Choose body sections together or eyes alone.')
    active = {s: active_channels(locks,s,channels) for s in sections}
    active = {s: cs for s,cs in active.items() if cs}
    if not active: raise ValueError('The selected channels are locked in every chosen section.')
    rows=[]
    for i,value in enumerate(sweep_values(values),1):
        colors=copy.deepcopy(source['colors'])
        for s,cs in active.items():
            for c in cs: colors[s][c]=value
        description=' + '.join(s+' '+''.join('XYZ'[c] for c in cs) for s,cs in active.items())+' = '+repr(value)
        doc=finish(source,colors,f'{source["name"]} Linked Sweep {i:02d}')
        doc['import_notes'].append('Linked value sweep: '+description)
        rows.append((description,doc))
    return rows


def paired_sweep(source, locks, section, channels, values, companion, companion_channels, companion_values):
    """Every A×B value combination; one A value gives a held-section sweep."""
    validate(source); checked_locks(locks)
    if companion == section or companion not in shader_sections(section):
        raise ValueError('Choose two different sections in the same material. Eyes have no body-shader partner.')
    first=active_channels(locks,section,channels);second=active_channels(locks,companion,companion_channels)
    if not first or not second:
        raise ValueError('Each section in a grid needs at least one unlocked selected channel.')
    values=sweep_values(values);companion_values=sweep_values(companion_values)
    total=len(values)*len(companion_values)
    if total>MAX_RESULTS:
        raise ValueError(f'This grid has {len(values)} × {len(companion_values)} = {total} results. Reduce the lists to at most {MAX_RESULTS} combinations; use one value to hold a section fixed.')
    rows=[]
    for a in values:
        for b in companion_values:
            colors=copy.deepcopy(source['colors'])
            for c in first:colors[section][c]=a
            for c in second:colors[companion][c]=b
            description=f'{section} '+''.join('XYZ'[c] for c in first)+' = '+repr(a)+f'; {companion} '+''.join('XYZ'[c] for c in second)+' = '+repr(b)
            doc=finish(source,colors,f'{source["name"]} Pair Sweep {len(rows)+1:02d}')
            doc['import_notes'].append('Two-section value grid: '+description)
            rows.append((description,doc))
    return rows
DEFAULT_SWEEP = '-1e30, -1e22, -1e18, -999999999, -9999999, -999, -1, 0, 0.004, 0.35, 1, 8, 9999999, 1e18, 1e30'


def default_locks():
    return {s: [s == 'e'] * 3 for s in SLOTS}


def prepare_source(doc, defaults):
    result = copy.deepcopy(validate(doc))
    # Freeze what original-eyes actually displays, including partially locked eyes.
    if result['default_eyes']:
        result['colors']['e'] = list(defaults['e'])
    return result


def checked_locks(locks):
    if set(locks) != set(SLOTS) or any(len(row) != 3 or any(type(v) is not bool for v in row) for row in locks.values()):
        raise ValueError('Locks must specify X, Y and Z for each section.')
    return locks


def finish(source, colors, name):
    result = copy.deepcopy(source)
    result['name'] = name
    result['colors'] = colors
    if colors['e'] != source['colors']['e']:
        result['default_eyes'] = False
    result['import_notes'] = list(result.get('import_notes', [])) + ['Experiment Lab: decoded preview only; live-game appearance is unverified.']
    return validate(result)


def parse_sweep(text):
    tokens = text.replace('\n', ',').split(',')
    if not 1 <= len(tokens) <= MAX_RESULTS:
        raise ValueError(f'Enter 1–{MAX_RESULTS} comma-separated values.')
    values = [raw_number(t) for t in tokens]
    return list(dict.fromkeys(values))


def sweep(source, locks, section, channels, values):
    validate(source); checked_locks(locks)
    if section not in SLOTS or not channels or any(c not in (0, 1, 2) for c in channels):
        raise ValueError('Choose a section and at least one RGB channel.')
    active = [c for c in channels if not locks[section][c]]
    if not active:
        raise ValueError('The selected channels are locked. Unlock one to run this sweep.')
    if not 1 <= len(values) <= MAX_RESULTS:
        raise ValueError(f'Use at most {MAX_RESULTS} sweep values.')
    rows = []
    for i, value in enumerate(dict.fromkeys(values), 1):
        if not math.isfinite(value):
            raise ValueError('Sweep values must be finite.')
        colors = copy.deepcopy(source['colors'])
        for c in active: colors[section][c] = value
        doc = finish(source, colors, f'{source["name"]} Sweep {i:02d}')
        rows.append((f'{section} {"".join("XYZ"[c] for c in active)} = {value:g}', doc))
    return rows


def variations(source, locks, count=12, seed=2026, style=STYLES[1], minimum=6, maximum=22, amount=25, scope='2–3 sections'):
    validate(source); checked_locks(locks)
    if type(count) is not int or not 1 <= count <= MAX_RESULTS:
        raise ValueError(f'Choose between 1 and {MAX_RESULTS} variations.')
    if type(seed) is not int or style not in STYLES:
        raise ValueError('Choose a style and a whole-number seed.')
    if not math.isfinite(amount) or not 0 < amount <= 100:
        raise ValueError('Subtle change amount must be greater than 0 and at most 100%.')
    if not all(type(x) is int for x in (minimum, maximum)) or not -12 <= minimum <= maximum <= 30:
        raise ValueError('Magnitude powers must be whole numbers from -12 to 30, with minimum ≤ maximum.')
    if scope not in ('One section', '2–3 sections', 'All unlocked'):
        raise ValueError('Choose how many sections to vary.')
    unlocked = {s: [c for c in range(3) if not locks[s][c]] for s in SLOTS}
    available = [s for s, channels in unlocked.items() if channels]
    if not available:
        raise ValueError('Everything is locked. Unlock at least one channel.')
    rng = random.Random(seed); rows = []; seen = {tuple(v for s in SLOTS for v in source['colors'][s])}
    for attempt in range(count * 50):
        colors = copy.deepcopy(source['colors'])
        n = 1 if scope == 'One section' else len(available) if scope == 'All unlocked' else min(len(available), rng.randint(2, 3))
        sections = rng.sample(available, n)
        for index, s in enumerate(sections):
            magnitude = 10. ** rng.uniform(minimum, maximum)
            for c in unlocked[s]:
                old = colors[s][c]
                if style == STYLES[0]:
                    delta = rng.uniform(-amount, amount) / 100
                    value = old * (1 + delta) if abs(old) > 1e-12 else old + delta * .05
                elif style == STYLES[1]:
                    value = -magnitude if index == 0 else magnitude * rng.choice((.004, .04, .35, 1.))
                else:
                    value = rng.choice((-1., 1.)) * magnitude * rng.choice((.004, .125, .5, 1.))
                if not math.isfinite(value):
                    raise ValueError('This variation exceeds finite storage. Reduce the amount or source magnitude.')
                colors[s][c] = value
        key = tuple(v for s in SLOTS for v in colors[s])
        if key in seen: continue
        seen.add(key)
        index = len(rows) + 1
        doc = finish(source, colors, f'{source["name"]} Variant {index:02d}')
        rows.append((f'Variant {index:02d} · {", ".join(sections)}', doc))
        if len(rows) == count: return rows
    raise ValueError('Too few distinct numeric results. Unlock more channels or widen the range.')


def compare_images(image, baseline, prior):
    """Fixed-camera picture comparison; not UV coverage or an in-game claim."""
    import hashlib
    import numpy as np
    a = np.asarray(image.convert('RGB'), dtype=np.int16)
    b = np.asarray(baseline.convert('RGB'), dtype=np.int16)
    if a.shape != b.shape: raise ValueError('Comparison pictures must have matching dimensions.')
    bg = np.median([b[0, 0], b[0, -1], b[-1, 0], b[-1, -1]], axis=0)
    mask = (np.max(abs(a-bg), axis=2) > 6) | (np.max(abs(b-bg), axis=2) > 6)
    changed = (np.max(abs(a-b), axis=2) > 8) & mask
    digest = hashlib.sha256(image.tobytes()).hexdigest()
    same = next((label for label, old in prior if old == digest), None)
    return dict(changed_percent=float(changed.sum() / max(1, mask.sum()) * 100), digest=digest, same_as=same)
