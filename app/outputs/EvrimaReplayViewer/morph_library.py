"""On-demand, hash-checked access to decoded inline-LOD shape targets."""
from pathlib import Path
import hashlib
import json
import math
import numpy as np

PROJECT = Path(__file__).resolve().parents[2]


class MorphLibrary:
    def __init__(self, project=PROJECT):
        self.project = Path(project).resolve()
        self.asset_root = self.project / 'work/all-models-animations'
        path = self.project / 'outputs/AssetDecode/morph-coverage.json'
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('Shape catalog exceeds size limit')
        catalog = json.loads(path.read_text(encoding='utf-8'))
        self.models = {}
        for row in catalog['models']:
            if row['status'] != 'decoded':
                continue
            if row['name'] in self.models:
                raise ValueError('Ambiguous model name in shape catalog')
            self.models[row['name']] = row
        if not 1 <= len(self.models) <= 256:
            raise ValueError('Invalid shape catalog size')
        self.loaded_name = None
        self.mesh = None
        self.targets = {}

    def _read(self, value, digest, folder, extension, limit):
        path = Path(value)
        path = (path if path.is_absolute() else self.project / path).resolve()
        # The broad catalog references project assets, never installed game files.
        if not path.is_relative_to((self.asset_root / folder).resolve()) or path.suffix != extension:
            raise ValueError('Shape asset is outside its project folder')
        if path.stat().st_size > limit:
            raise ValueError('Shape asset exceeds size limit')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('Shape asset changed since decoding')
        return path, raw

    def load(self, name):
        if name == self.loaded_name:
            return self.mesh
        row = self.models[name]
        path, _ = self._read(row['file'], row['sha256'], 'geometry', '.evmesh', 64*1024*1024)
        _, raw = self._read(row['morph_file'], row['morph_sha256'], 'morphs', '.evmorph', 64*1024*1024)
        decoded = json.loads(raw)
        if decoded.get('format') != 'evrima-morphs-1' or decoded.get('geometry_sha256') != row['sha256'] or decoded.get('source_sha256') != row['source_sha256']:
            raise ValueError('Shape targets do not match this model')
        if [t['name'] for t in decoded['targets']] != row['names'] or len(set(row['names'])) != len(row['names']):
            raise ValueError('Shape target names differ from catalog')
        from mesh_renderer import Mesh
        mesh = Mesh(path)
        if len(mesh.positions) != row['vertices']:
            raise ValueError('Shape vertex count differs from catalog')
        targets = {}
        for target in decoded['targets']:
            indices = np.asarray(target['indices'])
            positions = np.asarray(target['positions'], dtype=np.float64)
            normals = np.asarray(target['normals'], dtype=np.float64)
            if indices.ndim != 1 or (indices.size and indices.dtype.kind not in 'iu'):
                raise ValueError('Invalid shape vertex indices')
            indices = indices.astype(np.int64)
            if len(np.unique(indices)) != len(indices) or np.any(indices < 0) or np.any(indices >= len(mesh.positions)):
                raise ValueError('Shape vertex outside model or repeated')
            if positions.shape != (len(indices), 3) or normals.shape != positions.shape or not np.isfinite(positions).all() or not np.isfinite(normals).all():
                raise ValueError('Invalid shape deltas')
            targets[target['name']] = (indices, positions, normals)
        # Replace the previous selection; do not retain the entire collection.
        self.loaded_name, self.mesh, self.targets = name, mesh, targets
        return mesh

    def shape(self, target, strength):
        if self.mesh is None:
            raise ValueError('Select a model first')
        if isinstance(strength, bool) or not math.isfinite(strength) or not 0 <= strength <= 1:
            raise ValueError('Shape strength must be between zero and one')
        indices, deltas, _ = self.targets[target]
        points = self.mesh.positions.copy()
        points[indices] += deltas * strength
        return points

    def clear(self):
        self.loaded_name, self.mesh, self.targets = None, None, {}

    def carcass_shape(self, food_remaining_percent, forced_opening):
        from carcass_morphs import preview_weights
        if self.mesh is None or 'BodyGore' not in self.targets:
            raise ValueError('This model has no recovered body carcass shape')
        weights = preview_weights(food_remaining_percent, forced_opening)
        points = self.mesh.positions.copy()
        applied = {}
        for name, weight in weights.items():
            if name not in self.targets:
                continue
            indices, deltas, _ = self.targets[name]
            points[indices] += deltas * weight
            applied[name] = weight
        return points, applied
