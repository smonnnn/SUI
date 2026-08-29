#version 330
// "Waves" by @XorDev  (X.com/XorDev/status/1722433311685906509)
// https://www.shadertoy.com/playlist/fXlGDN
//
// Adapted for SUI: uniforms iResolution/iTime + raylib vertex outputs, the
// external noise texture replaced with a cheap procedural seed, and the alpha
// clamped to 1 so it composites.
uniform vec2 iResolution;
uniform float iTime;
in vec2 fragTexCoord;
in vec4 fragColor;
out vec4 finalColor;

void main(){
  vec2 I = gl_FragCoord.xy;
  vec3 r = vec3(iResolution, 1.0);
  // original seeded the loop with a noise texture; use a tiny hash instead
  float seed = fract(sin(dot(floor(I) * 0.001, vec2(12.9898, 78.233))) * 43758.5453);
  vec4 col = vec4(0.0);
  for (float i = seed + 9.0; i++ < 100.0; ) {
    vec3 p = vec3((I - r.xy * 0.5) / r.x * i, i + iTime * 0.1) * 0.2;
    col += max(cos(dot(cos(p), sin(p.yzx * 0.8)) * 4.0 + p.z + vec4(0.0, 1.0, 2.0, 3.0)), 0.0) / i * 0.7;
  }
  finalColor = vec4(col.rgb, 1.0);
}
