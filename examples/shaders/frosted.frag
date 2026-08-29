#version 330
// "Frosted Glass" for SUI, produced procedurally (this build's custom fragment
// shaders can't sample a texture — see README). A translucent cool pane that
// frosts whatever the box sits on top of; use it on a translucent box to get a
// glassy card over the scene behind it.
uniform vec2 iResolution;
uniform float iTime;
uniform vec2 iMouse;
in vec2 fragTexCoord;
in vec4 fragColor;
out vec4 finalColor;

void main() {
  vec2 uv = gl_FragCoord.xy / iResolution;
  vec2 p = uv - 0.5;
  vec3 col = mix(vec3(0.10, 0.16, 0.22), vec3(0.70, 0.84, 0.98),
                 0.35 + 0.30 * (1.0 - length(p) * 1.6));   // soft frost gradient
  // subtle light sheen across the pane
  col += vec3(0.10, 0.12, 0.16) * smoothstep(0.5, 0.0, length(p));
  float a = 0.62;   // translucent so the scene reads through
  finalColor = vec4(col, a);
}
