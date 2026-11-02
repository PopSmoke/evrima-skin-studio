"""Recorded player identity fields and time-aware dinosaur/player-state joins."""
import bisect
import hashlib
import math
from pathlib import Path
import runpy
import unicodedata

FIELDS = {'SteamId', 'PlayerState', 'PlayerNamePrivate'}
PLAYER_SCHEMA = '/Game/TheIsle/Core/Player/BP_PlayerState.BP_PlayerState_C'


def eligible(schema, field):
    return (field == 'PlayerNamePrivate' and schema == PLAYER_SCHEMA or
            field in ('SteamId', 'PlayerState') and '/Characters/Dinosaurs/' in (schema or ''))


def decode_value(bits_class, name, raw, size):
    reader = bits_class(raw, size)
    value = reader.packed(64) if name == 'PlayerState' else reader.string()['text']
    if reader.pos != reader.limit:
        raise ValueError('Identity field has trailing bits: ' + name)
    if name == 'PlayerState' and value == 1:
        raise ValueError('Inline player-state reference is unsupported')
    if name == 'SteamId' and value and (not value.isascii() or not value.isdecimal() or
                                        len(value) > 20 or not 0 < int(value) < 2**64):
        raise ValueError('Invalid recorded Steam ID')
    return value


def inspect_replay(path, updates, history):
    path = Path(path)
    u = runpy.run_path(str(Path(__file__).with_name('decode-replay-updates.py')))
    a, p = u['a'], u['a']['p']
    events, checkpoints = [], []
    with path.open('rb') as source:
        for message in updates['messages']:
            fields = [(b, f) for b in message['content']['blocks']
                      for f in b.get('properties', {}).get('fields', [])
                      if eligible(message['schema_group'], f['name'].get('text'))]
            if not fields:
                continue
            raw = u['payload'](source, history['messages'][message['message']])
            for block, field in fields:
                offset = block['payload_offset_bits'] + field['payload_offset_bits']
                value = u['slice_bits'](raw, offset, field['payload_bits'])
                if hashlib.sha256(value).hexdigest() != field['payload_sha256']:
                    raise ValueError('Identity field source digest mismatch')
                name = field['name']['text']
                events.append([message['seconds'], message['message'], message['actor_guid'], name,
                               decode_value(u['Bits'], name, value, field['payload_bits'])])
        index = u['m']['c'].outer.inspect(path)
        for chunk in index['chunks']:
            if chunk['type'] != 2:
                continue
            source.seek(chunk['data_offset']); data = source.read(chunk['data_bytes'])
            metadata = p['load_checkpoint_module']().parse(data)
            packets = p['inspect_checkpoint'](data)
            refs = {r['guid']: r for r in metadata['resolved_references']}
            groups = {g['name'].rsplit('.', 1)[-1]: g for g in metadata['resolved_export_groups']}
            states = []
            for message in packets['messages']:
                if not message['open']:
                    continue
                raw = a['payload'](data, packets['packets'], message)
                reader = u['Bits'](raw, message['payload_bits']); reader.pos = message['required_guid_prefix_bits']
                opening = a['actor_opening'](reader, closing=message['close'])
                ref = refs.get(opening.get('archetype_guid'))
                group = groups.get((ref['name'] if ref else '').removeprefix('Default__'))
                if group is None or not any(eligible(group['name'], f) for f in FIELDS):
                    continue
                values = {}
                for block in a['actor_blocks'](reader, None)['blocks']:
                    if not block['is_actor'] or not block['has_rep_layout'] or block['deleted']:
                        continue
                    payload = u['slice_bits'](raw, block['payload_offset_bits'], block['payload_bits'])
                    for field in a['properties'](payload, block['payload_bits'], group)['fields']:
                        name = field['name'].get('text')
                        if eligible(group['name'], name):
                            value = u['slice_bits'](payload, field['payload_offset_bits'], field['payload_bits'])
                            values[name] = decode_value(u['Bits'], name, value, field['payload_bits'])
                states.append([opening['actor_guid'], values])
            checkpoints.append({'chunk': chunk['index'], 'states': states})
    return {'format': 'evrima-player-identities-1', 'events': events, 'checkpoints': checkpoints}


class IdentityTimeline:
    def __init__(self, data, scene):
        self.scene, self.events, self.times, self.checkpoints = scene, {}, {}, {}
        if data is None:
            return
        if data.get('format') != 'evrima-player-identities-1':
            raise ValueError('Unsupported player identity cache')
        def validate(guid, field, value):
            if guid not in scene.actors or field not in FIELDS:
                raise ValueError('Invalid identity actor/field')
            if field == 'PlayerState':
                if type(value) is not int or not 0 <= value < 2**64 or value == 1:
                    raise ValueError('Invalid player-state GUID')
            elif not isinstance(value, str) or len(value) > 4096:
                raise ValueError('Invalid identity string')
            elif field == 'SteamId' and value and (not value.isascii() or not value.isdecimal() or
                                                  len(value) > 20 or not 0 < int(value) < 2**64):
                raise ValueError('Invalid Steam ID')
        previous = (-1, -1)
        for seconds, message, guid, field, value in data['events']:
            if (not math.isfinite(seconds) or not 0 <= seconds <= scene.duration + .001 or
                    type(message) is not int or message < 0 or (seconds, message) < previous):
                raise ValueError('Invalid identity event order')
            previous = seconds, message
            validate(guid, field, value)
            self.events.setdefault((guid, field), []).append((seconds, message, value))
        self.times = {key: [r[0] for r in rows] for key, rows in self.events.items()}
        for cp in data['checkpoints']:
            if cp['chunk'] in self.checkpoints:
                raise ValueError('Duplicate identity checkpoint')
            states = {}
            for guid, values in cp['states']:
                if guid in states:
                    raise ValueError('Duplicate checkpoint identity')
                for field, value in values.items():
                    validate(guid, field, value)
                states[guid] = values
            self.checkpoints[cp['chunk']] = states

    def field(self, guid, field, seconds, anchor=-1):
        key = guid, field
        rows = self.events.get(key, [])
        index = bisect.bisect_right(self.times.get(key, []), seconds) - 1
        event = rows[index] if index >= 0 else None
        if anchor >= 0:
            cp = self.scene.anchors[anchor]
            states = self.checkpoints.get(cp['chunk'], {})
            if guid in states:
                minimum = cp['resume_message']
                if event is None or minimum is None or event[1] < minimum:
                    return states[guid].get(field)
        return event[2] if event else None

    def player(self, guid, seconds, anchor=-1):
        steam_id = self.field(guid, 'SteamId', seconds, anchor)
        state_guid = self.field(guid, 'PlayerState', seconds, anchor)
        name = self.field(state_guid, 'PlayerNamePrivate', seconds, anchor) if state_guid else None
        return {'name': name or None, 'steam_id': steam_id or None, 'player_state': state_guid}


def display_name(value):
    return ''.join(c for c in value if unicodedata.category(c) not in ('Cc', 'Cf', 'Cs'))
