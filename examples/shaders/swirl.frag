#version 330
// Swirling kaleidoscope — a rotating vortex with a soft vignette.
uniform vec2 iResolution;
uniform float iTime;
in vec2 fragTexCoord;
in vec4 fragColor;
out vec4 finalColor;
void main(){
    vec2 uv = (gl_FragCoord.xy - 0.5 * iResolution.xy) / iResolution.y;
    float a = atan(uv.y, uv.x);
    float r = length(uv);
    float ang = a + 8.0 * r - iTime * 0.8;
    vec3 col = vec3(0.5 + 0.5 * sin(ang * 3.0),
                    0.5 + 0.5 * sin(ang * 3.0 + 2.1),
                    0.5 + 0.5 * sin(ang * 3.0 + 4.2));
    col *= smoothstep(0.0, 0.15, r) * (1.0 - smoothstep(0.75, 1.1, r));
    finalColor = vec4(col, 1.0);
}
