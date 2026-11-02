"""Model deformation separate from skin color. Never infer species scale curves."""
import numpy as np
from dinosaur_models import DinosaurModels
from morph_library import MorphLibrary


class SkinShapes:
    def __init__(self):
        self.models = DinosaurModels()
        self.morphs = MorphLibrary()
        self.current = None

    def clear(self):
        self.models.meshes.clear()
        self.models.morphs.clear()
        self.models.cache.clear()
        self.morphs.clear()
        self.current = None

    def full_support(self, species):
        return species in self.models.profiles

    def elder_support(self, species):
        row = self.morphs.models.get('SK_' + species, {})
        return sum('Elder' in name for name in row.get('names', [])) == 1

    def support_note(self, species):
        if self.full_support(species):
            return 'Recovered growth proportions and standard/prime size curves.'
        if not self.elder_support(species):
            return 'Stored reference model only. Growth changes skin colors; growth proportions and Prime shape are unavailable.'
        return 'Experimental elder shape only: shared blend rule on this species’ stored target. Species-specific activation and size curves are unverified; juvenile proportions are not applied.'

    def preview(self, species, mesh, growth, prime):
        if species != self.current:
            self.clear()
            self.current = species
        if self.full_support(species):
            source = self.models.mesh(species)
            if not np.array_equal(source.positions, mesh.positions) or not np.array_equal(source.indices, mesh.indices):
                raise ValueError('Growth profile geometry does not match the skin model')
            def shape(flag):
                positions, scale, info = self.models.shape(species, growth, flag)
                return positions * scale, info
        elif self.elder_support(species):
            source = self.morphs.load('SK_' + species)
            if not np.array_equal(source.positions, mesh.positions) or not np.array_equal(source.indices, mesh.indices):
                raise ValueError('Elder shape geometry does not match the skin model')
            targets = [name for name in self.morphs.targets if 'Elder' in name]
            if len(targets) != 1:
                raise ValueError('No unambiguous elder shape for this species')
            def shape(flag):
                # This is explicitly an experimental shared-rule illustration, not a
                # verified species runtime binding. No guessed scale multiplier.
                weight = max(0., min(1. if flag and growth > .75 else .2, (growth - .75) * 4))
                return self.morphs.shape(targets[0], weight), dict(scale=1., morph_weights={'elder': weight})
        else:
            def shape(flag):
                return mesh.positions, dict(scale=1., morph_weights={'elder': 0.})
        standard, standard_info = shape(False)
        elder, prime_info = shape(True)
        points, info = (elder, prime_info) if prime else (standard, standard_info)
        return dict(points=points, camera_standard=standard, camera_prime=elder,
            camera_standard_scale=standard_info['scale'], camera_prime_scale=prime_info['scale'],
            verified_size=self.full_support(species), note=self.support_note(species),
            state=('Prime' if prime else 'Standard') if self.full_support(species) or self.elder_support(species) else 'Reference model', scale=info['scale'],
            elder_weight=info['morph_weights'].get('elder', 0.),
            effect_active=growth > .75 and prime and (self.full_support(species) or self.elder_support(species)))
