// Shader-701 final blood coating stage; coverage uses the original noise red channel.
float recovered_blood_coverage(vec2 uv,float amount) {
    float threshold=1.0-amount*0.699999988079071;
    float noise=texture2D(blood_noise,uv).r;
    return threshold<noise && abs(threshold-noise)>9.999999747378752e-06 ? 1.0 : 0.0;
}
vec3 recovered_blood_color(vec3 color,float coverage) {
    return color+(color*vec3(-0.4470589756965637,-0.8627449870109558,-0.8627449870109558))*coverage;
}
float recovered_blood_roughness(float roughness,float coverage,float dry) {
    return roughness+(0.05000000074505806-roughness+(roughness-0.05000000074505806)*dry)*coverage;
}
