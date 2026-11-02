// LowHealth stages of shader-701; other injury/condition effects are excluded.
vec4 recovered_injury(vec2 uv,float amount) {
    vec2 xy=texture2D(wound_normal,uv).rg*2.0-1.0;
    float z=sqrt(clamp(1.0-dot(xy,xy),0.0,1.0));
    vec3 mask=texture2D(body_mask,uv).rgb;
    vec3 regions=clamp(2.0*mask-vec3(mask.r+mask.g+mask.b),0.0,1.0);
    float weight=amount*(1.0-pow(z,100.0))*(1.0-(regions.r+regions.g+regions.b));
    return vec4(xy*2.0,z,weight);
}
vec3 recovered_injury_color(vec3 color,float amount) {
    float grey=dot(color,vec3(0.2126390039920807,0.7151686549186707,0.07219231873750687));
    return color+(vec3(grey)-color)*amount*0.30000001192092896;
}
float recovered_injury_roughness(float roughness,float weight) {
    return roughness+(clamp(roughness*0.1,0.0,1.0)-roughness)*weight;
}
