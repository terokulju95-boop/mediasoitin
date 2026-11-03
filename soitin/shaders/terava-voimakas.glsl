// Mediasoitin: mukautuva terävöitys (voimakas)
// Terävöittää reunoja vähemmän siellä, missä kontrasti on jo suuri,
// joten kuvaan ei synny haloja eikä kohinaa korostu liikaa.
// (Toimintaperiaate: Contrast Adaptive Sharpening.)

//!HOOK LUMA
//!BIND HOOKED
//!DESC Mediasoitin terävöitys (voimakas)

#define SHARPNESS 0.8

vec4 hook() {
    float a = HOOKED_texOff(vec2( 0.0, -1.0)).x;
    float b = HOOKED_texOff(vec2(-1.0,  0.0)).x;
    float c = HOOKED_texOff(vec2( 0.0,  0.0)).x;
    float d = HOOKED_texOff(vec2( 1.0,  0.0)).x;
    float e = HOOKED_texOff(vec2( 0.0,  1.0)).x;
    float mn = min(min(min(a, b), min(d, e)), c);
    float mx = max(max(max(a, b), max(d, e)), c);
    float amp = sqrt(clamp(min(mn, 1.0 - mx) / max(mx, 1e-5), 0.0, 1.0));
    float w = amp * (-1.0 / mix(8.0, 5.0, SHARPNESS));
    float res = ((a + b + d + e) * w + c) / (1.0 + 4.0 * w);
    return vec4(clamp(res, 0.0, 1.0), 0.0, 0.0, 1.0);
}
