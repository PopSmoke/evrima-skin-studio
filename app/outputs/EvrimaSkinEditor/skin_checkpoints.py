"""Small editable checkpoints and colors-only comparison documents."""
import copy
import json
import uuid
from skin_document import validate

LIMIT = 12
FORMAT = 'evrima-skin-checkpoints'
MAX_BYTES = 2 * 1024 * 1024


def validate_rows(rows):
    if not isinstance(rows, list) or len(rows) > LIMIT:
        raise ValueError(f'A set may contain at most {LIMIT} checkpoints.')
    names = set(); ids = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'id', 'name', 'document'}:
            raise ValueError('Invalid checkpoint entry.')
        name = row['name']; identity = row['id']
        if not isinstance(name, str) or not name.strip() or name != name.strip() or len(name) > 80 or any(ord(c) < 32 for c in name):
            raise ValueError('Checkpoint names must contain 1–80 characters.')
        if not isinstance(identity, str) or not identity or len(identity) > 80:
            raise ValueError('Invalid checkpoint identity.')
        if name.casefold() in names or identity in ids:
            raise ValueError('Checkpoint names and identities must be unique.')
        names.add(name.casefold()); ids.add(identity)
        if not isinstance(row['document'], dict):
            raise ValueError('Checkpoint document must be an editable skin project.')
        validate(row['document'])
    return rows


def add(rows, name, document):
    if len(rows) >= LIMIT:
        raise ValueError(f'All {LIMIT} checkpoint slots are full. Remove one before adding another.')
    result = copy.deepcopy(rows)
    doc = copy.deepcopy(validate(document)); doc['name'] = name.strip()
    result.append(dict(id=uuid.uuid4().hex, name=name.strip(), document=doc))
    return validate_rows(result)


def encode(rows):
    result = dict(format=FORMAT, version=1, checkpoints=copy.deepcopy(validate_rows(rows)))
    if len((json.dumps(result, indent=2, allow_nan=False) + '\n').encode('utf-8')) > MAX_BYTES:
        raise ValueError('Checkpoint set exceeds 2 MB. Shorten imported notes or save fewer checkpoints.')
    return result


def decode(text):
    if len(text.encode('utf-8')) > MAX_BYTES:
        raise ValueError('Checkpoint set exceeds 2 MB.')
    data = json.loads(text)
    if not isinstance(data, dict) or data.get('format') != FORMAT or data.get('version') != 1:
        raise ValueError('Choose a Skin Studio checkpoint set.')
    return copy.deepcopy(validate_rows(data.get('checkpoints')))


def on_model(skin, model):
    """Compare only appearance on one frozen model/settings snapshot."""
    validate(skin); validate(model)
    result = copy.deepcopy(model)
    for key in ('name', 'colors', 'default_eyes', 'extra_overrides', 'source_glitch', 'import_notes'):
        if key in skin: result[key] = copy.deepcopy(skin[key])
        else: result.pop(key, None)
    return validate(result)
