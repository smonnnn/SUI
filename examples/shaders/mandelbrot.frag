#version 330
// Infinite zooming Mandelbrot — continuously dives into the Seahorse Valley.
// The zoom ramps 1x -> 8x every ~8 seconds and wraps seamlessly (the seahorse
// is self-similar under ~8x), so each cycle you descend another level forever.
uniform vec2 iResolution;
uniform float iTime;
in vec2 fragTexCoord;
in vec4 fragColor;
out vec4 finalColor;
void main(){
    vec2 uv = (gl_FragCoord.xy - 0.5 * iResolution.xy) / iResolution.y;
    float zoom = pow(8.0, fract(iTime * 0.12));      // 1x -> 8x -> (seamless wrap)
    vec2 c = vec2(-0.7453, 0.1127) + uv / zoom;      // seahorse valley
    vec2 z = vec2(0.0);
    float it = 0.0;
    for (int i = 0; i < 110; i++) {
        z = vec2(z.x * z.x - z.y * z.y, 2.0 * z.x * z.y) + c;
        if (dot(z, z) > 4.0) { it = float(i); break; }
    }
    vec3 col = 0.5 + 0.5 * cos(vec3(0.0, 0.7, 1.1) * 1.2 + it * 0.15);
    finalColor = vec4(col, 1.0);
}
