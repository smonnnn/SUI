#version 330
// "Flow Field" for SUI — a framebuffer-feedback simulation. Each frame the
// previous frame is advected along a smooth noise field (dragging the trails),
// faded, and new bright streaks are deposited, so particles flow and leave
// hue-shifting trails just like the original CPU script, but on the GPU.
//
// Uses SUI's ping-pong feedback: the engine renders this shader sampling the
// previous frame as 'texture0'. `uniform float u_feedback;` is the marker that
// enables it. u_speed/u_pause/u_intensity/u_fade are driven by box attributes
// (e.g. `.speed=calc(...)`), set by the engine.
uniform float u_feedback;
uniform vec2 iResolution;
uniform float iTime;
uniform float u_speed;      // advection speed (0 disables movement)
uniform float u_pause;      // 1 = freeze the simulation
uniform float u_intensity;  // streak brightness
uniform float u_fade;       // trail persistence (0.90..0.99)
uniform sampler2D texture0;
in vec2 fragTexCoord;
in vec4 fragColor;
out vec4 finalColor;

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x),
               mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x), f.y);
}
float fbm(vec2 p) {
    float v = 0.0, a = 0.55;
    for (int i = 0; i < 5; i++) { v += a * noise(p); p = p * 2.03 + vec2(11.3, 7.1); a *= 0.5; }
    return v;
}
vec3 hsv(float h, float s, float v) {
    vec3 c = vec3(h, s, v);
    vec3 rgb = clamp(abs(mod(c.x * 6.0 + vec3(0.0, 4.0, 2.0), 6.0) - 3.0) - 1.0, 0.0, 1.0);
    return c.z * mix(vec3(1.0), rgb, c.y);
}

void main() {
    vec2 uv = fragTexCoord;
    if (u_pause > 0.5) { finalColor = vec4(texture(texture0, uv).rgb, 1.0); return; }

    float speed = u_speed > 0.0 ? u_speed : 1.0;
    float fade  = u_fade  > 0.0 ? u_fade  : 0.93;
    float inten = u_intensity > 0.0 ? u_intensity : 1.0;
    float t = iTime;

    // smooth flow-field direction from fbm
    vec2 q = uv * iResolution;
    vec2 p = q * 0.0035 + vec2(t * 0.05);
    float n1 = fbm(p);
    float n2 = fbm(p + vec2(5.2, 1.3) + t * 0.03);
    vec2 flow = normalize(vec2(n1 - 0.5, n2 - 0.5) + 1e-4);

    // advect the previous frame along the flow (drags + curls the trails)
    vec2 prevUV = fract(uv + flow * speed * 0.011);
    vec3 prev = texture(texture0, prevUV).rgb * fade;

    // deposit moving streaks that ride the flow
    vec2 pd = q * 0.02;
    float s1 = pow(abs(noise(pd * 2.5 + flow * 3.0 + vec2(t * 0.7))), 5.0);
    float s2 = pow(abs(noise(pd * 4.0 - flow * 4.0 + vec2(-t * 0.5))), 6.0) * 0.6;
    float streak = (s1 + s2) * inten;
    vec3 hue = hsv(fract(t * 0.03 + uv.x * 0.4 + uv.y * 0.2), 0.85, 1.0);
    vec3 col = max(prev, hue * streak);

    finalColor = vec4(col, u_feedback);   // u_feedback is the ping-pong marker
}
