"""Reusable skin documents and color interchange. No renderer or game dependency."""
import copy
import json
import math
import re
from decimal import Decimal

SLOTS = {
    'md': ('Male display', 'MaleDisplayColor', 'Color1_RedLayer'),
    'm': ('Markings', 'MarkingsColor', 'Color5_MagentaLayer'),
    'b': ('Body', 'BodyColor', 'Color4_CyanLayer'),
    'f': ('Flank', 'FlankColor', 'Color3_BlueLayer'),
    'u': ('Underbelly', 'UnderbellyColor', 'Color2_GreenLayer'),
    'd': ('Detail', 'Detail1Color', 'Color6_YellowLayer'),
    'e': ('Eyes', 'EyesColor', 'Color_Iris_Primary'),
}
FORMAT = 'evrima-skin-editor'
IMPORTER_LIMIT = 1e23
BYTE_HEX_MODE = 'Direct hex (bytes / 255)'
ATAVUS_LIMIT = IMPORTER_LIMIT  # Compatibility with existing local scripts.
RAW_MODE = 'Raw RGBA (numbers)'


def finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def raw_number(text):
    text = text.strip()
    if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', text):
        raise ValueError('Enter a decimal or scientific number, such as -2, 1e22 or 0.004.')
    value = float(text)
    if not finite(value):
        raise ValueError('Number exceeds finite 64-bit storage. Infinity and NaN are not supported.')
    if value == 0. and Decimal(text) != 0:
        raise ValueError('Number is too small for 64-bit storage; it has not been replaced with zero.')
    return value


def format_color(color, mode):
    if mode == RAW_MODE:
        return ', '.join(repr(v) for v in color)
    return as_hex(color, mode)


def parse_color(text, mode, previous):
    if mode == RAW_MODE:
        pieces = text.split(',')
        if len(pieces) not in (3, 4):
            raise ValueError('Enter R, G, B or R, G, B, A. Example: -1, 1e22, 0.004, 1')
        values = [raw_number(p) for p in pieces]
        return values if len(values) == 4 else values + [previous[3]]
    return hex_color(text, mode)[:3] + [previous[3]]


def importer_range_notes(colors):
    outside = [alias for alias, c in colors.items() if any(abs(v) > IMPORTER_LIMIT for v in c)]
    return (['Raw values are preserved. Channels outside ±1e23 may exceed external importer limits: ' + ', '.join(outside)] if outside else [])


atavus_range_notes = importer_range_notes  # Compatibility with existing scripts.


def export_filename(name):
    """Keep the design name, replacing only characters Windows cannot save."""
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip().rstrip('. ')
    if stem.lower().endswith('.json'):
        stem = stem[:-5].rstrip('. ')
    stem = stem or 'Untitled Skin'
    if re.fullmatch(r'(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])', stem.split('.')[0], re.I):
        stem = '_' + stem
    return stem + '.json'


def hex_color(text, mode='Game hex (sRGB)'):
    if not isinstance(text, str) or not re.fullmatch(r'#?[0-9a-fA-F]{6}', text):
        raise ValueError('Enter six hexadecimal digits, for example #8000FF.')
    c = [v / 255 for v in bytes.fromhex(text.lstrip('#'))]
    if mode == 'Game hex (sRGB)':
        c = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in c]
    elif mode in (BYTE_HEX_MODE, 'Atavus hex (bytes / 255)'):
        c = [round(v, 6) for v in c]
    else:
        raise ValueError('Unknown color entry mode')
    return c + [1.]


def as_hex(color, mode='Game hex (sRGB)'):
    c = [max(0., min(1., v)) for v in color[:3]]
    if mode == 'Game hex (sRGB)':
        c = [v * 12.92 if v <= .0031308 else 1.055 * v ** (1 / 2.4) - .055 for v in c]
    elif mode not in (BYTE_HEX_MODE, 'Atavus hex (bytes / 255)'):
        raise ValueError('Unknown color entry mode')
    return '#' + ''.join(f'{int(v * 255 + .5):02X}' for v in c)


