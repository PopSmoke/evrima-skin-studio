"""Bounded finite-input reconstruction of the shared native carcass shape mapping.

Evidence: outputs/AssetDecode/carcass-shape-native-validation.json.
This models shape values, not corpse transitions, materials or health damage.
"""
import math
import numbers
import struct


def f32(value):
    if isinstance(value, bool) or not isinstance(value, numbers.Real) or not math.isfinite(value):
        raise ValueError('Finite numeric state required')
    try:
        result = struct.unpack('<f', struct.pack('<f', value))[0]
    except (OverflowError, struct.error) as exc:
        raise ValueError('State exceeds finite float32 range') from exc
    if not math.isfinite(result):
        raise ValueError('State exceeds finite float32 range')
    return result


BODY_CAP = f32(1.2)


def food_depletion(food, maximum_food, previous=0., corpse_type=0, authority=True):
    food, maximum_food, previous = map(f32, (food, maximum_food, previous))
    if maximum_food <= 0 or not 0 <= previous <= 1:
        raise ValueError('Positive maximum food and previous depletion from zero to one required')
    if type(authority) is not bool or type(corpse_type) is not int or not 0 <= corpse_type <= 255:
        raise ValueError('Boolean authority and byte-sized corpse state required')
    if not authority or previous >= 1 or corpse_type > 1:
        return previous
    return max(0., min(1., f32(1. - f32(food / maximum_food))))


def visual_weights(depletion, forced_opening):
    depletion, forced_opening = map(f32, (depletion, forced_opening))
    if not 0 <= depletion <= 1 or not 0 <= forced_opening <= 1:
        raise ValueError('Preview depletion and forced opening must be from zero to one')
    body = max(0., min(BODY_CAP, f32(depletion + forced_opening)))
    return dict(BodyGore=body, LegGore=depletion, NeckGore=depletion, Rib_Meat_Morph=body)


def preview_weights(food_remaining_percent, forced_opening):
    percent = f32(food_remaining_percent)
    if not 0 <= percent <= 100:
        raise ValueError('Food remaining must be from zero to 100 percent')
    # A fresh hypothetical update, not state carried over from replay history.
    return visual_weights(food_depletion(percent, 100.), forced_opening)
