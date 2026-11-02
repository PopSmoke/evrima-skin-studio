"""One recovered idle at a time; independent of color baking and replay state."""
from pathlib import Path
import hashlib
import json
import math
from itertools import product
import numpy as np
from mesh_renderer import component_matrices

HERE = Path(__file__).resolve().parent


def blend(a, b, weight):
    result = a + (b - a) * weight
    qa, qb = a[:, :4], b[:, :4]
    qb = np.where((qa * qb).sum(axis=1, keepdims=True) < 0, -qb, qb)
    q = qa + (qb - qa) * weight
    result[:, :4] = q / np.maximum(np.linalg.norm(q, axis=1, keepdims=True), 1e-12)
    return result


class IdleClip:
    def __init__(self, mesh, row):
        path = (HERE / row['file']).resolve()
        if not path.is_relative_to((HERE / 'idles').resolve()):
            raise ValueError('Idle file leaves the animation folder')
        if path.stat().st_size > 32_000_000 or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('Idle animation file changed')
        if [list(b) for b in mesh.bones] != row['bones']:
            raise ValueError('Idle skeleton differs from the model')
        with np.load(path, allow_pickle=False) as data:
            self.frames = data['transforms'].astype(np.float64)
            self.times = data['times'].copy()
        self.mesh = mesh
        self.row = row
        self.reference_components = 0
        self.duration = float(row['duration'])
        if (self.frames.shape != (row['frames'], len(mesh.bones), 10)
                or not np.isfinite(self.frames).all() or not np.isfinite(self.times).all()
                or self.times.shape != (row['frames'],) or not np.all(np.diff(self.times) > 0)
                or self.times[0] != 0 or abs(self.times[-1] - self.duration) > 1e-6):
            raise ValueError('Invalid idle samples')
        # A few original idle variants have slightly different endpoints.
        self.loop_blend = min(.25, self.duration * .05) if row['endpoint_displacement'] > .01 else 0.
        self.bounds_key = None
        self.bounds = None

    def pose(self, seconds):
        if not math.isfinite(seconds):
            raise ValueError('Invalid animation time')
        t = seconds % self.duration
        right = min(len(self.times) - 1, int(np.searchsorted(self.times, t, side='right')))
        left = max(0, right - 1)
        amount = (t - self.times[left]) / (self.times[right] - self.times[left])
        local = blend(self.frames[left], self.frames[right], amount)
        if self.loop_blend and t > self.duration - self.loop_blend:
            weight = (t - (self.duration - self.loop_blend)) / self.loop_blend
            weight = weight * weight * (3 - 2 * weight)
            local = blend(local, self.frames[0], weight)
        # Anchor the root; a studio idle must not slowly walk out of frame.
        local[0, 4:7] = self.frames[0, 0, 4:7]
        return component_matrices(self.mesh.bones, local)

    def vertices(self, seconds, points, scale=1.):
        # Morph in reference space, animate, then apply the recovered size curve.
        # Scaling before skinning would leave bone translations at adult size.
        return self.mesh.skin(self.pose(seconds), np.asarray(points) / scale) * scale

    def camera_bounds(self, shape):
        # Fit a stable envelope once per model/shape, not a moving fit every frame.
        key = tuple((hashlib.sha256(np.asarray(shape[k]).tobytes()).hexdigest(),
                     shape.get(k + '_scale', shape['scale'])) for k in ('camera_standard', 'camera_prime'))
        if key == self.bounds_key:
            return self.bounds
        bounds = []
        for field in ('camera_standard', 'camera_prime'):
            points = shape[field]
            # A single shape scale normalizes either state's already-scaled points;
            # use each state's own scale so both prime and standard fits stay correct.
            scale = shape.get(field + '_scale', shape['scale'])
            low, high = points.min(0).copy(), points.max(0).copy()
            for t in np.linspace(0, self.duration, 21):
                posed = self.vertices(float(t), points, scale)
                low = np.minimum(low, posed.min(0)); high = np.maximum(high, posed.max(0))
            margin = (high - low) * .06
            # All eight corners are needed when fitting a rotated camera.
            # Two opposite corners can project to nearly the same screen point.
            bounds.append(np.array(list(product(*zip(low - margin, high + margin)))))
        self.bounds_key, self.bounds = key, bounds
        return bounds


class IdleLibrary:
    def __init__(self):
        self.data = json.loads((HERE / 'idle-catalog.json').read_text())
        if self.data['format'] != 'evrima-studio-idles-1':
            raise ValueError('Unsupported idle catalog')
        self.key = None
        self.clip = None

    def load(self, species, mesh, mesh_hash):
        key = (species, id(mesh))
        if key != self.key:
            row = self.data['clips'].get(species)
            if row is None:
                raise ValueError('No recovered idle for this dinosaur')
            if row['mesh_sha256'] != mesh_hash:
                raise ValueError('Idle was validated against a different model')
            clip = IdleClip(mesh, row)
            self.clip, self.key = clip, key
        return self.clip
