#version 330
// Fractal zoom — a slowly breathing Mandelbrot set.
uniform vec2 iResolution;
uniform float iTime;
in vec2 fragTexCoord;
in vec4 fragColor;
out vec4 finalColor;
void main(){
    vec2 uv = (gl_FragCoord.xy - 0.5 * iResolution.xy) / iResolution.y;
    float zoom = 1.35 - 0.15 * sin(iTime * 0.3);
    vec2 c = uv * zoom;
    vec2 z = vec2(0.0);
    float it = 0.0;
    for (int i = 0; i < 80; i++) {
        z = vec2(z.x * z.x - z.y * z.y, 2.0 * z.x * z.y) + c;
        if (dot(z, z) > 4.0) { it = float(i); break; }
    }
    vec3 col = 0.5 + 0.5 * cos(vec3(0.0, 0.7, 1.1) * 1.2 + it * 0.18);
    finalColor = vec4(col, 1.0);
}
