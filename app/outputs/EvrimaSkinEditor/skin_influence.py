"""Display-space sensitivity probes, not anatomical masks or game validation."""
import copy
import math
from skin_document import SLOTS, validate


def probe_documents(source, slot, low, high):
    validate(source)
    if slot not in SLOTS: raise ValueError('Choose a color section.')
    if not all(math.isfinite(v) for v in (low, high)) or low == high:
        raise ValueError('Choose two different finite probe values.')
    docs = {'Current skin': copy.deepcopy(source)}
    for label, value in (('Low probe', low), ('High probe', high)):
        doc = copy.deepcopy(source)
        doc['colors'][slot][:3] = [value]*3
        if slot == 'e': doc['default_eyes'] = False
        docs[label] = validate(doc)
    return docs


def difference_overlay(baseline, low, high, threshold=8):
    """Union of the two probe differences in the final fixed-camera pictures."""
    import numpy as np
    from PIL import Image
    if type(threshold) is not int or not 0 <= threshold <= 255:
        raise ValueError('Pixel threshold must be an integer from 0 to 255.')
    arrays = [np.asarray(im.convert('RGB'), dtype=np.int16) for im in (baseline, low, high)]
    a,b,c = arrays
    if a.shape != b.shape or a.shape != c.shape: raise ValueError('Probe images must have matching sizes.')
    delta = np.maximum(np.max(abs(a-b), axis=2), np.max(abs(a-c), axis=2))
    changed = delta > threshold
    gray = np.rint(np.mean(a, axis=2)*.4).astype(np.uint8)
    output = np.repeat(gray[..., None], 3, axis=2)
    output[changed] = (255, 158, 38)
    count = int(changed.sum())
    return Image.fromarray(output), dict(changed_pixels=count, image_pixels=int(changed.size),
        image_percent=float(count / max(1,changed.size)*100), max_difference=int(delta.max()), threshold=threshold)
