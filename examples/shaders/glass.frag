#version 330
// "Glass Lens" for SUI — a real refracting lens over whatever is behind the box.
// Based on a Shadertoy glass-lens shader (IQ-style superellipse SDF + Schlick
// fresnel + chromatic aberration + gaussian blur + drop shadow). Adapted so the
// refracted background is 'texture0': the box's own screen footprint of the
// scene rendered without the lens (see box.py's backdrop pass).
uniform vec2 iResolution;   // this box's size (px)
uniform float iTime;
uniform vec2 iMouse;        // box-relative (px, y down)
uniform vec2 u_origin;      // this box's top-left, screen px
uniform vec2 u_screenRes;   // window size, px
uniform float u_glass;      // marker: declares this box as a lens
uniform float u_corner;     // the box's corner radius (px)
uniform float u_refract;    // counter-driven refraction strength (0..30+)
uniform sampler2D texture0;
in vec2 fragTexCoord;
in vec4 fragColor;
out vec4 finalColor;

// Schlick fresnel (user's implementation)
float fresnel(vec3 I, vec3 N, float ior) {
    float cosi = clamp(-1.0, 1.0, dot(I, N));
    float etai = 1.0, etat = ior;
    if (cosi > 0.0) { float tmp = etai; etai = etat; etat = tmp; }
    float sint = etai / etat * sqrt(max(0.0, 1.0 - cosi * cosi));
    if (sint >= 1.0) return 1.0;
    float cost = sqrt(max(0.0, 1.0 - sint * sint));
    cosi = abs(cosi);
    float Rs = ((etat * cosi) - (etai * cost)) / ((etat * cosi) + (etai * cost));
    float Rp = ((etai * cosi) - (etat * cost)) / ((etai * cosi) + (etat * cost));
    return (Rs * Rs + Rp * Rp) / 2.0;
}

// rounded-rectangle SDF (matches the box's own rounded corners)
float sdRoundBox(vec2 c, vec2 b, float r) {
    vec2 q = abs(c) - b + r;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}

// Sample the backdrop at the box's own screen footprint. The backdrop texture
// is the whole window (screen px), so map box-normalised coords (0..1 across
// the box) -> box's on-screen pixels -> texture uv (raylib textures are
// y-flipped).
vec2 toSceneUV(vec2 bx01) {
    vec2 p = u_origin + bx01 * iResolution;
    vec2 uv = p / u_screenRes;
    uv.y = 1.0 - uv.y;
    return uv;
}
vec3 sampleScene(vec2 bx01) {
    return texture(texture0, toSceneUV(bx01)).rgb;
}

// small blur for the refracted backdrop (glassy depth)
vec3 blurBG(vec2 bx01) {
    vec3 o = vec3(0.0);
    float w = 0.0;
    for (int i = 0; i < 9; i++) {
        vec2 d = vec2(float(i % 3) - 1.0, float(i / 3) - 1.0);
        float f = 1.0 - 0.28 * dot(d, d);
        f = max(f, 0.0);
        o += sampleScene(bx01 + d * 0.002).rgb * f;
        w += f;
    }
    return o / max(w, 1e-4);
}

void main() {
    vec2 R = iResolution.xy;
    vec2 fc = gl_FragCoord.xy;

    // box-normalised (0..1) coords for sampling, and centred (-1..1) coords
    // for the lens shape so it FILLS the whole box (rounded corners), matching
    // the box's real dimensions regardless of its aspect.
    vec2 nb = fc / R;
    vec2 uv = 2.0 * nb - 1.0;
    vec2 pos = vec2(0.0);
    // corner radius in centred units, matching the box's own .radius
    float rc = clamp(u_corner / (0.5 * min(R.x, R.y)), 0.0, 1.0);
    vec2 hext = vec2(1.0);

    float d = sdRoundBox(uv - pos, hext, rc);

    finalColor = vec4(sampleScene(nb), 0.0);

    if (d < 0.0) {
        // Smooth hover: ramps from the box edges (0) to the interior (1).
        float ex = min(min(iMouse.x, iMouse.y), min(R.x - iMouse.x, R.y - iMouse.y));
        float hover = smoothstep(0.0, 44.0, ex);
        vec2 mn = 2.0 * (iMouse / R) - 1.0;   // centred coords that fill the box
        vec2 focal = mix(pos, mn, hover);

        // Broad magnification: a gentle standing lens plus a wide, smooth bump
        // centred on the cursor. The gaussian is spread across the whole box so
        // it never reads as a small hard circle. The counter (u_refract) scales
        // the overall refraction strength.
        vec2 off = uv - focal;
        float dist = length(off);
        float g = exp(-1.6 * dist * dist);
        float rf = clamp(u_refract, 0.0, 30.0) / 30.0;   // 0..1
        float mag = mix(0.94, 0.52, rf) - (0.12 + 0.22 * hover) * g;
        // a touch more chromatic split as the refraction builds
        float split = 0.0012 + 0.0022 * rf;

        // distorted centred coords -> box-normalised for sampling (magnified)
        vec2 cuv = focal + off * mag;
        vec2 nbC = 0.5 * (cuv + 1.0);

        vec3 col;
        col.r = blurBG(nbC + vec2(split, 0.0)).r;
        col.g = blurBG(nbC).g;
        col.b = blurBG(nbC - vec2(split, 0.0)).b;
        col = col * vec3(0.95, 0.98, 1.0) + vec3(0.10);

        // fresnel edge reflection (gradient of the rounded-box shape)
        vec2 eps = vec2(0.01, 0.0);
        vec2 grad = vec2(
            sdRoundBox(uv + eps.xy - pos, hext, rc) - d,
            sdRoundBox(uv + eps.yx - pos, hext, rc) - d);
        vec3 normal = normalize(vec3(grad, 1.0));
        float fres = fresnel(vec3(0.0, 0.0, -1.0), normal, 1.5);
        col = mix(col, vec3(1.0), fres * 0.35);

        // broad soft sheen that glides toward the cursor (no hard dot)
        float hd = length(uv - mn);
        col += vec3(1.0, 0.99, 0.95) * hover * exp(-2.4 * hd * hd) * 0.16;

        finalColor = vec4(col, u_glass);  // u_glass used -> keeps the marker alive
    }

    // soft drop shadow hugging the lens base
    vec2 shOff = vec2(0.0, -0.012);
    float sh = sdRoundBox(uv - pos - shOff, hext, rc);
    float shadow = (1.0 - smoothstep(0.0, 0.05, sh)) * 0.25;
    finalColor.rgb = mix(finalColor.rgb, vec3(0.0), shadow * smoothstep(-0.03, 0.02, d));
}

