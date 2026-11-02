"""Independent snow preview using recovered UDW scatter and normal textures."""
import ctypes as C
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image


def slope_weight(normals):
    t = np.clip((normals[:, 2] - .35) / .4, 0, 1)
    return t * t * (3 - 2 * t)


class SnowPreview:
    def __init__(self, gl):
        self.gl = gl
        self.texture = C.c_uint()
        self.level = None
        folder = Path(__file__).with_name('snow-textures')
        metadata = json.loads((folder / 'sources.json').read_text())
        images = {}
        for row in metadata['textures']:
            file = folder / row['file']
            if hashlib.sha256(file.read_bytes()).hexdigest() != row['sha256']:
                raise ValueError('Snow texture checksum mismatch')
            with Image.open(file) as image:
                if image.size != (1024, 1024):
                    raise ValueError('Unsupported snow texture dimensions')
                images[file.stem] = np.asarray(image).astype(np.float32) / 255
        self.scatter = images['Snow_Scatter']
        normal = images['Snow_Normal'][..., :2] * 2 - 1
        z = np.sqrt(np.maximum(0, 1 - (normal * normal).sum(axis=2)))
        detail = np.clip(.82 + .15 * z - .10 * normal[..., 0] + .10 * normal[..., 1], .65, 1)
        self.rgb = np.rint(detail[..., None] * np.array([234, 243, 250])).astype(np.uint8)
        gl.glGenTextures(1, C.byref(self.texture))
        self._geometry = None

    def pixels(self, coverage):
        if not np.isfinite(coverage) or not 0 <= coverage <= 1:
            raise ValueError('Snow coverage must be between 0 and 1')
        if coverage == 0:
            alpha = np.zeros_like(self.scatter)
        elif coverage == 1:
            alpha = np.ones_like(self.scatter)
        else:
            t = np.clip((coverage - self.scatter + .08) / .16, 0, 1)
            alpha = t * t * (3 - 2 * t)
        return np.ascontiguousarray(np.dstack((self.rgb, np.rint(alpha * 255).astype(np.uint8))))

    def draw(self, terrain, normals, coverage):
        gl = self.gl
        level = round(float(coverage), 2)
        if not 0 <= level <= 1:
            raise ValueError('Invalid snow coverage')
        if level == 0:
            return
        gl.glBindTexture(0x0de1, self.texture.value)
        if self.level != level:
            from replay_texture_filter import mip_chain
            for mip_level, pixels in enumerate(mip_chain(self.pixels(level))):
                gl.glTexImage2D(0x0de1, mip_level, 0x8058, pixels.shape[1], pixels.shape[0], 0,
                                0x1908, 0x1401, pixels.ctypes.data)
            for key, value in ((0x2801, 0x2703), (0x2800, 0x2601), (0x2802, 0x2901), (0x2803, 0x2901)):
                gl.glTexParameteri(0x0de1, key, value)
            self.level = level
        if self._geometry is not terrain:
            self._uv = np.ascontiguousarray(terrain.positions[:, :2] / 400., dtype=np.float32)
            self._colors = np.ones((len(terrain.positions), 4), dtype=np.float32)
            self._colors[:, 3] = slope_weight(normals)
            arrays = [terrain.indices]
            if terrain.color_indices is not None:
                arrays.append(terrain.color_indices)
            arrays.extend(page.color_indices for page in terrain.color_batches)
            self._indices = np.ascontiguousarray(np.concatenate(arrays), dtype=np.uint32)
            self._geometry = terrain
        gl.glDisable(0x0bc0)
        gl.glEnable(0x0de1)
        gl.glEnableClientState(0x8078)
        gl.glTexEnvi(0x2300, 0x2200, 0x2100)
        gl.glTexCoordPointer(2, 0x1406, 0, self._uv.ctypes.data)
        gl.glColorPointer(4, 0x1406, 0, self._colors.ctypes.data)
        gl.glEnable(0x0be2)
        gl.glBlendFunc(0x0302, 0x0303)
        # Only pixels already written by the terrain receive snow; holes stay open.
        gl.glDepthFunc(0x0202)
        gl.glDepthMask(0)
        try:
            gl.glDrawElements(0x0004, len(self._indices), 0x1405, self._indices.ctypes.data)
        finally:
            gl.glDepthMask(1)
            gl.glDepthFunc(0x0201)
            gl.glDisable(0x0be2)
            gl.glDisable(0x0de1)
            gl.glDisableClientState(0x8078)
            gl.glColorPointer(3, 0x1406, 0, terrain.colors.ctypes.data)

    def close(self):
        if self.texture.value:
            self.gl.glDeleteTextures(1, C.byref(self.texture))
            self.texture.value = 0
        self._geometry = None
