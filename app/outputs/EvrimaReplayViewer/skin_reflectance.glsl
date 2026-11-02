// Clean material inputs recovered from shader-701; lighting is an independent preview.
vec2 recovered_reflectance(vec2 uv) {
    return vec2(clamp(texture2D(roughness_map,uv).r,0.0,1.0),0.003999999970197676);
}
