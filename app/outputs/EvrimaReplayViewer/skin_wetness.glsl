// Shader 718 passes the untransformed input normal to shader 701.
float recovered_wet_factor(float amount,float direction,float source_normal_z) {
    if(amount==0.0) return 0.0;
    return clamp(((source_normal_z*direction+1.590000033378601)*5.0)*amount,0.0,1.0);
}
vec3 recovered_wet_color(vec3 color,float factor) {
    return color+(color*-0.5)*factor;
}
float recovered_wet_roughness(float roughness,float factor) {
    return roughness+(0.20000000298023224-roughness)*factor;
}
