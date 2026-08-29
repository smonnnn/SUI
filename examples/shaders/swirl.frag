#version 330
// Swirling kaleidoscope — a spiraling wave field with auto-spinning hue.
uniform vec2 iResolution;
uniform float iTime;
out vec4 finalColor;
void main(){
    vec2 uv = (gl_FragCoord.xy - 0.5 * iResolution.xy) / iResolution.y;
    float r = length(uv);
    float a = atan(uv.y, uv.x);
    float w = sin(12.0 * a - 8.0 / max(r, 0.03) + iTime) * exp(-2.0 * r);
    vec3 col = 0.5 + 0.5 * cos(vec3(0.0, 2.1, 4.2) + iTime * 0.5 + w * 3.0);
    finalColor = vec4(col, 1.0);
}
