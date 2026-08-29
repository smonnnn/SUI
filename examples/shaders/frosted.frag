#version 330
// "Frosted glass" for SUI. Samples the scene behind the box (u_backdrop,
// provided automatically for any shader that declares it) and applies a
// frosted/gaussian-ish blur with a cool tint. Use on a translucant panel to
// blur whatever is underneath (e.g. a live shader wallpaper).
uniform vec2 iResolution;
uniform sampler2D u_backdrop;
in vec2 fragTexCoord;
in vec4 fragColor;
out vec4 finalColor;

vec3 blur9(vec2 uv, vec2 px) {
  vec3 s = texture(u_backdrop, uv).rgb * 4.0;
  s += texture(u_backdrop, uv + vec2(px.x, 0.0)).rgb * 2.0;
  s += texture(u_backdrop, uv - vec2(px.x, 0.0)).rgb * 2.0;
  s += texture(u_backdrop, uv + vec2(0.0, px.y)).rgb * 2.0;
  s += texture(u_backdrop, uv - vec2(0.0, px.y)).rgb * 2.0;
  s += texture(u_backdrop, uv + px).rgb;
  s += texture(u_backdrop, uv - px).rgb;
  s += texture(u_backdrop, uv + vec2(px.x, -px.y)).rgb;
  s += texture(u_backdrop, uv + vec2(-px.x, px.y)).rgb;
  return s / 16.0;
}

void main() {
  // raylib textures are stored y-flipped, so mirror the v coordinate.
  vec2 uv = gl_FragCoord.xy / iResolution;
  uv.y = 1.0 - uv.y;
  vec3 base = blur9(uv, vec2(1.5, 1.5) / iResolution);
  // slight prismatic/cool tint, ~frost amount; alpha keeps it translucent so the
  // underlying wallpaper still reads through like real frosted glass.
  vec3 tinted = base * vec3(0.78, 0.88, 1.0) + vec3(0.03, 0.06, 0.12);
  finalColor = vec4(mix(base, tinted, 0.45), 0.82);
}
