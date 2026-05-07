import { Color, Vector2 } from "three";

export const DitherShader = {
  uniforms: {
    tDiffuse: { value: null },
    resolution: { value: new Vector2() },
    ditherColor: { value: new Color(0x848bd8) },
  },

  vertexShader: /* glsl */ `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,

  fragmentShader: /* glsl */ `
    uniform sampler2D tDiffuse;
    uniform vec2 resolution;
    uniform vec3 ditherColor;
    varying vec2 vUv;

    // 4x4 Bayer dither pattern (more compatible than 8x8 array)
    float bayer4(vec2 p) {
      vec2 pp = floor(mod(p, 4.0));
      float x = pp.x;
      float y = pp.y;

      // 4x4 Bayer matrix encoded as conditionals for WebGL 1.0 compatibility
      float m = 0.0;
      if (y < 2.0) {
        if (x < 2.0) {
          if (y < 1.0) m = (x < 1.0) ? 0.0 : 8.0;
          else m = (x < 1.0) ? 12.0 : 4.0;
        } else {
          if (y < 1.0) m = (x < 3.0) ? 2.0 : 10.0;
          else m = (x < 3.0) ? 14.0 : 6.0;
        }
      } else {
        if (x < 2.0) {
          if (y < 3.0) m = (x < 1.0) ? 3.0 : 11.0;
          else m = (x < 1.0) ? 15.0 : 7.0;
        } else {
          if (y < 3.0) m = (x < 3.0) ? 1.0 : 9.0;
          else m = (x < 3.0) ? 13.0 : 5.0;
        }
      }
      return m / 16.0;
    }

    void main() {
      vec4 color = texture2D(tDiffuse, vUv);
      float luma = dot(color.rgb, vec3(0.299, 0.587, 0.114));

      // Gamma-boost to pull out detail from dark regions
      luma = pow(luma, 0.5);
      luma = smoothstep(0.1, 0.7, luma);

      vec2 pixel = vUv * resolution;
      float threshold = bayer4(pixel);
      float dithered = 1.0 - step(threshold, luma);

      // Output colored pixels on transparent background
      gl_FragColor = vec4(ditherColor * dithered, dithered);
    }
  `,
};