def validate(doc):
    if not isinstance(doc, dict) or doc.get('format') != FORMAT or doc.get('version') != 1:
        raise ValueError('Unsupported editor project')
    if not isinstance(doc.get('name'), str) or len(doc['name']) > 200:
        raise ValueError('Skin name must be at most 200 characters')
    if not isinstance(doc.get('species'), str) or len(doc['species']) > 64:
        raise ValueError('Invalid species')
    for k in ('growth', 'variation'):
        v = doc.get(k)
        if not finite(v) or not 0 <= v <= (1 if k == 'growth' else 128):
            raise ValueError('Growth must be 0–100%; variation must be 0–128.')
    if type(doc.get('pattern')) is not int or not 0 <= doc['pattern'] < 32:
        raise ValueError('Invalid pattern')
    if any(type(doc.get(k)) is not bool for k in ('female', 'default_eyes')):
        raise ValueError('Invalid sex or eye setting')
    if type(doc.get('prime', False)) is not bool:
        raise ValueError('Prime must be true or false')
    colors = doc.get('colors')
    if not isinstance(colors, dict) or set(colors) != set(SLOTS):
        raise ValueError('Project must contain all seven color slots')
    for c in colors.values():
        if not isinstance(c, list) or len(c) != 4 or not all(finite(v) for v in c):
            raise ValueError('RGBA must contain four finite numbers representable in 64-bit storage')
    if not isinstance(doc.get('extra_overrides', {}), dict):
        raise ValueError('Invalid extra material colors')
    for k, c in doc.get('extra_overrides', {}).items():
        if k not in ('ClawColor', 'MouthColor', 'TeethColor') or not isinstance(c, list) or len(c) != 4 or not all(finite(v) for v in c):
            raise ValueError('Unsupported extra material color')
    if not isinstance(doc.get('import_notes', []), list) or not all(isinstance(s, str) for s in doc.get('import_notes', [])):
        raise ValueError('Invalid import notes')
    if doc.get('source_glitch') is not None and not isinstance(doc['source_glitch'], dict):
        raise ValueError('Invalid neon metadata')
    return doc


def new_document(species, colors):
    return validate(dict(format=FORMAT, version=1, name='Untitled skin', species=species,
        pattern=0, growth=1., female=False, variation=8., default_eyes=True, prime=False,
        colors=copy.deepcopy(colors), extra_overrides={}, import_notes=[]))


def read_raw(value, fallback):
    result = list(fallback)
    for i, k in enumerate('rgba'):
        v = value.get(k)
        if v is None:
            v = value.get(k.upper())
        if finite(v):
            result[i] = v
    return result


def normalize_json_whitespace(text):
    """Chat-pasted indentation may contain NBSP; never change text inside strings."""
    inside = escaped = False
    result = []
    for c in text.lstrip('\ufeff'):
        if inside:
            result.append(c)
            if escaped:
                escaped = False
            elif c == '\\':
                escaped = True
            elif c == '"':
                inside = False
        else:
            if c == '"':
                inside = True
            result.append(' ' if c.isspace() and c not in ' \t\r\n' else c)
    return ''.join(result)


def import_legacy_xyz(value, fallback):
    aliases = {'md': 'md', 'm': 'm', 'b': 'b', 'f': 'f', 'u': 'u', 'd1': 'd', 'e': 'e'}
    expected = {'sv', 'pi', *aliases}
    if set(value) != expected:
        raise ValueError('XYZ skin requires exactly sv, pi, md, m, b, f, u, d1 and e; fields will not be silently discarded.')
    for key in ('sv', 'pi'):
        v = value[key]
        if not finite(v) or not 0 <= v <= 31 or v != int(v):
            raise ValueError(key + ' must be an integer from 0 to 31 for the legacy XYZ format.')
    doc = copy.deepcopy(fallback)
    doc.update(name='Imported XYZ skin', pattern=int(value['pi']), variation=value['sv'], default_eyes=False,
        extra_overrides={}, source_glitch=dict(mode='legacy_glitch', sections={}))
    for source, dest in aliases.items():
        vector = value[source]
        if not isinstance(vector, dict) or set(vector) != {'X', 'Y', 'Z'}:
            raise ValueError(source + ' must contain exactly X, Y and Z.')
        channels = [vector[axis] for axis in ('X', 'Y', 'Z')]
        if not all(finite(v) for v in channels):
            raise ValueError(source + ' must contain finite numeric X, Y and Z values.')
        doc['colors'][dest] = channels + [1.]
    doc['import_notes'] = [
        'Imported legacy XYZ: sv → variation; pi → zero-based pattern; X/Y/Z → raw R/G/B; d1 → detail; alpha = 1.',
        'No species is stored in this format. The selected species, sex, growth and prime setting are retained.',
        'Negative and extreme RGB are preserved. Legacy preview metadata is retained, but server glitch/glow appearance is unverified.',
    ] + atavus_range_notes(doc['colors'])
    return validate(doc)


