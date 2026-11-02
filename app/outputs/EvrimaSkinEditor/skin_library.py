"""Portable, metadata-only personal skin collections. No graphics dependencies."""
import copy
import json
import uuid
from skin_document import validate

FORMAT = 'evrima-skin-library'
LIMIT = 500
MAX_BYTES = 8 * 1024 * 1024
STATUSES = ('Not tested in game', 'Tested in game', 'Needs adjustment')


def tags_from_text(text):
    tags = list(dict.fromkeys(t.strip().casefold() for t in text.split(',') if t.strip()))
    if len(tags) > 20 or any(len(t) > 40 or any(ord(c) < 32 for c in t) for t in tags):
        raise ValueError('Use up to 20 comma-separated tags, at most 40 characters each.')
    return tags


def validate_rows(rows):
    if not isinstance(rows, list) or len(rows) > LIMIT:
        raise ValueError(f'A library can hold up to {LIMIT} designs.')
    identities = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'id', 'document', 'favorite', 'tags', 'status', 'notes'}:
            raise ValueError('Invalid library entry.')
        identity = row['id']
        if not isinstance(identity, str) or not identity or len(identity) > 80 or identity in identities:
            raise ValueError('Library identities must be unique nonempty strings.')
        identities.add(identity)
        validate(row['document'])
        if type(row['favorite']) is not bool or row['status'] not in STATUSES:
            raise ValueError('Invalid favorite or test status.')
        tags = row['tags']
        if not isinstance(tags, list) or not all(isinstance(t, str) and t and ',' not in t for t in tags) or tags_from_text(','.join(tags)) != tags:
            raise ValueError('Invalid library tags.')
        if not isinstance(row['notes'], str) or len(row['notes']) > 4000:
            raise ValueError('Test notes must be at most 4,000 characters.')
    return rows


def encode(rows):
    data = dict(format=FORMAT, version=1, designs=copy.deepcopy(validate_rows(rows)))
    if len((json.dumps(data, indent=2, allow_nan=False) + '\n').encode('utf-8')) > MAX_BYTES:
        raise ValueError('Library exceeds 8 MB. Save a smaller collection.')
    return data


def decode(text):
    if len(text.encode('utf-8')) > MAX_BYTES:
        raise ValueError('Library exceeds 8 MB.')
    data = json.loads(text)
    if not isinstance(data, dict) or data.get('format') != FORMAT or data.get('version') != 1:
        raise ValueError('Choose a Skin Studio library JSON file.')
    return encode(data.get('designs'))['designs']


def add_documents(rows, documents):
    result = copy.deepcopy(rows)
    for doc in documents:
        result.append(dict(id=uuid.uuid4().hex, document=copy.deepcopy(validate(doc)),
                           favorite=False, tags=[], status=STATUSES[0], notes=''))
    return encode(result)['designs']


def matching(rows, query='', favorites=False, status='All statuses'):
    terms = query.casefold().split()
    return [r for r in rows if (not favorites or r['favorite']) and
            (status == 'All statuses' or r['status'] == status) and
            all(t in ' '.join((r['document']['name'], r['document']['species'],
                              *r['tags'], r['notes'])).casefold() for t in terms)]
