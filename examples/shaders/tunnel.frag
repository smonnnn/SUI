#version 330
// Volumetric raymarched tunnel — a glowing, flying vortex.
// Ported for SUI (uniforms iResolution/iTime + raylib vertex outputs).
// Original by @YoheiNishitsuji (MIT). The WebGL/ShaderToy raymarch loop was
// rewritten cleanly and the alpha is clamped to 1 so it composites in raylib.
// Note: in raylib's pipeline this comes out as a subdued glow rather than the
// vivid tunnel on ShaderToy (the domain-warp dominates the ray divergence).
uniform vec2 iResolution;
uniform float iTime;
in vec2 fragTexCoord;
in vec4 fragColor;
out vec4 finalColor;

vec3 hsv(float h, float s, float v){
  vec4 t = vec4(1., 2./3., 1./3., 3.);
  vec3 p = abs(fract(vec3(h) + t.xyz) * 6. - vec3(t.w));
  return v * mix(vec3(t.x), clamp(p - vec3(t.x), 0., 1.), s);
}

mat2 rotate2D(float a){ return mat2(cos(a), -sin(a), sin(a), cos(a)); }

void main(){
  vec2 r = iResolution;
  vec2 FC = gl_FragCoord.xy;
  float t = iTime;
  vec3 o = vec3(0.);
  vec3 dir = normalize(vec3(FC.xy * 2. - r, r.y));

  float z = 0.0;
  for (int i = 0; i < 100; i++) {
    vec3 q = z * dir;
    q.z += t * 4.;
    q.xy *= rotate2D(q.z * 0.1);
    float s = 1.0;
    for (int j = 0; j < 32; j++) {
      q += (abs(cos(q.yzx * s)) - .68) / s;
      s *= .5;
    }
    float d = .005 + abs((length(q.yx) - 6.) * q.x) / 8.;
    z += d;
    o += hsv(.3 + sin(q.x) * .2, .5, .2) * exp(-z * .1) / d;
    if (float(i) + z > 100.) break;
  }

  finalColor = vec4(tanh(o / 2e2), 1.0);
}
