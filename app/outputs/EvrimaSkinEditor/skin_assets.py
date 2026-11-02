"""Game-specific adapter. Owns one model; never loads replay scenery or a map."""
from collections import OrderedDict
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
VIEWER = PROJECT / 'outputs/EvrimaReplayViewer'
sys.path.insert(0, str(VIEWER))
sys.path.insert(0, str(PROJECT / 'work'))
from dinosaur_skins import DinosaurSkins, bilinear, linear_to_srgb, preshader
from mesh_renderer import Mesh
from skin_color_kernel import color
from eye_color_kernel import color_6931, color_3188
from additional_eye_kernel import color_6909, color_3193
from dilophosaurus_color_kernel import color as dilo_color
from skin_legacy_color import color as legacy_color
from skin_document import SLOTS, material_overrides, validate, import_json, normalize_json_whitespace, FORMAT
from skin_shapes import SkinShapes


class SkinAssets:
    def __init__(self):
        self.data = json.loads((HERE / 'assets.json').read_text())
        if self.data['format'] != 'evrima-skin-editor-assets-1':
            raise ValueError('Unsupported editor asset catalog')
        for name, digest in self.data['code_hashes'].items():
            self.checked_file(dict(file=name, sha256=digest))
        self.skins = DinosaurSkins(VIEWER)
        self.profiles = self.data['profiles']
        self.skins.profiles = {s: p['body'] for s, p in self.profiles.items()}
        self.skins.eyes.profiles = {s: p['eye'] for s, p in self.profiles.items()}
        self.images = OrderedDict()
        self.used = {}
        self.current = None
        self.mesh = None
        self.surface = None
        self.shapes = SkinShapes()

    def checked_file(self, row):
        path = (PROJECT / row['file']).resolve()
        if not path.is_relative_to(PROJECT.resolve()):
            raise ValueError('Asset path leaves this project')
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('Asset has changed: ' + path.name)
        return path

    def defaults(self, species):
        profile = self.profiles[species]
        common = {p['name']: p['default'] for p in self.skins.data['numeric_parameters']}
        common.update(profile['body']['defaults'])
        eye = {p['name']: p['default'] for p in self.skins.eyes.data['numeric_parameters']}
        eye.update(profile['eye']['defaults'])
        return {alias: list(eye[param] if alias == 'e' else common[param]) for alias, (_, _, param) in SLOTS.items()}

    def load(self, species):
        if species != self.current:
            if species not in self.profiles:
                raise ValueError('This species has no validated skin adapter yet')
            mesh = Mesh(self.checked_file(self.profiles[species]['mesh']))
            self.images.clear()
            self.skins.geometry.clear()
            self.used.clear()
            self.mesh, self.current, self.surface = mesh, species, None
        return self.mesh

    def image(self, package, numeric=False):
        key = (package, numeric)
        if key not in self.images:
            row = self.data['textures'][package]
            path = self.checked_file(row)
            with Image.open(path) as source:
                if list(source.size) != row['size'] or max(source.size) > 8192:
                    raise ValueError('Unexpected source texture size')
                pixels = np.ascontiguousarray(source.convert('RGBA'))
            self.used[package] = dict(size=row['size'], highest_stored_mip=row.get('highest_stored_mip', False))
            if numeric:
                # Existing preview GPU supports 2K normal maps; CPU color reads stay full source.
                if max(pixels.shape[:2]) > 2048:
                    im = Image.fromarray(pixels)
                    im.thumbnail((2048, 2048), Image.Resampling.BOX)
                    pixels = np.ascontiguousarray(im)
                result = (pixels, bool(row['srgb']))
            else:
                result = pixels.astype(np.float32) / 255
                if row['srgb']:
                    result[:, :, :3] = self.skins.srgb[pixels[:, :, :3]]
            self.images[key] = result
            if len(self.images) > 16:
                self.images.popitem(last=False)
        else:
            self.images.move_to_end(key)
        return self.images[key]

    def validate_document(self, doc):
        validate(doc)
        if doc['species'] not in self.profiles:
            raise ValueError('Species not yet supported by the preview')
        if doc['pattern'] >= len(self.profiles[doc['species']]['body']['patterns']):
            raise ValueError('Pattern does not exist for this species')
        if not self.profiles[doc['species']]['body']['patterns'][doc['pattern']].get('available', True):
            raise ValueError('This pattern’s textures have not been recovered yet. Choose an available pattern.')

    def import_document(self, text, fallback):
        doc = import_json(text, fallback)
        self.validate_document(doc)
        source = json.loads(normalize_json_whitespace(text))
        if source.get('format') != FORMAT and 'pi' in source:
            pattern = self.profiles[doc['species']]['body']['patterns'][doc['pattern']]
            if pattern.get('origin') == 'asset-preview':
                raise ValueError('This pi selects an asset-only preview, not a verified game pattern. Choose that texture in the studio instead of importing it as a game index.')
        return doc

    def decoded(self, doc):
        self.validate_document(doc)
        return dict(pattern=doc['pattern'], overrides=material_overrides(doc, self.defaults(doc['species'])))

    @staticmethod
    def check_material_range(overrides):
        limit = float(np.finfo(np.float32).max)
        for name, values in overrides.items():
            if any(abs(v) > limit for v in values):
                raise ValueError(f'{name} exceeds the game material’s finite 32-bit range. Raw values are preserved; preview unavailable for this design.')

    @staticmethod
    def bake_kernel(kernel, images, cb, size, statistics=None):
        if size not in (128, 256, 512, 1024, 2048, 4096):
            raise ValueError('Unsupported bake resolution')
        result = np.empty((size, size, 4), np.uint8)
        outside = 0
        raw_min, raw_max = float('inf'), float('-inf')
        axis = (np.arange(size, dtype=np.float32) + .5) / size
        for y in range(0, size, 32):
            u, v = np.meshgrid(axis, axis[y:y + 32])
            def sample(slot, x, yy):
                return bilinear(images[slot], x, yy)
            with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
                rgb = kernel(sample, cb, u, v)
            if rgb.shape != (len(axis[y:y + 32]), size, 3) or not np.isfinite(rgb).all():
                raise ValueError('The decoded shader produced a nonfinite result for these inputs. Raw values are preserved; preview unavailable for this design.')
            if statistics is not None:
                outside += int(np.any((rgb < 0) | (rgb > 1), axis=2).sum())
                raw_min = min(raw_min, float(rgb.min()))
                raw_max = max(raw_max, float(rgb.max()))
            result[y:y + 32, :, :3] = np.rint(linear_to_srgb(rgb) * 255).astype(np.uint8)
            result[y:y + 32, :, 3] = 255
        if statistics is not None:
            statistics.update(outside_display_percent=100 * outside / (size * size),
                              raw_min=raw_min, raw_max=raw_max, samples=size * size)
        return result

    def body_texture(self, doc, size=512, statistics=None):
        decoded = self.decoded(doc)
        species = doc['species']
        self.load(species)
        profile = self.profiles[species]['body']
        pattern = profile['patterns'][doc['pattern']]['textures']
        common = self.skins.data['common_textures']
        if self.profiles[species].get('body_kernel') == 'legacy-painted':
            binding = self.profiles[species]['legacy_uniforms']
            values = dict(profile['defaults'], SkinNoiseTiling=doc['variation'])
            params = [np.atleast_1d(np.asarray(values.get(p['name'], p['default']), np.float32)) for p in binding['numeric_parameters']]
            cb = np.zeros(binding['uniform_floats'], np.float32)
            needed = set(binding['color_uniform_components']); filled = set()
            for program in binding['preshaders']:
                if len(program['fields']) != 1: raise ValueError('Unsupported legacy uniform fields')
                offset, component, count = program['fields'][0]
                used = needed.intersection(range(offset, offset + count))
                if not used: continue  # Animation/condition uniforms are outside the clean color slice.
                result = preshader(program['bytecode'], params)
                if component != 0 or count != len(result) or offset + count > len(cb): raise ValueError('Invalid legacy uniform output')
                cb[offset:offset + count] = result
                filled.update(used)
            if filled != needed: raise ValueError('Missing legacy color uniform')
            packages = {6: profile['textures']['Base_Mask'], 11: profile['textures']['Base_RoughAlbedoCavityMap'],
                        12: pattern['AdultTexture'], 13: common['skin_noise']}
            images = {slot: self.image(p) for slot, p in packages.items()}
            return self.bake_kernel(legacy_color, images, cb.reshape(-1, 4), size, statistics)
        self.check_material_range(decoded['overrides'])
        packages = {6: profile['textures']['Base_Mask'], 10: common['growth_noise'], 11: profile['textures']['Base_RoughAlbedoCavityMap'],
            12: pattern['AdultTexture'], 13: pattern['JuvenileTexture'], 14: pattern['HatchlingTexture'], 15: common['skin_noise']}
        images = {slot: self.image(p) for slot, p in packages.items()}
        uniforms = self.skins.uniforms(species, doc['growth'], doc['female'], doc['variation'], decoded)
        kernel = dilo_color if self.profiles[species].get('body_kernel') == 'dilophosaurus' else color
        return self.bake_kernel(kernel, images, uniforms, size, statistics)

    def eye_texture(self, doc, size=256):
        decoded = self.decoded(doc)
        self.check_material_range({'Color_Iris_Primary': decoded['overrides']['Color_Iris_Primary']})
        profile = self.profiles[doc['species']]['eye']
        if profile['kernel'] == 'source-texture':
            pixels = np.rint(linear_to_srgb(self.image(profile['textures']['5'])[:, :, :3]) * 255).astype(np.uint8)
            return np.ascontiguousarray(Image.fromarray(pixels).resize((size, size), Image.Resampling.LANCZOS).convert('RGBA'))
        images = {int(slot): self.image(p) for slot, p in profile['textures'].items()}
        kernel = {'6931': color_6931, '3188': color_3188, '6909': color_6909, '3193': color_3193}[profile['kernel']]
        return self.bake_kernel(kernel, images, self.skins.eyes.uniforms(doc['species'], decoded), size)

    def material(self, doc, size=512):
        mesh = self.load(doc['species'])
        body = self.body_texture(doc, size)
        eyes = self.eye_texture(doc)
        if self.surface is None:
            p = self.profiles[doc['species']]['surface']
            uniforms = np.zeros((4, 4), np.float32)
            uniforms[3, 1] = p['detail_scale']
            self.surface = dict(maps=tuple(self.image(p['textures'][str(i)], True) for i in (4, 5, 6)),
                uniforms=uniforms, kernel=self.skins.surfaces.kernel, roughness=self.image(p['roughness'], True),
                masked_normals=p.get('normal_variant') == 'masked')
        geometry = dict(self.skins.body_geometry(mesh, doc['species']))
        profile = self.profiles[doc['species']]
        body_indices, eye_indices, cutout_indices = [], [], []
        cutout = profile.get('cutout', {})
        if cutout:
            # Basic-lighting fallback carries the same recovered mask in alpha.
            # Detailed lighting samples the full available mask directly in GLSL.
            mask = self.image(profile['body']['textures']['Base_Mask'])
            axis = (np.arange(size, dtype=np.float32) + .5) / size
            for y in range(0, size, 32):
                u, v = np.meshgrid(axis, axis[y:y + 32]); sampled = bilinear(mask, u, v)
                opacity = np.clip((sampled[1] + sampled[2]) + sampled[0], 0, 1)
                body[y:y + 32, :, 3] = np.rint(opacity * 255).astype(np.uint8)
        for section in mesh.data['sections']:
            slot = section['material']
            if slot in cutout.get('slots', []):
                destination = cutout_indices
            elif slot in profile['body_slots']:
                destination = body_indices
            elif slot in profile['eye_slots']:
                destination = eye_indices
            else:
                raise ValueError('Unmapped material slot in this model')
            start = section['base_index']
            destination.extend(mesh.indices[start:start + section['triangles'] * 3])
        if len(body_indices) + len(eye_indices) + len(cutout_indices) != len(mesh.indices):
            raise ValueError('Material sections do not cover the model')
        geometry.update(skin_indices=np.ascontiguousarray(body_indices, np.uint32),
                        skin_cutout_indices=np.ascontiguousarray(cutout_indices, np.uint32),
                        skin_cutout_threshold=cutout.get('threshold', 0.),
                        indices=np.ascontiguousarray(eye_indices, np.uint32))
        return SimpleNamespace(**geometry, skin_texture=body, eye_texture=eyes, surface=self.surface)

    def shape(self, doc):
        self.validate_document(doc)
        mesh = self.load(doc['species'])
        return self.shapes.preview(doc['species'], mesh, doc['growth'], doc.get('prime', False))

    def clear(self):
        self.mesh = self.surface = self.current = None
        self.images.clear()
        self.skins.geometry.clear()
        self.shapes.clear()
