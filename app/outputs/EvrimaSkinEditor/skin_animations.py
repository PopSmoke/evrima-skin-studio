"""On-demand playback of existing decoded game clips. No bulk animation cache."""
from pathlib import Path
import hashlib
import json
import math
import runpy
import numpy as np
from skin_idle import IdleClip, blend
from mesh_renderer import component_matrices

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
_track_sampler = None


def _sample_tracks(*args):
    # The portable idle edition uses dense clips and does not ship the decoder.
    global _track_sampler
    if _track_sampler is None:
        _track_sampler = runpy.run_path(str(ROOT/'work/read-pertrack-animation.py'))['sample_tracks']
    return _track_sampler(*args)


class AnimationClip(IdleClip):
    def __init__(self, mesh, row, bones):
        self.mesh, self.row = mesh, row
        self.duration = float(row['duration'])
        if not 0 < self.duration < 120:
            raise ValueError('Invalid animation duration')
        path = (ROOT/row['file']).resolve()
        if not path.is_relative_to((ROOT/'work').resolve()):
            raise ValueError('Animation path leaves the decoded asset folder')
        if path.stat().st_size > 128_000_000:
            raise ValueError('Animation exceeds the per-clip size limit')
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != row['sha256']:
            raise ValueError('Decoded animation file changed')
        indices = {b['name']: i for i, b in enumerate(bones)}
        defaults = []
        for name, parent in mesh.bones:
            if name not in indices:
                raise ValueError('Animation bone missing from this skeleton')
            b = bones[indices[name]]
            if (None if b['parent'] < 0 else bones[b['parent']]['name']) != (None if parent < 0 else mesh.bones[parent][0]):
                raise ValueError('Animation hierarchy differs from the model')
            defaults.append(b['transform'])
        self.defaults = np.asarray(defaults, dtype=np.float64)
        self.tracks = None
        self.frames = None
        self.reference_components = 0
        if row['codec'] == 'acl-2.1':
            import io
            with np.load(io.BytesIO(payload), allow_pickle=False) as data:
                values = data['transforms'].astype(np.float32)
                mapping = data['bone_map'].tolist()
                rate = float(data['rate']); wrap = bool(data['wrap'])
            if values.ndim != 3 or values.shape[1:] != (len(mapping), 10) or not np.isfinite(values).all() or rate <= 0:
                raise ValueError('Invalid ACL samples')
            if wrap:
                values = np.concatenate([values, values[:1]])
            self.times = np.arange(len(values), dtype=np.float64)/rate
            if abs(self.times[-1] - self.duration) > .001:
                raise ValueError('ACL sample times disagree with the clip duration')
            self.times[-1] = self.duration
            self.frames = values
            byname = {bones[b]['name']: i for i, b in enumerate(mapping)}
        elif row['codec'] in ('per-track', 'key-lerp'):
            data = json.loads(payload)
            self.tracks = data['tracks']
            self.frame_count = data['envelope']['compressed_frames']
            # Some non-additive key-lerp poses omit scale (or another component).
            # Preserve the source skeleton's reference component, as for a
            # missing bone track; do not ask the sampler to interpolate zero keys.
            for track in self.tracks:
                reference = bones[indices[track['bone_name']]]['transform']
                for field, start, end in (('rotation', 0, 4), ('translation', 4, 7), ('scale', 7, 10)):
                    if not track[field]['keys']:
                        track[field] = dict(keys=[reference[start:end]])
                        self.reference_components += 1
            byname = {t['bone_name']: i for i, t in enumerate(self.tracks)}
        else:
            raise ValueError('Unsupported animation codec')
        self.target_indices = np.asarray([i for i, (name, _) in enumerate(mesh.bones) if name in byname], dtype=int)
        self.source_indices = np.asarray([byname[name] for name, _ in mesh.bones if name in byname], dtype=int)
        self.root_translation = self.local_pose(0)[0, 4:7].copy()
        self.bounds_key = self.bounds = None

    def local_pose(self, seconds):
        if not math.isfinite(seconds):
            raise ValueError('Invalid animation time')
        seconds = min(self.duration, max(0., seconds))
        local = self.defaults.copy()
        if self.frames is not None:
            right = min(len(self.times)-1, max(1, int(np.searchsorted(self.times, seconds, side='right'))))
            left = right-1
            amount = (seconds-self.times[left])/(self.times[right]-self.times[left])
            samples = blend(self.frames[left].astype(np.float64), self.frames[right].astype(np.float64), amount)
        else:
            sampled = _sample_tracks(self.tracks, self.frame_count, self.duration, seconds)
            samples = np.asarray([s['rotation_xyzw']+s['translation']+s['scale'] for s in sampled])
        local[self.target_indices] = samples[self.source_indices]
        if not np.isfinite(local).all() or not np.allclose(np.linalg.norm(local[:, :4], axis=1), 1., atol=.003):
            raise ValueError('Invalid sampled animation transform')
        return local

    def pose(self, seconds):
        local = self.local_pose(seconds)
        local[0, 4:7] = self.root_translation
        return component_matrices(self.mesh.bones, local)


class AnimationLibrary:
    def __init__(self):
        self.data = json.loads((HERE/'animation-catalog.json').read_text(encoding='utf-8'))
        if self.data['format'] != 'evrima-studio-animations-1':
            raise ValueError('Unsupported animation catalog')
        self.key = self.clip = None

    def choices(self, species):
        return self.data['models'][species]['clips']

    def load(self, species, mesh, mesh_hash, selection=None):
        model = self.data['models'][species]
        selection = selection or model['default']
        key = (species, id(mesh), selection)
        if key != self.key:
            if model['mesh_sha256'] != mesh_hash:
                raise ValueError('Animations were indexed for a different model')
            row = next((r for r in model['clips'] if r['id'] == selection), None)
            if row is None:
                raise ValueError('Animation does not belong to this dinosaur')
            clip = (IdleClip(mesh, row) if row.get('cache') == 'studio-idle'
                    else AnimationClip(mesh, row, self.data['skeletons'][row['skeleton']]))
            self.clip, self.key = clip, key
        return self.clip
