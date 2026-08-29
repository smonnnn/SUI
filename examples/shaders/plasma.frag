#version 330
uniform vec2 iResolution;
uniform float iTime;
in vec2 fragTexCoord;
in vec4 fragColor;
out vec4 finalColor;
void main(){
    vec2 uv = gl_FragCoord.xy / iResolution;
    float t = iTime;
    float d = sin(uv.x*10.0 + t) * cos(uv.y*10.0 - t);
    vec3 col = vec3(0.5 + 0.5*sin(uv.x*6.0 + d*3.0 + t),
                    0.5 + 0.5*cos(uv.y*6.0 + d*3.0 - t),
                    0.5 + 0.5*sin((uv.x+uv.y)*4.0 + d*2.0));
    finalColor = vec4(col, 1.0);
}
