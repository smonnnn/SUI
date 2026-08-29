#version 330
// "Glass Lens" for SUI. A translucent convex-lens sheen drawn over a box: a
// cool glass tint that's thickest at the centre, a prismatic rim, and a
// specular highlight that follows the mouse (iMouse is box-relative). The
// waves (or anything) behind the box show through because the box is drawn
// translucently on top. NOTE: this build's custom fragment shaders can't sample
// a texture (see README), so the refraction is a shading illusion, not a live
// sample of the backdrop.
uniform vec2 iResolution;
uniform float iTime;
uniform vec2 iMouse;
in vec2 fragTexCoord;
in vec4 fragColor;
out vec4 finalColor;

void main() {
  vec2 uv = gl_FragCoord.xy / iResolution;   // 0..1 across the box
  vec2 p = uv - 0.5;                          // centred
  float d = length(p) * 2.0;                  // 0 centre .. 1.4 corner
  float R = 0.88;                             // lens radius
  float inside = 1.0 - smoothstep(R - 0.05, R, d);   // antialiased round mask

  // specular sheen that follows the cursor (iMouse is box-relative, px)
  vec2 m = iMouse / iResolution;  m.y = 1.0 - m.y;
  float inBox = step(0.0, m.x) * step(m.x, 1.0) * step(0.0, m.y) * step(m.y, 1.0);
  vec2 hv = uv - m - vec2(0.10, -0.12);
  float spec = 0.0;
  if (inBox > 0.5) {
    spec = exp(-7.0 * dot(hv, hv)) * 0.8;
    spec += exp(-11.0 * dot(hv * 2.1, hv * 2.1)) * 0.4;
  }
  // fixed glint near the rim so the lens reads even when idle
  float rim = smoothstep(R * 0.78, R * 0.5, d) * 0.22;

  // cool glass -> bright centre gradient, prismatic at the rim
  vec3 tint = mix(vec3(0.42, 0.60, 0.80), vec3(0.10, 0.16, 0.24), rim);
  tint = mix(tint, vec3(1.0, 0.99, 0.95), spec);
  // translucent so the backdrop (waves) shines through
  float a = inside * 0.30;
  finalColor = vec4(tint, a);
}