def import_json(text, fallback):
    if len(text) > 1024 * 1024:
        raise ValueError('Skin file exceeds 1 MB')
    def reject_constant(value):
        raise ValueError('JSON contains a nonfinite number: ' + value)
    def integer(value):
        result = int(value)
        if not finite(result):
            raise ValueError('JSON integer exceeds finite 64-bit numeric range')
        return result
    value = json.loads(normalize_json_whitespace(text), parse_constant=reject_constant, parse_float=raw_number, parse_int=integer)
    if not isinstance(value, dict):
        raise ValueError('Skin JSON must be an object')
    if value.get('format') == FORMAT:
        value.setdefault('prime', False)
        return copy.deepcopy(validate(value))
    glitch = value.get('glitch') if isinstance(value.get('glitch'), dict) else {}
    if any(k in value for k in ('sv', 'pi', 'd1')):
        return import_legacy_xyz(value, fallback)
    doc = copy.deepcopy(fallback)
    doc['extra_overrides'] = {}
    notes = ['Imported colors use the selected species, pattern, sex and variation. Compact skin JSON does not select those settings.']
    config = value.get('config')
    if isinstance(config, dict):
        game = value.get('game') if isinstance(value.get('game'), dict) else {}
        raw = value.get('raw', game.get('raw', {}))
        if not isinstance(raw, dict):
            raw = {}
        for alias in SLOTS:
            if isinstance(raw.get(alias), dict):
                doc['colors'][alias] = read_raw(raw[alias], doc['colors'][alias])
            elif isinstance(config.get(alias), str) and re.fullmatch(r'#?[0-9a-fA-F]{6}', config[alias]):
                doc['colors'][alias] = hex_color(config[alias], 'Atavus hex (bytes / 255)')
        if not isinstance(raw.get('d'), dict) and not (isinstance(config.get('d'), str) and re.fullmatch(r'#?[0-9a-fA-F]{6}', config['d'])):
            if isinstance(raw.get('u'), dict):
                doc['colors']['d'] = read_raw(raw['u'], doc['colors']['d'])
            elif isinstance(config.get('u'), str) and re.fullmatch(r'#?[0-9a-fA-F]{6}', config['u']):
                doc['colors']['d'] = hex_color(config['u'], 'Atavus hex (bytes / 255)')
        notes.append('Raw RGBA takes priority over hex. config.gamma is ignored by this compact format importer.')
    else:
        payload = value.get('gameSkin', value)
        if not isinstance(payload, dict) or not all(isinstance(payload.get(slot), dict) for _, slot, _ in SLOTS.values()):
            raise ValueError('Expected an editor project, skin config/raw JSON, or seven-slot gameSkin payload.')
        for alias, (_, slot, _) in SLOTS.items():
            doc['colors'][alias] = read_raw(payload[slot], doc['colors'][alias])
    doc['name'] = value.get('name') if isinstance(value.get('name'), str) and value['name'].strip() else doc['name']
    doc['default_eyes'] = False  # Preserve an imported eye color until the user opts into defaults.
    doc['source_glitch'] = copy.deepcopy(glitch) or None
    if not doc['source_glitch'] and isinstance(value.get('preview'), dict) and value['preview'].get('legacyGlitch'):
        doc['source_glitch'] = dict(mode='legacy_glitch', sections={})
    if doc['source_glitch']:
        notes.append('Neon metadata is preserved but not rendered: native glow is unverified.')
    notes.extend(atavus_range_notes(doc['colors']))
    doc['import_notes'] = notes
    return validate(doc)


def material_overrides(doc, default_colors):
    validate(doc)
    overrides = copy.deepcopy(doc.get('extra_overrides', {}))
    for alias, (_, _, parameter) in SLOTS.items():
        c = default_colors[alias] if alias == 'e' and doc['default_eyes'] else doc['colors'][alias]
        # Normal body refresh discards imported alpha and writes A=1. Eyes are separate.
        overrides[parameter] = list(c[:3]) + [1. if alias != 'e' else c[3]]
    return overrides


def export_skin(doc, default_colors):
    validate(doc)
    colors = copy.deepcopy(doc['colors'])
    if doc['default_eyes']:
        colors['e'] = list(default_colors['e'])
    return dict(format='evrima-skin', version=1, name=doc['name'],
        code=re.sub(r'[^a-z0-9]+', '-', doc['name'].lower()).strip('-') or 'skin-design',
        config=dict(gamma=2.5, **{k: as_hex(v, BYTE_HEX_MODE)[1:].lower() for k, v in colors.items()}),
        raw={k: dict(zip('rgba', v)) for k, v in colors.items()},
        glitch=copy.deepcopy(doc.get('source_glitch')) or dict(mode='neon', sections={k: 0 for k in SLOTS}))


export_atavus = export_skin  # Retain the old Python entry point for local scripts.


def save_json(path, value):
    """Replace only the selected destination after serializing successfully."""
    from pathlib import Path
    path = Path(path)
    text = json.dumps(value, indent=2, allow_nan=False) + '\n'
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(text, encoding='utf-8')
    temp.replace(path)
