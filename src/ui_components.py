from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components


PLOT_BG = "rgba(0,0,0,0)"
PAPER_BG = "rgba(0,0,0,0)"
GRID = "rgba(255,255,255,0.08)"
TEXT = "#F5F7FA"
MUTED = "#A7ADBA"
GREEN = "#33D69F"
RED = "#FF5C7A"
BLUE = "#5B8CFF"
CYAN = "#37E8FF"
PURPLE = "#9B5CFF"
ORANGE = "#FFB86B"
GLASS_HOVER_BG = "rgba(13,18,28,0.94)"
GLASS_HOVER_BORDER = "rgba(55,232,255,0.45)"
BAR_LINE = "rgba(255,255,255,0.22)"


def _rgba(hex_color: str, alpha: float) -> str:
    value = hex_color.lstrip("#")
    r, g, b = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _bar_marker(color: str, alpha: float = 0.68) -> dict:
    return dict(color=_rgba(color, alpha), line=dict(color=_rgba(color, 0.95), width=1.15))


def _line_style(color: str, width: float = 2.8) -> dict:
    return dict(color=color, width=width, shape="spline", smoothing=0.45)


def _add_glow_line(fig: go.Figure, *, x, y, name: str, color: str, width: float = 2.8, mode: str = "lines", **kwargs) -> None:
    fig.add_trace(
        go.Scatter(
            x=x,
            y=y,
            mode="lines",
            line=dict(color=_rgba(color, 0.18), width=width + 6, shape="spline", smoothing=0.45),
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=y,
            mode=mode,
            name=name,
            line=_line_style(color, width),
            marker=dict(size=7, color=color, line=dict(color="rgba(255,255,255,0.28)", width=1)),
            **kwargs,
        )
    )


def load_css(path: str = "assets/jocket_final.css") -> None:
    css_path = Path(path)
    if css_path.exists():
        st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)
        if path != "assets/jocket_final.css":
            return
        components.html(
            """
            <script>
            (() => {
              const doc = window.parent.document;

              // Dynamically inject Inter variable font if not present
              if (!doc.querySelector('link[href*="fonts.googleapis.com/css2?family=Inter"]')) {
                const link = doc.createElement("link");
                link.rel = "stylesheet";
                link.href = "https://fonts.googleapis.com/css2?family=Inter:wght@100..900&display=swap";
                doc.head.appendChild(link);
              }

              // Clean up and remove global dot field and orbs to disable dot field effect
              doc.getElementById("jocket-dot-field")?.remove();
              doc.getElementById("global-cursor-orb")?.remove();
              doc.querySelectorAll(".ai-orb-stage, .ai-breathing-orb").forEach((node) => node.remove());

              // Plain-WebGL port of React Bits Aurora, using Streamlit's shared
              // background canvas host.
              const vertexShaderAurora = `#version 300 es
                in vec2 position;
                void main() {
                  gl_Position = vec4(position, 0.0, 1.0);
                }
              `;

              const fragmentShaderAurora = `#version 300 es
                precision highp float;

                uniform float uTime;
                uniform float uAmplitude;
                uniform vec3 uColorStops[3];
                uniform vec2 uResolution;
                uniform float uBlend;

                out vec4 fragColor;

                vec3 permute(vec3 x) {
                  return mod(((x * 34.0) + 1.0) * x, 289.0);
                }

                float snoise(vec2 v) {
                  const vec4 C = vec4(
                    0.211324865405187, 0.366025403784439,
                    -0.577350269189626, 0.024390243902439
                  );
                  vec2 i = floor(v + dot(v, C.yy));
                  vec2 x0 = v - i + dot(i, C.xx);
                  vec2 i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
                  vec4 x12 = x0.xyxy + C.xxzz;
                  x12.xy -= i1;
                  i = mod(i, 289.0);

                  vec3 p = permute(
                    permute(i.y + vec3(0.0, i1.y, 1.0))
                    + i.x + vec3(0.0, i1.x, 1.0)
                  );
                  vec3 m = max(
                    0.5 - vec3(
                      dot(x0, x0),
                      dot(x12.xy, x12.xy),
                      dot(x12.zw, x12.zw)
                    ),
                    0.0
                  );
                  m = m * m;
                  m = m * m;

                  vec3 x = 2.0 * fract(p * C.www) - 1.0;
                  vec3 h = abs(x) - 0.5;
                  vec3 ox = floor(x + 0.5);
                  vec3 a0 = x - ox;
                  m *= 1.79284291400159 - 0.85373472095314 * (a0 * a0 + h * h);

                  vec3 g;
                  g.x = a0.x * x0.x + h.x * x0.y;
                  g.yz = a0.yz * x12.xz + h.yz * x12.yw;
                  return 130.0 * dot(m, g);
                }

                struct ColorStop {
                  vec3 color;
                  float position;
                };

                #define COLOR_RAMP(colors, factor, finalColor) { \
                  int index = 0; \
                  for (int i = 0; i < 2; i++) { \
                    ColorStop currentColor = colors[i]; \
                    bool isInBetween = currentColor.position <= factor; \
                    index = int(mix(float(index), float(i), float(isInBetween))); \
                  } \
                  ColorStop currentColor = colors[index]; \
                  ColorStop nextColor = colors[index + 1]; \
                  float range = nextColor.position - currentColor.position; \
                  float lerpFactor = (factor - currentColor.position) / range; \
                  finalColor = mix(currentColor.color, nextColor.color, lerpFactor); \
                }

                void main() {
                  vec2 uv = gl_FragCoord.xy / uResolution;

                  ColorStop colors[3];
                  colors[0] = ColorStop(uColorStops[0], 0.0);
                  colors[1] = ColorStop(uColorStops[1], 0.5);
                  colors[2] = ColorStop(uColorStops[2], 1.0);

                  vec3 rampColor;
                  COLOR_RAMP(colors, uv.x, rampColor);

                  float height = snoise(vec2(uv.x * 2.0 + uTime * 0.1, uTime * 0.25)) * 0.5 * uAmplitude;
                  height = exp(height);
                  height = uv.y * 2.0 - height + 0.2;
                  float intensity = 0.6 * height;

                  float midPoint = 0.20;
                  float auroraAlpha = smoothstep(midPoint - uBlend * 0.5, midPoint + uBlend * 0.5, intensity);
                  vec3 auroraColor = intensity * rampColor;
                  fragColor = vec4(auroraColor * auroraAlpha, auroraAlpha);
                }
              `;

              const initAurora = (doc, win, canvas) => {
                const gl = canvas.getContext("webgl2", {
                  alpha: true,
                  premultipliedAlpha: true,
                  antialias: true
                });
                if (!gl) return null;

                gl.clearColor(0, 0, 0, 0);
                gl.enable(gl.BLEND);
                gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);

                const vs = gl.createShader(gl.VERTEX_SHADER);
                gl.shaderSource(vs, vertexShaderAurora);
                gl.compileShader(vs);
                if (!gl.getShaderParameter(vs, gl.COMPILE_STATUS)) {
                  console.error("Aurora VS compile error:", gl.getShaderInfoLog(vs));
                  return null;
                }

                const fs = gl.createShader(gl.FRAGMENT_SHADER);
                gl.shaderSource(fs, fragmentShaderAurora);
                gl.compileShader(fs);
                if (!gl.getShaderParameter(fs, gl.COMPILE_STATUS)) {
                  console.error("Aurora FS compile error:", gl.getShaderInfoLog(fs));
                  return null;
                }

                const program = gl.createProgram();
                gl.attachShader(program, vs);
                gl.attachShader(program, fs);
                gl.linkProgram(program);

                if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
                  console.error("Aurora program link error:", gl.getProgramInfoLog(program));
                  return null;
                }

                const positionLoc = gl.getAttribLocation(program, "position");
                const uTimeLoc = gl.getUniformLocation(program, "uTime");
                const uResolutionLoc = gl.getUniformLocation(program, "uResolution");
                const uAmplitudeLoc = gl.getUniformLocation(program, "uAmplitude");
                const uColorStopsLoc = gl.getUniformLocation(program, "uColorStops[0]");
                const uBlendLoc = gl.getUniformLocation(program, "uBlend");

                const positionBuffer = gl.createBuffer();
                gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
                gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
                  -1, -1,
                   3, -1,
                  -1,  3
                ]), gl.STATIC_DRAW);

                let active = true;
                let animFrameId = null;
                const hexToVec3 = (hex) => {
                  const h = hex.replace("#", "");
                  return [
                    parseInt(h.slice(0, 2), 16) / 255,
                    parseInt(h.slice(2, 4), 16) / 255,
                    parseInt(h.slice(4, 6), 16) / 255
                  ];
                };

                const baseSpeed = 1.0;
                const loadingSpeed = 1.35;
                const getSpeed = () => {
                  const marker = doc.querySelector('[data-jocket-loading-active]');
                  return marker ? loadingSpeed : baseSpeed;
                };
                const amplitude = 1.0;
                const blend = 0.5;
                const colorStops = ["#5227FF", "#7CFF67", "#5227FF"]
                  .flatMap(hexToVec3);

                function renderFrame(time) {
                  if (!active) return;
                  animFrameId = win.requestAnimationFrame(renderFrame);

                  const width = canvas.clientWidth || win.innerWidth || 1024;
                  const height = canvas.clientHeight || win.innerHeight || 768;
                  if (canvas.width !== width || canvas.height !== height) {
                    canvas.width = width;
                    canvas.height = height;
                    gl.viewport(0, 0, width, height);
                  }

                  gl.clear(gl.COLOR_BUFFER_BIT);
                  gl.useProgram(program);

                  gl.uniform1f(uTimeLoc, time * 0.001 * getSpeed());
                  gl.uniform2f(uResolutionLoc, canvas.width, canvas.height);
                  gl.uniform1f(uAmplitudeLoc, amplitude);
                  gl.uniform3fv(uColorStopsLoc, colorStops);
                  gl.uniform1f(uBlendLoc, blend);

                  gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
                  gl.enableVertexAttribArray(positionLoc);
                  gl.vertexAttribPointer(positionLoc, 2, gl.FLOAT, false, 0, 0);

                  gl.drawArrays(gl.TRIANGLES, 0, 3);
                }

                animFrameId = win.requestAnimationFrame(renderFrame);

                setTimeout(() => {
                  canvas.classList.add("active");
                }, 50);

                return {
                  destroy() {
                    active = false;
                    if (animFrameId) {
                      win.cancelAnimationFrame(animFrameId);
                    }
                    gl.getExtension('WEBGL_lose_context')?.loseContext();
                  }
                };
              };

              const initSplashCursor = (doc, win) => {
                // Reuse existing container to avoid flash on Streamlit reruns
                let container = doc.getElementById("jocket-splash-cursor-container");
                let canvas = container && container.querySelector("#jocket-fluid-canvas");
                let auroraCanvas = container && container.querySelector("#jocket-aurora-canvas");
                let reuseAurora = !!(container && auroraCanvas);

                if (!container) {
                  container = doc.createElement("div");
                  container.id = "jocket-splash-cursor-container";
                  canvas = doc.createElement("canvas");
                  canvas.id = "jocket-fluid-canvas";
                  auroraCanvas = doc.createElement("canvas");
                  auroraCanvas.id = "jocket-aurora-canvas";
                  container.appendChild(auroraCanvas);
                  container.appendChild(canvas);
                  doc.body.prepend(container);
                }

                // Only init a new aurora if we created fresh canvas; reuse keeps opacity
                const auroraInstance = reuseAurora ? null : initAurora(doc, win, auroraCanvas);

                let isActive = true;
                let animationFrameId = null;

                function pointerPrototype() {
                  this.id = -1;
                  this.texcoordX = 0;
                  this.texcoordY = 0;
                  this.prevTexcoordX = 0;
                  this.prevTexcoordY = 0;
                  this.deltaX = 0;
                  this.deltaY = 0;
                  this.down = false;
                  this.moved = false;
                  this.color = [0, 0, 0];
                }

                let config = {
                  SIM_RESOLUTION: 128,
                  DYE_RESOLUTION: 1440,
                  CAPTURE_RESOLUTION: 512,
                  DENSITY_DISSIPATION: 3.5,
                  VELOCITY_DISSIPATION: 2,
                  PRESSURE: 0.2,
                  PRESSURE_ITERATIONS: 20,
                  CURL: 5,
                  SPLAT_RADIUS: 0.15,
                  SPLAT_FORCE: 5500,
                  SHADING: true,
                  COLOR_UPDATE_SPEED: 8,
                  PAUSED: false,
                  BACK_COLOR: { r: 0.5, g: 0, b: 0 },
                  TRANSPARENT: true,
                  RAINBOW_MODE: true,
                  COLOR: '#ff0000'
                };

                let pointers = [new pointerPrototype()];

                function getWebGLContext(canvas) {
                  const params = {
                    alpha: true,
                    depth: false,
                    stencil: false,
                    antialias: false,
                    preserveDrawingBuffer: false
                  };
                  let gl = canvas.getContext('webgl2', params);
                  const isWebGL2 = !!gl;
                  if (!isWebGL2) gl = canvas.getContext('webgl', params) || canvas.getContext('experimental-webgl', params);

                  let halfFloat;
                  let supportLinearFiltering;
                  if (isWebGL2) {
                    gl.getExtension('EXT_color_buffer_float');
                    supportLinearFiltering = gl.getExtension('OES_texture_float_linear');
                  } else {
                    halfFloat = gl.getExtension('OES_texture_half_float');
                    supportLinearFiltering = gl.getExtension('OES_texture_half_float_linear');
                  }
                  gl.clearColor(0.0, 0.0, 0.0, 1.0);

                  const halfFloatTexType = isWebGL2 ? gl.HALF_FLOAT : halfFloat && halfFloat.HALF_FLOAT_OES;
                  let formatRGBA;
                  let formatRG;
                  let formatR;

                  if (isWebGL2) {
                    formatRGBA = getSupportedFormat(gl, gl.RGBA16F, gl.RGBA, halfFloatTexType, supportLinearFiltering);
                    formatRG = getSupportedFormat(gl, gl.RG16F, gl.RG, halfFloatTexType, supportLinearFiltering);
                    formatR = getSupportedFormat(gl, gl.R16F, gl.RED, halfFloatTexType, supportLinearFiltering);
                  } else {
                    formatRGBA = getSupportedFormat(gl, gl.RGBA, gl.RGBA, halfFloatTexType, supportLinearFiltering);
                    formatRG = getSupportedFormat(gl, gl.RGBA, gl.RGBA, halfFloatTexType, supportLinearFiltering);
                    formatR = getSupportedFormat(gl, gl.RGBA, gl.RGBA, halfFloatTexType, supportLinearFiltering);
                  }

                  return {
                    gl,
                    ext: {
                      formatRGBA,
                      formatRG,
                      formatR,
                      halfFloatTexType,
                      supportLinearFiltering
                    }
                  };
                }

                function getSupportedFormat(gl, internalFormat, format, type, supportLinearFiltering) {
                  if (!supportRenderTextureFormat(gl, internalFormat, format, type)) {
                    switch (internalFormat) {
                      case gl.R16F:
                        return getSupportedFormat(gl, gl.RG16F, gl.RG, type, supportLinearFiltering);
                      case gl.RG16F:
                        return getSupportedFormat(gl, gl.RGBA16F, gl.RGBA, type, supportLinearFiltering);
                      default:
                        return null;
                    }
                  }
                  return { internalFormat, format };
                }

                function supportRenderTextureFormat(gl, internalFormat, format, type) {
                  const texture = gl.createTexture();
                  gl.bindTexture(gl.TEXTURE_2D, texture);
                  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
                  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
                  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
                  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
                  gl.texImage2D(gl.TEXTURE_2D, 0, internalFormat, 4, 4, 0, format, type, null);
                  const fbo = gl.createFramebuffer();
                  gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
                  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texture, 0);
                  const status = gl.checkFramebufferStatus(gl.FRAMEBUFFER);
                  return status === gl.FRAMEBUFFER_COMPLETE;
                }

                const { gl, ext } = getWebGLContext(canvas);
                if (!ext.supportLinearFiltering) {
                  config.DYE_RESOLUTION = 256;
                  config.SHADING = false;
                }

                class Material {
                  constructor(vertexShader, fragmentShaderSource) {
                    this.vertexShader = vertexShader;
                    this.fragmentShaderSource = fragmentShaderSource;
                    this.programs = [];
                    this.activeProgram = null;
                    this.uniforms = [];
                  }
                  setKeywords(keywords) {
                    let hash = 0;
                    for (let i = 0; i < keywords.length; i++) hash += hashCode(keywords[i]);
                    let program = this.programs[hash];
                    if (program == null) {
                      let fragmentShader = compileShader(gl.FRAGMENT_SHADER, this.fragmentShaderSource, keywords);
                      program = createProgram(this.vertexShader, fragmentShader);
                      this.programs[hash] = program;
                    }
                    if (program === this.activeProgram) return;
                    this.uniforms = getUniforms(program);
                    this.activeProgram = program;
                  }
                  bind() {
                    gl.useProgram(this.activeProgram);
                  }
                }

                class Program {
                  constructor(vertexShader, fragmentShader) {
                    this.uniforms = {};
                    this.program = createProgram(vertexShader, fragmentShader);
                    this.uniforms = getUniforms(this.program);
                  }
                  bind() {
                    gl.useProgram(this.program);
                  }
                }

                function createProgram(vertexShader, fragmentShader) {
                  let program = gl.createProgram();
                  gl.attachShader(program, vertexShader);
                  gl.attachShader(program, fragmentShader);
                  gl.bindAttribLocation(program, 0, "aPosition");
                  gl.linkProgram(program);
                  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) console.trace(gl.getProgramInfoLog(program));
                  return program;
                }

                function getUniforms(program) {
                  let uniforms = [];
                  let uniformCount = gl.getProgramParameter(program, gl.ACTIVE_UNIFORMS);
                  for (let i = 0; i < uniformCount; i++) {
                    let uniformName = gl.getActiveUniform(program, i).name;
                    uniforms[uniformName] = gl.getUniformLocation(program, uniformName);
                  }
                  return uniforms;
                }

                function compileShader(type, source, keywords) {
                  source = addKeywords(source, keywords);
                  const shader = gl.createShader(type);
                  gl.shaderSource(shader, source);
                  gl.compileShader(shader);
                  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) console.trace(gl.getShaderInfoLog(shader));
                  return shader;
                }

                function addKeywords(source, keywords) {
                  if (!keywords) return source;
                  let keywordsString = '';
                  keywords.forEach(keyword => {
                    keywordsString += '#define ' + keyword + '\\n';
                  });
                  return keywordsString + source;
                }

                const baseVertexShader = compileShader(
                  gl.VERTEX_SHADER,
                  `
                    precision highp float;
                    attribute vec2 aPosition;
                    varying vec2 vUv;
                    varying vec2 vL;
                    varying vec2 vR;
                    varying vec2 vT;
                    varying vec2 vB;
                    uniform vec2 texelSize;

                    void main () {
                        vUv = aPosition * 0.5 + 0.5;
                        vL = vUv - vec2(texelSize.x, 0.0);
                        vR = vUv + vec2(texelSize.x, 0.0);
                        vT = vUv + vec2(0.0, texelSize.y);
                        vB = vUv - vec2(0.0, texelSize.y);
                        gl_Position = vec4(aPosition, 0.0, 1.0);
                    }
                  `
                );

                const copyShader = compileShader(
                  gl.FRAGMENT_SHADER,
                  `
                    precision mediump float;
                    precision mediump sampler2D;
                    varying highp vec2 vUv;
                    uniform sampler2D uTexture;

                    void main () {
                        gl_FragColor = texture2D(uTexture, vUv);
                    }
                  `
                );

                const clearShader = compileShader(
                  gl.FRAGMENT_SHADER,
                  `
                    precision mediump float;
                    precision mediump sampler2D;
                    varying highp vec2 vUv;
                    uniform sampler2D uTexture;
                    uniform float value;

                    void main () {
                        gl_FragColor = value * texture2D(uTexture, vUv);
                    }
                  `
                );

                const displayShaderSource = `
                  precision highp float;
                  precision highp sampler2D;
                  varying vec2 vUv;
                  varying vec2 vL;
                  varying vec2 vR;
                  varying vec2 vT;
                  varying vec2 vB;
                  uniform sampler2D uTexture;
                  uniform sampler2D uDithering;
                  uniform vec2 ditherScale;
                  uniform vec2 texelSize;

                  vec3 linearToGamma (vec3 color) {
                      color = max(color, vec3(0));
                      return max(1.055 * pow(color, vec3(0.416666667)) - 0.055, vec3(0));
                  }

                  void main () {
                      vec3 c = texture2D(uTexture, vUv).rgb;
                      #ifdef SHADING
                          vec3 lc = texture2D(uTexture, vL).rgb;
                          vec3 rc = texture2D(uTexture, vR).rgb;
                          vec3 tc = texture2D(uTexture, vT).rgb;
                          vec3 bc = texture2D(uTexture, vB).rgb;

                          float dx = length(rc) - length(lc);
                          float dy = length(tc) - length(bc);

                          vec3 n = normalize(vec3(dx, dy, length(texelSize)));
                          vec3 l = vec3(0.0, 0.0, 1.0);

                          float diffuse = clamp(dot(n, l) + 0.7, 0.7, 1.0);
                          c *= diffuse;
                      #endif

                      float a = max(c.r, max(c.g, c.b));
                      gl_FragColor = vec4(c, a);
                  }
                `;

                const splatShader = compileShader(
                  gl.FRAGMENT_SHADER,
                  `
                    precision highp float;
                    precision highp sampler2D;
                    varying vec2 vUv;
                    uniform sampler2D uTarget;
                    uniform float aspectRatio;
                    uniform vec3 color;
                    uniform vec2 point;
                    uniform float radius;

                    void main () {
                        vec2 p = vUv - point.xy;
                        p.x *= aspectRatio;
                        vec3 splat = exp(-dot(p, p) / radius) * color;
                        vec3 base = texture2D(uTarget, vUv).xyz;
                        gl_FragColor = vec4(base + splat, 1.0);
                    }
                  `
                );

                const advectionShader = compileShader(
                  gl.FRAGMENT_SHADER,
                  `
                    precision highp float;
                    precision highp sampler2D;
                    varying vec2 vUv;
                    uniform sampler2D uVelocity;
                    uniform sampler2D uSource;
                    uniform vec2 texelSize;
                    uniform vec2 dyeTexelSize;
                    uniform float dt;
                    uniform float dissipation;

                    vec4 bilerp (sampler2D sam, vec2 uv, vec2 tsize) {
                        vec2 st = uv / tsize - 0.5;
                        vec2 iuv = floor(st);
                        vec2 fuv = fract(st);

                        vec4 a = texture2D(sam, (iuv + vec2(0.5, 0.5)) * tsize);
                        vec4 b = texture2D(sam, (iuv + vec2(1.5, 0.5)) * tsize);
                        vec4 c = texture2D(sam, (iuv + vec2(0.5, 1.5)) * tsize);
                        vec4 d = texture2D(sam, (iuv + vec2(1.5, 1.5)) * tsize);

                        return mix(mix(a, b, fuv.x), mix(c, d, fuv.x), fuv.y);
                    }

                    void main () {
                        #ifdef MANUAL_FILTERING
                            vec2 coord = vUv - dt * bilerp(uVelocity, vUv, texelSize).xy * texelSize;
                            vec4 result = bilerp(uSource, coord, dyeTexelSize);
                        #else
                            vec2 coord = vUv - dt * texture2D(uVelocity, vUv).xy * texelSize;
                            vec4 result = texture2D(uSource, coord);
                        #endif
                        float decay = 1.0 + dissipation * dt;
                        gl_FragColor = result / decay;
                    }
                  `,
                  ext.supportLinearFiltering ? null : ['MANUAL_FILTERING']
                );

                const divergenceShader = compileShader(
                  gl.FRAGMENT_SHADER,
                  `
                    precision mediump float;
                    precision mediump sampler2D;
                    varying highp vec2 vUv;
                    varying highp vec2 vL;
                    varying highp vec2 vR;
                    varying highp vec2 vT;
                    varying highp vec2 vB;
                    uniform sampler2D uVelocity;

                    void main () {
                        float L = texture2D(uVelocity, vL).x;
                        float R = texture2D(uVelocity, vR).x;
                        float T = texture2D(uVelocity, vT).y;
                        float B = texture2D(uVelocity, vB).y;

                        vec2 C = texture2D(uVelocity, vUv).xy;
                        if (vL.x < 0.0) { L = -C.x; }
                        if (vR.x > 1.0) { R = -C.x; }
                        if (vT.y > 1.0) { T = -C.y; }
                        if (vB.y < 0.0) { B = -C.y; }

                        float div = 0.5 * (R - L + T - B);
                        gl_FragColor = vec4(div, 0.0, 0.0, 1.0);
                    }
                  `
                );

                const curlShader = compileShader(
                  gl.FRAGMENT_SHADER,
                  `
                    precision mediump float;
                    precision mediump sampler2D;
                    varying highp vec2 vUv;
                    varying highp vec2 vL;
                    varying highp vec2 vR;
                    varying highp vec2 vT;
                    varying highp vec2 vB;
                    uniform sampler2D uVelocity;

                    void main () {
                        float L = texture2D(uVelocity, vL).y;
                        float R = texture2D(uVelocity, vR).y;
                        float T = texture2D(uVelocity, vT).x;
                        float B = texture2D(uVelocity, vB).x;
                        float vorticity = R - L - T + B;
                        gl_FragColor = vec4(0.5 * vorticity, 0.0, 0.0, 1.0);
                    }
                  `
                );

                const vorticityShader = compileShader(
                  gl.FRAGMENT_SHADER,
                  `
                    precision highp float;
                    precision highp sampler2D;
                    varying vec2 vUv;
                    varying vec2 vL;
                    varying vec2 vR;
                    varying vec2 vT;
                    varying vec2 vB;
                    uniform sampler2D uVelocity;
                    uniform sampler2D uCurl;
                    uniform float curl;
                    uniform float dt;

                    void main () {
                        float L = texture2D(uCurl, vL).x;
                        float R = texture2D(uCurl, vR).x;
                        float T = texture2D(uCurl, vT).x;
                        float B = texture2D(uCurl, vB).x;
                        float C = texture2D(uCurl, vUv).x;

                        vec2 force = 0.5 * vec2(abs(T) - abs(B), abs(R) - abs(L));
                        force /= length(force) + 0.0001;
                        force *= curl * C;
                        force.y *= -1.0;

                        vec2 velocity = texture2D(uVelocity, vUv).xy;
                        velocity += force * dt;
                        velocity = min(max(velocity, -1000.0), 1000.0);
                        gl_FragColor = vec4(velocity, 0.0, 1.0);
                    }
                  `
                );

                const pressureShader = compileShader(
                  gl.FRAGMENT_SHADER,
                  `
                    precision mediump float;
                    precision mediump sampler2D;
                    varying highp vec2 vUv;
                    varying highp vec2 vL;
                    varying highp vec2 vR;
                    varying highp vec2 vT;
                    varying highp vec2 vB;
                    uniform sampler2D uPressure;
                    uniform sampler2D uDivergence;

                    void main () {
                        float L = texture2D(uPressure, vL).x;
                        float R = texture2D(uPressure, vR).x;
                        float T = texture2D(uPressure, vT).x;
                        float B = texture2D(uPressure, vB).x;
                        float C = texture2D(uPressure, vUv).x;
                        float divergence = texture2D(uDivergence, vUv).x;
                        float pressure = (L + R + B + T - divergence) * 0.25;
                        gl_FragColor = vec4(pressure, 0.0, 0.0, 1.0);
                    }
                  `
                );

                const gradientSubtractShader = compileShader(
                  gl.FRAGMENT_SHADER,
                  `
                    precision mediump float;
                    precision mediump sampler2D;
                    varying highp vec2 vUv;
                    varying highp vec2 vL;
                    varying highp vec2 vR;
                    varying highp vec2 vT;
                    varying highp vec2 vB;
                    uniform sampler2D uPressure;
                    uniform sampler2D uVelocity;

                    void main () {
                        float L = texture2D(uPressure, vL).x;
                        float R = texture2D(uPressure, vR).x;
                        float T = texture2D(uPressure, vT).x;
                        float B = texture2D(uPressure, vB).x;
                        vec2 velocity = texture2D(uVelocity, vUv).xy;
                        velocity.xy -= vec2(R - L, T - B);
                        gl_FragColor = vec4(velocity, 0.0, 1.0);
                    }
                  `
                );

                const blit = (() => {
                  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
                  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, -1, 1, 1, 1, 1, -1]), gl.STATIC_DRAW);
                  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, gl.createBuffer());
                  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array([0, 1, 2, 0, 2, 3]), gl.STATIC_DRAW);
                  gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
                  gl.enableVertexAttribArray(0);
                  return (target, clear = false) => {
                    if (target == null) {
                      gl.viewport(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight);
                      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
                    } else {
                      gl.viewport(0, 0, target.width, target.height);
                      gl.bindFramebuffer(gl.FRAMEBUFFER, target.fbo);
                    }
                    if (clear) {
                      gl.clearColor(0.0, 0.0, 0.0, 1.0);
                      gl.clear(gl.COLOR_BUFFER_BIT);
                    }
                    gl.drawElements(gl.TRIANGLES, 6, gl.UNSIGNED_SHORT, 0);
                  };
                })();

                let dye, velocity, divergence, curl, pressure;

                const copyProgram = new Program(baseVertexShader, copyShader);
                const clearProgram = new Program(baseVertexShader, clearShader);
                const splatProgram = new Program(baseVertexShader, splatShader);
                const advectionProgram = new Program(baseVertexShader, advectionShader);
                const divergenceProgram = new Program(baseVertexShader, divergenceShader);
                const curlProgram = new Program(baseVertexShader, curlShader);
                const vorticityProgram = new Program(baseVertexShader, vorticityShader);
                const pressureProgram = new Program(baseVertexShader, pressureShader);
                const gradienSubtractProgram = new Program(baseVertexShader, gradientSubtractShader);
                const displayMaterial = new Material(baseVertexShader, displayShaderSource);

                function initFramebuffers() {
                  let simRes = getResolution(config.SIM_RESOLUTION);
                  let dyeRes = getResolution(config.DYE_RESOLUTION);
                  const texType = ext.halfFloatTexType;
                  const rgba = ext.formatRGBA;
                  const rg = ext.formatRG;
                  const r = ext.formatR;
                  const filtering = ext.supportLinearFiltering ? gl.LINEAR : gl.NEAREST;
                  gl.disable(gl.BLEND);

                  if (!dye)
                    dye = createDoubleFBO(dyeRes.width, dyeRes.height, rgba.internalFormat, rgba.format, texType, filtering);
                  else
                    dye = resizeDoubleFBO(dye, dyeRes.width, dyeRes.height, rgba.internalFormat, rgba.format, texType, filtering);

                  if (!velocity)
                    velocity = createDoubleFBO(simRes.width, simRes.height, rg.internalFormat, rg.format, texType, filtering);
                  else
                    velocity = resizeDoubleFBO(
                      velocity,
                      simRes.width,
                      simRes.height,
                      rg.internalFormat,
                      rg.format,
                      texType,
                      filtering
                    );

                  divergence = createFBO(simRes.width, simRes.height, r.internalFormat, r.format, texType, gl.NEAREST);
                  curl = createFBO(simRes.width, simRes.height, r.internalFormat, r.format, texType, gl.NEAREST);
                  pressure = createDoubleFBO(simRes.width, simRes.height, r.internalFormat, r.format, texType, gl.NEAREST);
                }

                function createFBO(w, h, internalFormat, format, type, param) {
                  gl.activeTexture(gl.TEXTURE0);
                  let texture = gl.createTexture();
                  gl.bindTexture(gl.TEXTURE_2D, texture);
                  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, param);
                  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, param);
                  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
                  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
                  gl.texImage2D(gl.TEXTURE_2D, 0, internalFormat, w, h, 0, format, type, null);

                  let fbo = gl.createFramebuffer();
                  gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
                  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texture, 0);
                  gl.viewport(0, 0, w, h);
                  gl.clear(gl.COLOR_BUFFER_BIT);

                  let texelSizeX = 1.0 / w;
                  let texelSizeY = 1.0 / h;
                  return {
                    texture,
                    fbo,
                    width: w,
                    height: h,
                    texelSizeX,
                    texelSizeY,
                    attach(id) {
                      gl.activeTexture(gl.TEXTURE0 + id);
                      gl.bindTexture(gl.TEXTURE_2D, texture);
                      return id;
                    }
                  };
                }

                function createDoubleFBO(w, h, internalFormat, format, type, param) {
                  let fbo1 = createFBO(w, h, internalFormat, format, type, param);
                  let fbo2 = createFBO(w, h, internalFormat, format, type, param);
                  return {
                    width: w,
                    height: h,
                    texelSizeX: fbo1.texelSizeX,
                    texelSizeY: fbo1.texelSizeY,
                    get read() {
                      return fbo1;
                    },
                    set read(value) {
                      fbo1 = value;
                    },
                    get write() {
                      return fbo2;
                    },
                    set write(value) {
                      fbo2 = value;
                    },
                    swap() {
                      let temp = fbo1;
                      fbo1 = fbo2;
                      fbo2 = temp;
                    }
                  };
                }

                function resizeFBO(target, w, h, internalFormat, format, type, param) {
                  let newFBO = createFBO(w, h, internalFormat, format, type, param);
                  copyProgram.bind();
                  gl.uniform1i(copyProgram.uniforms.uTexture, target.attach(0));
                  blit(newFBO);
                  return newFBO;
                }

                function resizeDoubleFBO(target, w, h, internalFormat, format, type, param) {
                  if (target.width === w && target.height === h) return target;
                  target.read = resizeFBO(target.read, w, h, internalFormat, format, type, param);
                  target.write = createFBO(w, h, internalFormat, format, type, param);
                  target.width = w;
                  target.height = h;
                  target.texelSizeX = 1.0 / w;
                  target.texelSizeY = 1.0 / h;
                  return target;
                }

                function updateKeywords() {
                  let displayKeywords = [];
                  if (config.SHADING) displayKeywords.push('SHADING');
                  displayMaterial.setKeywords(displayKeywords);
                }

                updateKeywords();
                initFramebuffers();
                let lastUpdateTime = Date.now();
                let colorUpdateTimer = 0.0;

                function updateFrame() {
                  if (!isActive) return;
                  const dt = calcDeltaTime();
                  if (resizeCanvas()) initFramebuffers();
                  updateColors(dt);
                  applyInputs();
                  step(dt);
                  render(null);
                  animationFrameId = win.requestAnimationFrame(updateFrame);
                }

                function calcDeltaTime() {
                  let now = Date.now();
                  let dt = (now - lastUpdateTime) / 1000;
                  dt = Math.min(dt, 0.016666);
                  lastUpdateTime = now;
                  return dt;
                }

                function resizeCanvas() {
                  let clientW = canvas.clientWidth || win.innerWidth || 1024;
                  let clientH = canvas.clientHeight || win.innerHeight || 768;
                  let width = scaleByPixelRatio(clientW);
                  let height = scaleByPixelRatio(clientH);
                  if (canvas.width !== width || canvas.height !== height) {
                    canvas.width = width;
                    canvas.height = height;
                    return true;
                  }
                  return false;
                }

                function updateColors(dt) {
                  colorUpdateTimer += dt * config.COLOR_UPDATE_SPEED;
                  if (colorUpdateTimer >= 1) {
                    colorUpdateTimer = wrap(colorUpdateTimer, 0, 1);
                    pointers.forEach(p => {
                      p.color = generateColor();
                    });
                  }
                }

                function applyInputs() {
                  pointers.forEach(p => {
                    if (p.moved) {
                      p.moved = false;
                      splatPointer(p);
                    }
                  });
                }

                function step(dt) {
                  gl.disable(gl.BLEND);
                  curlProgram.bind();
                  gl.uniform2f(curlProgram.uniforms.texelSize, velocity.texelSizeX, velocity.texelSizeY);
                  gl.uniform1i(curlProgram.uniforms.uVelocity, velocity.read.attach(0));
                  blit(curl);

                  vorticityProgram.bind();
                  gl.uniform2f(vorticityProgram.uniforms.texelSize, velocity.texelSizeX, velocity.texelSizeY);
                  gl.uniform1i(vorticityProgram.uniforms.uVelocity, velocity.read.attach(0));
                  gl.uniform1i(vorticityProgram.uniforms.uCurl, curl.attach(1));
                  gl.uniform1f(vorticityProgram.uniforms.curl, config.CURL);
                  gl.uniform1f(vorticityProgram.uniforms.dt, dt);
                  blit(velocity.write);
                  velocity.swap();

                  divergenceProgram.bind();
                  gl.uniform2f(divergenceProgram.uniforms.texelSize, velocity.texelSizeX, velocity.texelSizeY);
                  gl.uniform1i(divergenceProgram.uniforms.uVelocity, velocity.read.attach(0));
                  blit(divergence);

                  clearProgram.bind();
                  gl.uniform1i(clearProgram.uniforms.uTexture, pressure.read.attach(0));
                  gl.uniform1f(clearProgram.uniforms.value, config.PRESSURE);
                  blit(pressure.write);
                  pressure.swap();

                  pressureProgram.bind();
                  gl.uniform2f(pressureProgram.uniforms.texelSize, velocity.texelSizeX, velocity.texelSizeY);
                  gl.uniform1i(pressureProgram.uniforms.uDivergence, divergence.attach(0));
                  for (let i = 0; i < config.PRESSURE_ITERATIONS; i++) {
                    gl.uniform1i(pressureProgram.uniforms.uPressure, pressure.read.attach(1));
                    blit(pressure.write);
                    pressure.swap();
                  }

                  gradienSubtractProgram.bind();
                  gl.uniform2f(gradienSubtractProgram.uniforms.texelSize, velocity.texelSizeX, velocity.texelSizeY);
                  gl.uniform1i(gradienSubtractProgram.uniforms.uPressure, pressure.read.attach(0));
                  gl.uniform1i(gradienSubtractProgram.uniforms.uVelocity, velocity.read.attach(1));
                  blit(velocity.write);
                  velocity.swap();

                  advectionProgram.bind();
                  gl.uniform2f(advectionProgram.uniforms.texelSize, velocity.texelSizeX, velocity.texelSizeY);
                  if (!ext.supportLinearFiltering)
                    gl.uniform2f(advectionProgram.uniforms.dyeTexelSize, velocity.texelSizeX, velocity.texelSizeY);
                  let velocityId = velocity.read.attach(0);
                  gl.uniform1i(advectionProgram.uniforms.uVelocity, velocityId);
                  gl.uniform1i(advectionProgram.uniforms.uSource, velocityId);
                  gl.uniform1f(advectionProgram.uniforms.dt, dt);
                  gl.uniform1f(advectionProgram.uniforms.dissipation, config.VELOCITY_DISSIPATION);
                  blit(velocity.write);
                  velocity.swap();

                  if (!ext.supportLinearFiltering)
                    gl.uniform2f(advectionProgram.uniforms.dyeTexelSize, dye.texelSizeX, dye.texelSizeY);
                  gl.uniform1i(advectionProgram.uniforms.uVelocity, velocity.read.attach(0));
                  gl.uniform1i(advectionProgram.uniforms.uSource, dye.read.attach(1));
                  gl.uniform1f(advectionProgram.uniforms.dissipation, config.DENSITY_DISSIPATION);
                  blit(dye.write);
                  dye.swap();
                }

                function render(target) {
                  gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
                  gl.enable(gl.BLEND);
                  drawDisplay(target);
                }

                function drawDisplay(target) {
                  let width = target == null ? gl.drawingBufferWidth : target.width;
                  let height = target == null ? gl.drawingBufferHeight : target.height;
                  displayMaterial.bind();
                  if (config.SHADING) gl.uniform2f(displayMaterial.uniforms.texelSize, 1.0 / width, 1.0 / height);
                  gl.uniform1i(displayMaterial.uniforms.uTexture, dye.read.attach(0));
                  blit(target);
                }

                function splatPointer(pointer) {
                  let dx = pointer.deltaX * config.SPLAT_FORCE;
                  let dy = pointer.deltaY * config.SPLAT_FORCE;
                  splat(pointer.texcoordX, pointer.texcoordY, dx, dy, pointer.color);
                }

                function clickSplat(pointer) {
                  const color = generateColor();
                  color.r *= 10.0;
                  color.g *= 10.0;
                  color.b *= 10.0;
                  let dx = 10 * (Math.random() - 0.5);
                  let dy = 30 * (Math.random() - 0.5);
                  splat(pointer.texcoordX, pointer.texcoordY, dx, dy, color);
                }

                function splat(x, y, dx, dy, color) {
                  splatProgram.bind();
                  gl.uniform1i(splatProgram.uniforms.uTarget, velocity.read.attach(0));
                  gl.uniform1f(splatProgram.uniforms.aspectRatio, canvas.width / canvas.height);
                  gl.uniform2f(splatProgram.uniforms.point, x, y);
                  gl.uniform3f(splatProgram.uniforms.color, dx, dy, 0.0);
                  gl.uniform1f(splatProgram.uniforms.radius, correctRadius(config.SPLAT_RADIUS / 100.0));
                  blit(velocity.write);
                  velocity.swap();

                  gl.uniform1i(splatProgram.uniforms.uTarget, dye.read.attach(0));
                  gl.uniform3f(splatProgram.uniforms.color, color.r, color.g, color.b);
                  blit(dye.write);
                  dye.swap();
                }

                function correctRadius(radius) {
                  let aspectRatio = canvas.width / canvas.height;
                  if (aspectRatio > 1) radius *= aspectRatio;
                  return radius;
                }

                function updatePointerDownData(pointer, id, posX, posY) {
                  pointer.id = id;
                  pointer.down = true;
                  pointer.moved = false;
                  pointer.texcoordX = posX / canvas.width;
                  pointer.texcoordY = 1.0 - posY / canvas.height;
                  pointer.prevTexcoordX = pointer.texcoordX;
                  pointer.prevTexcoordY = pointer.texcoordY;
                  pointer.deltaX = 0;
                  pointer.deltaY = 0;
                  pointer.color = generateColor();
                }

                function updatePointerMoveData(pointer, posX, posY, color) {
                  pointer.prevTexcoordX = pointer.texcoordX;
                  pointer.prevTexcoordY = pointer.texcoordY;
                  pointer.texcoordX = posX / canvas.width;
                  pointer.texcoordY = 1.0 - posY / canvas.height;
                  pointer.deltaX = correctDeltaX(pointer.texcoordX - pointer.prevTexcoordX);
                  pointer.deltaY = correctDeltaY(pointer.texcoordY - pointer.prevTexcoordY);
                  pointer.moved = Math.abs(pointer.deltaX) > 0 || Math.abs(pointer.deltaY) > 0;
                  pointer.color = color;
                }

                function updatePointerUpData(pointer) {
                  pointer.down = false;
                }

                function correctDeltaX(delta) {
                  let aspectRatio = canvas.width / canvas.height;
                  if (aspectRatio < 1) delta *= aspectRatio;
                  return delta;
                }

                function correctDeltaY(delta) {
                  let aspectRatio = canvas.width / canvas.height;
                  if (aspectRatio > 1) delta /= aspectRatio;
                  return delta;
                }

                function hexToRGB(hex) {
                  let val = hex.replace('#', '');
                  if (val.length === 3) val = val[0] + val[0] + val[1] + val[1] + val[2] + val[2];
                  const r = parseInt(val.slice(0, 2), 16) / 255;
                  const g = parseInt(val.slice(2, 4), 16) / 255;
                  const b = parseInt(val.slice(4, 6), 16) / 255;
                  return { r: r * 0.15, g: g * 0.15, b: b * 0.15 };
                }

                function generateColor() {
                  if (!config.RAINBOW_MODE) {
                    return hexToRGB(config.COLOR);
                  }
                  let c = HSVtoRGB(Math.random(), 1.0, 1.0);
                  c.r *= 0.15;
                  c.g *= 0.15;
                  c.b *= 0.15;
                  return c;
                }

                function HSVtoRGB(h, s, v) {
                  let r, g, b, i, f, p, q, t;
                  i = Math.floor(h * 6);
                  f = h * 6 - i;
                  p = v * (1 - s);
                  q = v * (1 - f * s);
                  t = v * (1 - (1 - f) * s);
                  switch (i % 6) {
                    case 0:
                      r = v;
                      g = t;
                      b = p;
                      break;
                    case 1:
                      r = q;
                      g = v;
                      b = p;
                      break;
                    case 2:
                      r = p;
                      g = v;
                      b = t;
                      break;
                    case 3:
                      r = p;
                      g = q;
                      b = v;
                      break;
                    case 4:
                      r = t;
                      g = p;
                      b = v;
                      break;
                    case 5:
                      r = v;
                      g = p;
                      b = q;
                      break;
                    default:
                      break;
                  }
                  return { r, g, b };
                }

                function wrap(value, min, max) {
                  const range = max - min;
                  if (range === 0) return min;
                  return ((value - min) % range) + min;
                }

                function getResolution(resolution) {
                  let aspectRatio = gl.drawingBufferWidth / gl.drawingBufferHeight;
                  if (aspectRatio < 1) aspectRatio = 1.0 / aspectRatio;
                  const min = Math.round(resolution);
                  const max = Math.round(resolution * aspectRatio);
                  if (gl.drawingBufferWidth > gl.drawingBufferHeight) return { width: max, height: min };
                  else return { width: min, height: max };
                }

                function scaleByPixelRatio(input) {
                  const pixelRatio = win.devicePixelRatio || 1;
                  return Math.floor(input * pixelRatio);
                }

                function hashCode(s) {
                  if (s.length === 0) return 0;
                  let hash = 0;
                  for (let i = 0; i < s.length; i++) {
                    hash = (hash << 5) - hash + s.charCodeAt(i);
                    hash |= 0;
                  }
                  return hash;
                }

                function handleMouseDown(e) {
                  let pointer = pointers[0];
                  let posX = scaleByPixelRatio(e.clientX);
                  let posY = scaleByPixelRatio(e.clientY);
                  updatePointerDownData(pointer, -1, posX, posY);
                  clickSplat(pointer);
                }

                let firstMouseMoveHandled = false;
                function handleMouseMove(e) {
                  let pointer = pointers[0];
                  let posX = scaleByPixelRatio(e.clientX);
                  let posY = scaleByPixelRatio(e.clientY);
                  if (!firstMouseMoveHandled) {
                    let color = generateColor();
                    updatePointerMoveData(pointer, posX, posY, color);
                    firstMouseMoveHandled = true;
                  } else {
                    updatePointerMoveData(pointer, posX, posY, pointer.color);
                  }
                }

                function handleTouchStart(e) {
                  const touches = e.targetTouches;
                  let pointer = pointers[0];
                  for (let i = 0; i < touches.length; i++) {
                    let posX = scaleByPixelRatio(touches[i].clientX);
                    let posY = scaleByPixelRatio(touches[i].clientY);
                    updatePointerDownData(pointer, touches[i].identifier, posX, posY);
                  }
                }

                function handleTouchMove(e) {
                  const touches = e.targetTouches;
                  let pointer = pointers[0];
                  for (let i = 0; i < touches.length; i++) {
                    let posX = scaleByPixelRatio(touches[i].clientX);
                    let posY = scaleByPixelRatio(touches[i].clientY);
                    updatePointerMoveData(pointer, posX, posY, pointer.color);
                  }
                }

                function handleTouchEnd(e) {
                  const touches = e.changedTouches;
                  let pointer = pointers[0];
                  for (let i = 0; i < touches.length; i++) {
                    updatePointerUpData(pointer);
                  }
                }

                doc.addEventListener('mousedown', handleMouseDown, { passive: true });
                doc.addEventListener('mousemove', handleMouseMove, { passive: true });
                doc.addEventListener('touchstart', handleTouchStart, { passive: true });
                doc.addEventListener('touchmove', handleTouchMove, { passive: true });
                doc.addEventListener('touchend', handleTouchEnd, { passive: true });

                updateFrame();

                return {
                  destroy() {
                    isActive = false;
                    if (auroraInstance) {
                      auroraInstance.destroy();
                    }
                    if (animationFrameId) {
                      win.cancelAnimationFrame(animationFrameId);
                      animationFrameId = null;
                    }
                    doc.removeEventListener('mousedown', handleMouseDown);
                    doc.removeEventListener('mousemove', handleMouseMove);
                    doc.removeEventListener('touchstart', handleTouchStart);
                    doc.removeEventListener('touchmove', handleTouchMove);
                    doc.removeEventListener('touchend', handleTouchEnd);
                    container.remove();
                  }
                };
              };

              const win = window.parent;
              const isIframeActive = (winObj) => {
                try {
                  if (!winObj) return false;
                  if (winObj === winObj.parent) return true;
                  return !!(winObj.frameElement && winObj.parent.document.body.contains(winObj.frameElement));
                } catch (e) {
                  return false;
                }
              };
              const manageSplashCursor = () => {
                const hasPageG = !!doc.querySelector(".page-g-standard");
                const hasSpinner = !!doc.querySelector('div[data-testid="stSpinner"]');
                const aiProcessing = doc.getElementById("jocket-ai-processing");
                const isAiRunning = hasSpinner || (aiProcessing && aiProcessing.getAttribute("data-running") === "true");
                const isAiChatActive = !!doc.getElementById("jocket-ai-chat-active");
                const shouldBeActive = hasPageG || isAiRunning || isAiChatActive;

                const ownerStale = win.__jocketSplashCursor__ && !isIframeActive(win.__jocketSplashCursor__.owner);

                if (shouldBeActive) {
                  if (ownerStale) {
                    // Iframe was recreated by Streamlit rerun but cursor is
                    // still alive in the parent DOM – just re-adopt it instead
                    // of destroy+recreate which causes a black flash.
                    win.__jocketSplashCursor__.owner = window;
                  } else if (!win.__jocketSplashCursor__) {
                    win.__jocketSplashCursor__ = initSplashCursor(doc, win);
                    win.__jocketSplashCursor__.owner = window;
                  }
                } else {
                  if (win.__jocketSplashCursor__) {
                    try {
                      win.__jocketSplashCursor__.destroy();
                    } catch (e) {
                      console.error("Error destroying splash cursor:", e);
                    }
                    delete win.__jocketSplashCursor__;
                  }
                }
              };

              const initDotField = (doc, win) => {
                let container = doc.getElementById("jocket-dot-field-container");
                let canvas = container && container.querySelector("#jocket-dot-field-canvas");
                
                if (!container) {
                  container = doc.createElement("div");
                  container.id = "jocket-dot-field-container";
                  container.style.cssText = "position: fixed !important; inset: 0 !important; z-index: 0 !important; width: 100vw !important; height: 100vh !important; pointer-events: none !important; overflow: hidden !important; background: transparent !important;";
                  
                  canvas = doc.createElement("canvas");
                  canvas.id = "jocket-dot-field-canvas";
                  canvas.style.cssText = "position: absolute !important; inset: 0 !important; width: 100% !important; height: 100% !important; pointer-events: none !important; display: block !important; opacity: 0 !important; transition: opacity 0.8s ease-in-out !important;";
                  
                  container.appendChild(canvas);
                  doc.body.prepend(container);
                  
                  setTimeout(() => {
                    if (canvas) canvas.style.opacity = "0.35";
                  }, 50);
                }
                
                let isActive = true;
                let animationFrameId = null;
                
                const dotRadius = 1.5;
                const dotSpacing = 14;
                const cursorRadius = 500;
                const cursorForce = 0.1;
                const bulgeOnly = true;
                const bulgeStrength = 67;
                const gradientFrom = "#4a4a4a";
                const gradientTo = "#272727";
                
                const ctx = canvas.getContext("2d", { alpha: true });
                const dpr = Math.min(win.devicePixelRatio || 1, 2);
                
                let dots = [];
                const mouse = {
                  x: -9999,
                  y: -9999,
                  prevX: -9999,
                  prevY: -9999,
                  speed: 0
                };
                
                let dimensions = { w: 0, h: 0, offsetX: 0, offsetY: 0 };
                let speedFactor = 0;
                let cursorOpacity = 0;
                
                let resizeTimer = null;
                function handleResize() {
                  clearTimeout(resizeTimer);
                  resizeTimer = setTimeout(resizeCanvas, 100);
                }
                
                function resizeCanvas() {
                  if (!canvas || !isActive) return;
                  const rect = canvas.parentElement.getBoundingClientRect();
                  const w = rect.width;
                  const h = rect.height;
                  
                  canvas.width = w * dpr;
                  canvas.height = h * dpr;
                  canvas.style.width = `${w}px`;
                  canvas.style.height = `${h}px`;
                  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
                  
                  dimensions = {
                    w,
                    h,
                    offsetX: rect.left + win.scrollX,
                    offsetY: rect.top + win.scrollY
                  };
                  
                  initGrid(w, h);
                }
                
                function initGrid(width, height) {
                  const spacing = dotRadius + dotSpacing;
                  const cols = Math.floor(width / spacing);
                  const rows = Math.floor(height / spacing);
                  const offsetX = (width % spacing) / 2;
                  const offsetY = (height % spacing) / 2;
                  
                  dots = new Array(rows * cols);
                  let index = 0;
                  for (let r = 0; r < rows; r++) {
                    for (let c = 0; c < cols; c++) {
                      const x = offsetX + c * spacing + spacing / 2;
                      const y = offsetY + r * spacing + spacing / 2;
                      dots[index++] = {
                        ax: x, ay: y,
                        sx: x, sy: y,
                        vx: 0, vy: 0,
                        x: x, y: y
                      };
                    }
                  }
                }
                
                function handleMouseMove(e) {
                  mouse.x = e.clientX - dimensions.offsetX;
                  mouse.y = e.clientY - dimensions.offsetY;
                }
                
                function handleMouseLeave() {
                  mouse.x = -9999;
                  mouse.y = -9999;
                }
                
                function handleTouchMove(e) {
                  if (e.touches && e.touches[0]) {
                    mouse.x = e.touches[0].clientX - dimensions.offsetX;
                    mouse.y = e.touches[0].clientY - dimensions.offsetY;
                  }
                }
                
                function updateSpeed() {
                  const dx = mouse.prevX - mouse.x;
                  const dy = mouse.prevY - mouse.y;
                  const dist = Math.sqrt(dx * dx + dy * dy);
                  mouse.speed += (dist - mouse.speed) * 0.5;
                  if (mouse.speed < 0.001) mouse.speed = 0;
                  mouse.prevX = mouse.x;
                  mouse.prevY = mouse.y;
                }
                
                const speedInterval = setInterval(updateSpeed, 20);
                
                function animate() {
                  if (!isActive) return;
                  
                  const dotCount = dots.length;
                  const normSpeed = Math.min(mouse.speed / 5, 1);
                  speedFactor += (normSpeed - speedFactor) * 0.06;
                  if (speedFactor < 0.001) speedFactor = 0;
                  
                  cursorOpacity += (speedFactor - cursorOpacity) * 0.08;
                  
                  ctx.clearRect(0, 0, dimensions.w, dimensions.h);
                  
                  const gradient = ctx.createLinearGradient(0, 0, dimensions.w, dimensions.h);
                  gradient.addColorStop(0, gradientFrom);
                  gradient.addColorStop(1, gradientTo);
                  ctx.fillStyle = gradient;
                  
                  const maxDist = cursorRadius;
                  const maxDistSq = maxDist * maxDist;
                  const radiusHalf = dotRadius / 2;
                  const twoPi = Math.PI * 2;
                  
                  ctx.beginPath();
                  for (let i = 0; i < dotCount; i++) {
                    const dot = dots[i];
                    const dx = mouse.x - dot.ax;
                    const dy = mouse.y - dot.ay;
                    const distSq = dx * dx + dy * dy;
                    
                    if (distSq < maxDistSq && speedFactor > 0.01) {
                      const dist = Math.sqrt(distSq);
                      if (bulgeOnly) {
                        const force = 1 - dist / maxDist;
                        const shift = force * force * bulgeStrength * speedFactor;
                        const angle = Math.atan2(dy, dx);
                        dot.sx += (dot.ax - Math.cos(angle) * shift - dot.sx) * 0.15;
                        dot.sy += (dot.ay - Math.sin(angle) * shift - dot.sy) * 0.15;
                      } else {
                        const angle = Math.atan2(dy, dx);
                        const force = (500 / dist) * (mouse.speed * cursorForce);
                        dot.vx += Math.cos(angle) * -force;
                        dot.vy += Math.sin(angle) * -force;
                      }
                    } else if (bulgeOnly) {
                      dot.sx += (dot.ax - dot.sx) * 0.1;
                      dot.sy += (dot.ay - dot.sy) * 0.1;
                    }
                    
                    if (!bulgeOnly) {
                      dot.vx *= 0.9;
                      dot.vy *= 0.9;
                      dot.x = dot.ax + dot.vx;
                      dot.y = dot.ay + dot.vy;
                      dot.sx += (dot.x - dot.sx) * 0.1;
                      dot.sy += (dot.y - dot.sy) * 0.1;
                    }
                    
                    let finalX = dot.sx;
                    let finalY = dot.sy;
                    
                    ctx.moveTo(finalX + radiusHalf, finalY);
                    ctx.arc(finalX, finalY, radiusHalf, 0, twoPi);
                  }
                  ctx.fill();
                  
                  animationFrameId = requestAnimationFrame(animate);
                }
                
                resizeCanvas();
                win.addEventListener("resize", handleResize);
                doc.addEventListener("mousemove", handleMouseMove, { passive: true });
                doc.addEventListener("mouseleave", handleMouseLeave, { passive: true });
                doc.addEventListener("touchmove", handleTouchMove, { passive: true });
                
                animationFrameId = requestAnimationFrame(animate);
                
                return {
                  destroy() {
                    isActive = false;
                    if (animationFrameId) {
                      cancelAnimationFrame(animationFrameId);
                      animationFrameId = null;
                    }
                    clearInterval(speedInterval);
                    clearTimeout(resizeTimer);
                    win.removeEventListener("resize", handleResize);
                    doc.removeEventListener("mousemove", handleMouseMove);
                    doc.removeEventListener("mouseleave", handleMouseLeave);
                    doc.removeEventListener("touchmove", handleTouchMove);
                    
                    if (canvas) {
                      canvas.style.opacity = "0";
                    }
                    setTimeout(() => {
                      if (container) container.remove();
                    }, 800);
                  }
                };
              };

              const manageDotField = () => {
                const currentPageEl = doc.getElementById("jocket-current-page");
                const currentPage = currentPageEl ? currentPageEl.getAttribute("data-page") : "";
                const hasLanding = !!doc.querySelector(".st-key-jocket_page_g_landing");
                const hasLoading = !!doc.querySelector(".jocket-loading-marker");
                
                const shouldBeActive = currentPage && currentPage !== "AI洞察" && !hasLanding && !hasLoading;
                const ownerStale = win.__jocketDotField__ && !isIframeActive(win.__jocketDotField__.owner);
                
                if (shouldBeActive) {
                  if (ownerStale) {
                    win.__jocketDotField__.owner = window;
                  } else if (!win.__jocketDotField__) {
                    win.__jocketDotField__ = initDotField(doc, win);
                    win.__jocketDotField__.owner = window;
                  }
                } else {
                  if (win.__jocketDotField__) {
                    try {
                      win.__jocketDotField__.destroy();
                    } catch (e) {
                      console.error("Error destroying dot field:", e);
                    }
                    delete win.__jocketDotField__;
                  }
                }
              };

              const decorateAsPillNav = (wrapSelector, buttonsOrSelector, currentActiveText) => {
                const wraps = doc.querySelectorAll(wrapSelector);
                wraps.forEach((wrap) => {
                  wrap.setAttribute("data-jocket-nav-style", "pill-nav");
                });

                const buttons = typeof buttonsOrSelector === "string"
                  ? [...doc.querySelectorAll(buttonsOrSelector)]
                  : buttonsOrSelector;

                buttons.forEach((button) => {
                  const btn = button.matches("button") ? button : button.closest("button") || button.querySelector("button");
                  if (!btn) return;
                  
                  const text =
                    btn.getAttribute("data-jocket-nav-label") ||
                    (btn.innerText || btn.textContent || "").trim();
                  const btnTextArray = text.split('\\n').map(t => t.trim());
                  const selected =
                    btnTextArray.includes(currentActiveText) ||
                    btn.getAttribute("kind") === "segmented_controlActive" ||
                    btn.getAttribute("data-testid") === "stBaseButton-segmented_controlActive" ||
                    btn.getAttribute("aria-checked") === "true" ||
                    btn.getAttribute("aria-selected") === "true" ||
                    btn.getAttribute("aria-pressed") === "true" ||
                    btn.getAttribute("data-selected") === "true" ||
                    !!btn.querySelector("input:checked");

                  const targets = new Set([
                    btn,
                    btn.closest('[data-testid="stSegmentedControlOption"]'),
                    btn.closest('[role="radio"]'),
                    btn.closest('[role="button"]'),
                  ].filter(Boolean));
                  
                  targets.forEach((target) => {
                    target.setAttribute("data-jocket-nav-label", text);
                    target.dataset.jocketNavActive = selected ? "true" : "false";
                    target.classList.toggle("jocket-nav-active", selected);
                  });

                  btn.setAttribute("data-jocket-nav-label", text);
                  btn.dataset.jocketNavActive = selected ? "true" : "false";

                  // Reset background and borders
                  if (selected) {
                    btn.style.setProperty("background", "#ffffff", "important");
                    btn.style.setProperty("background-color", "#ffffff", "important");
                    btn.style.setProperty("color", "#09090b", "important");
                    btn.style.setProperty("-webkit-text-fill-color", "#09090b", "important");
                    btn.style.setProperty("border", "none", "important");
                    btn.style.setProperty("box-shadow", "0 6px 18px rgba(6, 6, 12, 0.16)", "important");
                  } else {
                    btn.style.setProperty("background", "transparent", "important");
                    btn.style.setProperty("background-color", "transparent", "important");
                    btn.style.setProperty("color", "rgba(232, 229, 236, 0.52)", "important");
                    btn.style.setProperty("-webkit-text-fill-color", "rgba(232, 229, 236, 0.52)", "important");
                    btn.style.setProperty("border", "none", "important");
                    btn.style.setProperty("box-shadow", "none", "important");
                  }
                  btn.style.removeProperty("filter");
                  btn.style.removeProperty("transform");
                  btn.style.removeProperty("transition");

                  let circle = btn.querySelector(":scope > .jocket-pill-hover-circle");
                  let label = btn.querySelector(".jocket-pill-label");
                  let hoverLabel = btn.querySelector(".jocket-pill-label-hover");
                  
                  if (!circle || !label || !hoverLabel) {
                    const paragraph = btn.querySelector('[data-testid="stMarkdownContainer"] p') || btn.querySelector("p") || btn;
                    let labelText = text;
                    if (paragraph !== btn) {
                      paragraph.textContent = "";
                    } else {
                      btn.textContent = "";
                    }

                    circle = doc.createElement("span");
                    circle.className = "jocket-pill-hover-circle";
                    circle.setAttribute("aria-hidden", "true");

                    const stack = doc.createElement("span");
                    stack.className = "jocket-pill-label-stack";
                    
                    label = doc.createElement("span");
                    label.className = "jocket-pill-label";
                    label.textContent = labelText;
                    
                    hoverLabel = doc.createElement("span");
                    hoverLabel.className = "jocket-pill-label-hover";
                    hoverLabel.textContent = labelText;
                    hoverLabel.setAttribute("aria-hidden", "true");
                    
                    stack.append(label, hoverLabel);
                    
                    if (paragraph !== btn) {
                      paragraph.append(stack);
                    } else {
                      btn.append(stack);
                    }
                    btn.insertBefore(circle, btn.firstChild);
                    btn.dataset.jocketPillDecorated = "true";
                  }

                  if (!btn.dataset.jocketPillHoverBound) {
                    btn.dataset.jocketPillHoverBound = "true";
                    const setPillHover = (active) => {
                      btn.dataset.jocketPillHover = active ? "true" : "false";
                    };
                    btn.addEventListener("pointerenter", () => setPillHover(true));
                    btn.addEventListener("pointerleave", () => setPillHover(false));
                    btn.addEventListener("focus", () => setPillHover(true));
                    btn.addEventListener("blur", () => setPillHover(false));
                  }

                  const rect = btn.getBoundingClientRect();
                  const w = rect.width;
                  const h = rect.height;
                  if (w > 0 && h > 0 && circle) {
                    const radius = ((w * w) / 4 + h * h) / (2 * h);
                    const diameter = Math.ceil(2 * radius) + 2;
                    const delta = Math.ceil(radius - Math.sqrt(Math.max(0, radius * radius - (w * w) / 4))) + 1;
                    circle.style.width = `${diameter}px`;
                    circle.style.height = `${diameter}px`;
                    circle.style.bottom = `-${delta}px`;
                    circle.style.transformOrigin = `50% ${diameter - delta}px`;
                  }
                });
              };

              const enhanceNav = () => {
                const navWrap = doc.querySelector(".st-key-analysis_mode_top");
                if (!navWrap) return;
                navWrap.classList.add("container-t");
                navWrap.setAttribute("data-jocket-container", "container t");
                navWrap.setAttribute("data-jocket-nav-style", "pill-nav");
                const navScope = navWrap;
                const navLabels = ["AI洞察", "个股行情", "市场情绪", "投研分析", "量化对冲"];
                const getNavLabel = (item) => {
                  const saved = item.getAttribute("data-jocket-nav-label");
                  if (saved && navLabels.includes(saved)) return saved;
                  const raw = (item.innerText || item.textContent || "").replace(/\\s+/g, "").trim();
                  return navLabels.find((label) => raw === label || raw === `${label}${label}`) || "";
                };
                const rawItems = [
                  ...navScope.querySelectorAll('[data-testid="stSegmentedControlOption"], button, label, [role="radio"], [role="button"]')
                ];
                const seen = new Set();
                const navButtons = rawItems.filter((item) => {
                  const text = getNavLabel(item);
                  if (!navLabels.includes(text) || seen.has(text)) return false;
                  item.setAttribute("data-jocket-nav-label", text);
                  seen.add(text);
                  return true;
                });
                if (navButtons.length < 5) return;
                const nav = navButtons[0].parentElement;
                if (!nav) return;
                nav.dataset.jocketNavEnhanced = "true";

                const marker = doc.getElementById("jocket-current-page");
                const currentPage = marker ? marker.getAttribute("data-page") : "";
                navButtons.forEach((item) => {
                  const text = getNavLabel(item);
                  const selected =
                    currentPage === text ||
                    item.getAttribute("kind") === "segmented_controlActive" ||
                    item.getAttribute("data-testid") === "stBaseButton-segmented_controlActive" ||
                    item.getAttribute("aria-checked") === "true" ||
                    item.getAttribute("aria-selected") === "true" ||
                    item.getAttribute("aria-pressed") === "true" ||
                    item.getAttribute("data-selected") === "true" ||
                    !!item.querySelector("input:checked");
                  const targets = new Set([
                    item,
                    item.closest('[data-testid="stSegmentedControlOption"]'),
                    item.closest("button"),
                    item.closest("label"),
                    item.closest('[role="radio"]'),
                    item.closest('[role="button"]'),
                  ].filter(Boolean));
                  targets.forEach((target) => {
                    target.setAttribute("data-jocket-nav-label", text);
                    target.dataset.jocketNavActive = selected ? "true" : "false";
                    target.classList.toggle("jocket-nav-active", selected);
                  });

                  const button = item.matches("button") ? item : item.closest("button") || item.querySelector("button");
                  if (!button) return;
                  button.setAttribute("data-jocket-nav-label", text);

                  let circle = button.querySelector(":scope > .jocket-pill-hover-circle");
                  let label = button.querySelector(".jocket-pill-label");
                  let hoverLabel = button.querySelector(".jocket-pill-label-hover");
                  if (!circle || !label || !hoverLabel) {
                    const paragraph = button.querySelector('[data-testid="stMarkdownContainer"] p') || button.querySelector("p");
                    if (!paragraph) return;
                    paragraph.textContent = "";

                    circle = doc.createElement("span");
                    circle.className = "jocket-pill-hover-circle";
                    circle.setAttribute("aria-hidden", "true");

                    const stack = doc.createElement("span");
                    stack.className = "jocket-pill-label-stack";
                    label = doc.createElement("span");
                    label.className = "jocket-pill-label";
                    label.textContent = text;
                    hoverLabel = doc.createElement("span");
                    hoverLabel.className = "jocket-pill-label-hover";
                    hoverLabel.textContent = text;
                    hoverLabel.setAttribute("aria-hidden", "true");
                    stack.append(label, hoverLabel);
                    paragraph.append(stack);
                    button.insertBefore(circle, button.firstChild);
                    button.dataset.jocketPillDecorated = "true";
                  }

                  if (!button.dataset.jocketPillHoverBound) {
                    button.dataset.jocketPillHoverBound = "true";
                    const setPillHover = (active) => {
                      button.dataset.jocketPillHover = active ? "true" : "false";
                    };
                    button.addEventListener("pointerenter", () => setPillHover(true));
                    button.addEventListener("pointerleave", () => setPillHover(false));
                    button.addEventListener("focus", () => setPillHover(true));
                    button.addEventListener("blur", () => setPillHover(false));
                  }

                  const rect = button.getBoundingClientRect();
                  const w = rect.width;
                  const h = rect.height;
                  if (w > 0 && h > 0 && circle) {
                    const radius = ((w * w) / 4 + h * h) / (2 * h);
                    const diameter = Math.ceil(2 * radius) + 2;
                    const delta = Math.ceil(radius - Math.sqrt(Math.max(0, radius * radius - (w * w) / 4))) + 1;
                    circle.style.width = `${diameter}px`;
                    circle.style.height = `${diameter}px`;
                    circle.style.bottom = `-${delta}px`;
                    circle.style.transformOrigin = `50% ${diameter - delta}px`;
                  }
                });

                if (!nav.dataset.jocketPillNavEntered) {
                  nav.dataset.jocketPillNavEntered = "true";
                  nav.classList.add("jocket-pill-nav-enter");
                }
              };
              const enhanceProvider = () => {
                const pMarker = doc.getElementById("jocket-ai-provider");
                const pCurrent = pMarker ? pMarker.getAttribute("data-provider") : "";
                decorateAsPillNav('[class*="st-key-ai_market_provider_label"]', '[class*="st-key-ai_market_provider_label"] button', pCurrent);
                
                const wMarker = doc.getElementById("jocket-sentiment-window");
                const wCurrent = wMarker ? wMarker.getAttribute("data-window") : "";
                const windowLabels = ["14日", "30日", "60日"];
                let wButtons = [...doc.querySelectorAll(".st-key-sentiment_window_segment button")];
                if (wButtons.length < 3) {
                  const seenWindowLabels = new Set();
                  wButtons = [...doc.querySelectorAll("button")].filter((button) => {
                    const text = (button.innerText || button.textContent || "").trim();
                    if (!windowLabels.includes(text) || seenWindowLabels.has(text)) return false;
                    seenWindowLabels.add(text);
                    return true;
                  });
                }
                const wWrap = doc.querySelector(".st-key-sentiment_window_segment");
                const rootsFor = (ancestor) => {
                  if (!ancestor) return [];
                  return wButtons.map((button) => {
                    let node = button;
                    while (node.parentElement && node.parentElement !== ancestor) {
                      node = node.parentElement;
                    }
                    return node;
                  });
                };
                let wTrack = null;
                let probe = wButtons.length ? wButtons[0].parentElement : null;
                while (probe) {
                  if (wButtons.every((button) => probe.contains(button))) {
                    const roots = [...new Set(rootsFor(probe))];
                    if (roots.length === 3) {
                      wTrack = probe;
                      break;
                    }
                  }
                  if (wWrap && probe === wWrap) break;
                  probe = probe.parentElement;
                }
                if (!wTrack) {
                  wTrack = wButtons.length ? wButtons[0].parentElement : null;
                  while (wTrack && !wButtons.every((button) => wTrack.contains(button))) {
                    wTrack = wTrack.parentElement;
                  }
                }
                const wShell = wWrap || wTrack;
                if (wShell) {
                  wShell.style.setProperty("display", "block", "important");
                  wShell.style.setProperty("max-width", "100%", "important");
                  wShell.style.setProperty("margin", "0 auto 14px", "important");
                  wShell.style.setProperty("width", "100%", "important");
                  wShell.style.setProperty("height", "62px", "important");
                  wShell.style.setProperty("min-height", "62px", "important");
                  wShell.style.setProperty("padding", "7px", "important");
                  wShell.style.setProperty("box-sizing", "border-box", "important");
                  wShell.style.setProperty("border-radius", "999px", "important");
                  wShell.style.setProperty("overflow", "visible", "important");
                }
                let ancestor = wTrack;
                let guard = 0;
                while (ancestor && ancestor !== wShell && guard < 8) {
                  ancestor.style.setProperty("width", "100%", "important");
                  ancestor.style.setProperty("max-width", "100%", "important");
                  ancestor.style.setProperty("min-width", "0", "important");
                  ancestor.style.setProperty("height", "100%", "important");
                  ancestor.style.setProperty("min-height", "0", "important");
                  ancestor.style.setProperty("margin", "0", "important");
                  ancestor.style.setProperty("padding", "0", "important");
                  ancestor.style.setProperty("overflow", "visible", "important");
                  ancestor = ancestor.parentElement;
                  guard += 1;
                }
                if (wTrack) {
                  const wItems = [...new Set(rootsFor(wTrack))];
                  wTrack.style.setProperty("display", "grid", "important");
                  wTrack.style.setProperty("grid-template-columns", "repeat(3, minmax(0, 1fr))", "important");
                  wTrack.style.setProperty("align-items", "stretch", "important");
                  wTrack.style.setProperty("align-content", "stretch", "important");
                  wTrack.style.setProperty("gap", "6px", "important");
                  wTrack.style.setProperty("width", "100%", "important");
                  wTrack.style.setProperty("height", "100%", "important");
                  wTrack.style.setProperty("min-height", "0", "important");
                  wTrack.style.setProperty("margin", "0", "important");
                  wTrack.style.setProperty("padding", "0", "important");
                  wTrack.style.setProperty("overflow", "visible", "important");
                  wItems.forEach((child) => {
                    child.style.setProperty("display", "flex", "important");
                    child.style.setProperty("align-items", "stretch", "important");
                    child.style.setProperty("justify-content", "stretch", "important");
                    child.style.setProperty("width", "100%", "important");
                    child.style.setProperty("min-width", "0", "important");
                    child.style.setProperty("height", "100%", "important");
                    child.style.setProperty("min-height", "0", "important");
                    child.style.setProperty("align-self", "stretch", "important");
                    child.style.setProperty("margin", "0", "important");
                    child.style.setProperty("padding", "0", "important");
                  });
                }

                // Decorate sentiment buttons with pill nav style
                if (wButtons.length > 0) {
                  const activeText = `${wCurrent}日`; // Convert e.g., 60 to "60日"
                  decorateAsPillNav(".st-key-sentiment_window_segment", wButtons, activeText);
                }
              };

              const enhanceDockHosts = () => {
                doc.querySelectorAll(".jocket-dock-host").forEach((host) => {
                  const marker = host.querySelector(".jocket-bottom-dock");
                  if (!marker) {
                    host.classList.remove("jocket-dock-host");
                    host.classList.remove("container-b");
                    host.classList.remove("style-bottom");
                    host.removeAttribute("data-jocket-container");
                    host.removeAttribute("data-jocket-dock-style");
                  }
                });
                doc.querySelectorAll(".jocket-bottom-dock").forEach((marker) => {
                  const host = marker.closest('[data-testid="stVerticalBlockBorderWrapper"]') || marker.closest('[data-testid="stVerticalBlock"]');
                  if (host) {
                    const template =
                      host.querySelector('[class*="st-key-hedge_tickers"], [class*="st-key-hedge_start_date"], [class*="st-key-hedge_end_date"]')
                        ? "multi-field"
                        : host.querySelector('[class*="st-key-ta_input_ticker"], [class*="st-key-ta_input_date"]')
                          ? "dual-field"
                          : "single-field";
                    host.classList.add("jocket-dock-host");
                    host.classList.add("container-b");
                    host.classList.add("style-bottom");
                    host.setAttribute("data-jocket-container", "container b");
                    host.setAttribute("data-jocket-dock-style", "style bottom");
                    host.setAttribute("data-jocket-dock-template", template);
                    if (template === "multi-field") {
                      host.style.setProperty("width", "var(--j-page-g-dock)", "important");
                    } else {
                      host.style.removeProperty("width");
                    }
                  }
                });
              };

              const enhanceHedgeMode = () => {
                const hMarker = doc.getElementById("jocket-hedge-mode");
                const hCurrent = hMarker ? hMarker.getAttribute("data-mode") : "";
                decorateAsPillNav('[class*="st-key-hedge_mode_widget"]', '[class*="st-key-hedge_mode_widget"] button', hCurrent);
              };

              // Fix skill buttons layout safely
              const fixSkillsLayout = () => {
                const containers = doc.querySelectorAll('.ai-skill-buttons-container');
                containers.forEach(container => {
                  const verticalBlock = container.closest('[data-testid="stVerticalBlock"]');
                  if (verticalBlock) {
                    verticalBlock.style.display = 'flex';
                    verticalBlock.style.flexDirection = 'row';
                    verticalBlock.style.flexWrap = 'wrap';
                    verticalBlock.style.gap = '12px 16px';
                    verticalBlock.style.justifyContent = 'flex-start';
                    verticalBlock.style.alignItems = 'center';
                  }
                  // Make element containers inline
                  if (verticalBlock) {
                    const els = verticalBlock.querySelectorAll('[data-testid="element-container"]');
                    els.forEach(el => {
                      el.style.width = 'auto';
                      el.style.flex = '0 0 auto';
                      el.style.margin = '0';
                    });
                  }
                });
              };

              // Fix history report buttons layout inside popover
              const fixHistoryLayout = () => {
                // Target history items inside popover body
                const popoverBody = doc.querySelector('[data-testid="stPopoverBody"]');
                if (!popoverBody) return;

                // CRITICAL: Also strip background from the outer BaseWeb portal wrapper
                // (the div[data-baseweb="popover"] that wraps stPopoverBody carries BaseWeb's dark theme bg)
                const outerWrapper = popoverBody.closest('[data-baseweb="popover"]') || popoverBody.parentElement;
                if (outerWrapper && outerWrapper !== popoverBody) {
                  outerWrapper.style.setProperty('background', 'transparent', 'important');
                  outerWrapper.style.setProperty('background-color', 'transparent', 'important');
                  outerWrapper.style.setProperty('border', 'none', 'important');
                  outerWrapper.style.setProperty('box-shadow', 'none', 'important');
                  outerWrapper.style.setProperty('padding', '0', 'important');
                }

                // Make popover body container clean frosted glass directly on the page background (matching top nav)
                popoverBody.style.setProperty('background', 'rgba(20, 23, 28, 0.76)', 'important');
                popoverBody.style.setProperty('border', '1px solid rgba(255, 255, 255, 0.18)', 'important');
                popoverBody.style.setProperty('backdrop-filter', 'blur(30px) saturate(155%)', 'important');
                popoverBody.style.setProperty('-webkit-backdrop-filter', 'blur(30px) saturate(155%)', 'important');
                popoverBody.style.setProperty('border-radius', '24px', 'important');
                popoverBody.style.setProperty('box-shadow', '0 24px 70px rgba(0, 0, 0, 0.6)', 'important');

                // Strip backgrounds from all intermediate Streamlit wrapper divs inside the popover
                popoverBody.querySelectorAll('[data-testid="stVerticalBlockBorderWrapper"], [data-testid="stVerticalBlock"], [data-testid="stColumn"], [data-testid="stHorizontalBlock"], [data-testid="stElementContainer"]').forEach(el => {
                  el.style.setProperty('background', 'transparent', 'important');
                  el.style.setProperty('background-color', 'transparent', 'important');
                  el.style.setProperty('border', 'none', 'important');
                  el.style.setProperty('box-shadow', 'none', 'important');
                });

                // Tighten vertical spacing in popover
                popoverBody.querySelectorAll('[data-testid="stVerticalBlock"]').forEach(vb => {
                  vb.style.setProperty('gap', '4px', 'important');
                });

                // Fix each history row (horizontal block with report btn + delete btn)
                popoverBody.querySelectorAll('[data-testid="stHorizontalBlock"]').forEach(row => {
                  // Only apply this layout fix to history rows (which contain a delete key)
                  const hasHistoryDel = row.querySelector('[class*="st-key-ta_del_select"]');
                  if (!hasHistoryDel) return;

                  row.style.setProperty('gap', '6px', 'important');
                  row.style.setProperty('align-items', 'center', 'important');
                  const cols = row.querySelectorAll('[data-testid="stColumn"]');
                  if (cols.length === 2) {
                    // Report button column: fill
                    cols[0].style.setProperty('flex', '1 1 auto', 'important');
                    cols[0].style.setProperty('min-width', '0', 'important');
                    // Delete button column: narrow
                    cols[1].style.setProperty('flex', '0 0 28px', 'important');
                    cols[1].style.setProperty('max-width', '28px', 'important');
                    cols[1].style.setProperty('min-width', '28px', 'important');
                  }
                });

                // Force history select buttons to be capsule shape (pill cards)
                doc.querySelectorAll('[class*="st-key-ta_hist_select_"] button').forEach(btn => {
                  btn.style.setProperty('border-radius', '9999px', 'important');
                  btn.style.setProperty('background', 'rgba(255, 255, 255, 0.08)', 'important');
                  btn.style.setProperty('border', '1px solid rgba(255, 255, 255, 0.14)', 'important');
                  btn.style.setProperty('color', 'rgba(255, 255, 255, 0.85)', 'important');
                  btn.style.setProperty('padding', '10px 20px 10px 14px', 'important');
                  btn.style.setProperty('display', 'flex', 'important');
                  btn.style.setProperty('flex-direction', 'row', 'important');
                  btn.style.setProperty('align-items', 'center', 'important');
                  btn.style.setProperty('height', 'auto', 'important');
                  btn.style.setProperty('min-height', '56px', 'important');
                  btn.style.setProperty('width', '100%', 'important');
                  btn.style.setProperty('box-shadow', 'none', 'important');
                  btn.style.setProperty('transition', 'all 0.2s ease', 'important');

                  // Setup hover listeners
                  if (!btn.dataset.jocketHoverBound) {
                    btn.dataset.jocketHoverBound = "true";
                    btn.addEventListener('mouseenter', () => {
                      btn.style.setProperty('background', 'rgba(255, 255, 255, 0.18)', 'important');
                      btn.style.setProperty('border-color', 'rgba(255, 255, 255, 0.24)', 'important');
                    });
                    btn.addEventListener('mouseleave', () => {
                      btn.style.setProperty('background', 'rgba(255, 255, 255, 0.08)', 'important');
                      btn.style.setProperty('border-color', 'rgba(255, 255, 255, 0.14)', 'important');
                    });
                  }
                });

                // Force delete buttons compact and centered
                doc.querySelectorAll('[class*="st-key-ta_del_"] button').forEach(btn => {
                  btn.style.setProperty('width', '20px', 'important');
                  btn.style.setProperty('min-width', '20px', 'important');
                  btn.style.setProperty('max-width', '20px', 'important');
                  btn.style.setProperty('height', '20px', 'important');
                  btn.style.setProperty('min-height', '20px', 'important');
                  btn.style.setProperty('max-height', '20px', 'important');
                  btn.style.setProperty('padding', '0', 'important');
                  btn.style.setProperty('margin', '0', 'important');
                  btn.style.setProperty('border-radius', '50%', 'important');
                  btn.style.setProperty('border', 'none', 'important');
                  btn.style.setProperty('background', 'rgba(255, 92, 122, 0.8)', 'important');
                  btn.style.setProperty('color', '#fff', 'important');
                  btn.style.setProperty('display', 'inline-flex', 'important');
                  btn.style.setProperty('align-items', 'center', 'important');
                  btn.style.setProperty('justify-content', 'center', 'important');
                  btn.style.setProperty('overflow', 'hidden', 'important');
                  btn.style.setProperty('flex-shrink', '0', 'important');
                  btn.style.setProperty('font-size', '10px', 'important');
                  btn.style.setProperty('line-height', '1', 'important');

                  // Centering inner cross characters perfectly
                  btn.querySelectorAll('*').forEach(child => {
                    child.style.setProperty('margin', '0', 'important');
                    child.style.setProperty('padding', '0', 'important');
                    child.style.setProperty('line-height', '1', 'important');
                    child.style.setProperty('display', 'inline-flex', 'important');
                    child.style.setProperty('align-items', 'center', 'important');
                    child.style.setProperty('justify-content', 'center', 'important');
                    child.style.setProperty('width', '100%', 'important');
                    child.style.setProperty('height', '100%', 'important');
                  });
                });
              };

              // Fix analyst selection popover style to pill nav style
              const fixAnalystLayout = () => {
                const popoverBody = doc.querySelector('[data-testid="stPopoverBody"]');
                if (!popoverBody) return;

                // CRITICAL: Also strip background from the outer BaseWeb portal wrapper
                // (the div[data-baseweb="popover"] that wraps stPopoverBody carries BaseWeb's dark theme bg)
                const outerWrapper = popoverBody.closest('[data-baseweb="popover"]') || popoverBody.parentElement;
                if (outerWrapper && outerWrapper !== popoverBody) {
                  outerWrapper.style.setProperty('background', 'transparent', 'important');
                  outerWrapper.style.setProperty('background-color', 'transparent', 'important');
                  outerWrapper.style.setProperty('border', 'none', 'important');
                  outerWrapper.style.setProperty('box-shadow', 'none', 'important');
                  outerWrapper.style.setProperty('padding', '0', 'important');
                }

                // Make popover body container clean frosted glass directly on the page background (matching top nav)
                popoverBody.style.setProperty('background', 'rgba(20, 23, 28, 0.76)', 'important');
                popoverBody.style.setProperty('border', '1px solid rgba(255, 255, 255, 0.18)', 'important');
                popoverBody.style.setProperty('backdrop-filter', 'blur(30px) saturate(155%)', 'important');
                popoverBody.style.setProperty('-webkit-backdrop-filter', 'blur(30px) saturate(155%)', 'important');
                popoverBody.style.setProperty('border-radius', '24px', 'important');
                popoverBody.style.setProperty('box-shadow', '0 24px 70px rgba(0, 0, 0, 0.6)', 'important');

                // Strip backgrounds from all intermediate Streamlit wrapper divs inside the popover
                popoverBody.querySelectorAll('[data-testid="stVerticalBlockBorderWrapper"], [data-testid="stVerticalBlock"], [data-testid="stColumn"], [data-testid="stHorizontalBlock"], [data-testid="stElementContainer"]').forEach(el => {
                  el.style.setProperty('background', 'transparent', 'important');
                  el.style.setProperty('background-color', 'transparent', 'important');
                  el.style.setProperty('border', 'none', 'important');
                  el.style.setProperty('box-shadow', 'none', 'important');
                });

                // Increase vertical spacing between rows of chips for a less crowded layout
                popoverBody.querySelectorAll('[data-testid="stVerticalBlock"]').forEach(vb => {
                  vb.style.setProperty('gap', '10px', 'important');
                });

                // Target analyst buttons inside popover body
                popoverBody.querySelectorAll('[class*="st-key-ai_skill_"] button').forEach(btn => {
                  const isPrimary = btn.getAttribute('kind') === 'primary' || btn.dataset.testid === 'stBaseButton-primary';

                  btn.style.setProperty('border-radius', '9999px', 'important');
                  btn.style.setProperty('height', '44px', 'important'); // Increased height
                  btn.style.setProperty('min-height', '44px', 'important');
                  btn.style.setProperty('max-height', '44px', 'important');
                  btn.style.setProperty('width', '100%', 'important');
                  btn.style.setProperty('min-width', '0', 'important');
                  btn.style.setProperty('max-width', 'none', 'important');
                  btn.style.setProperty('transition', 'all 0.2s ease', 'important');
                  btn.style.setProperty('font-size', '13px', 'important');
                  btn.style.setProperty('display', 'inline-flex', 'important');
                  btn.style.setProperty('align-items', 'center', 'important');
                  btn.style.setProperty('justify-content', 'center', 'important');
                  btn.style.setProperty('padding', '8px 16px', 'important');
                  btn.style.setProperty('box-shadow', 'none', 'important');

                  if (isPrimary) {
                    // Selected state: White bg, Black text
                    btn.style.setProperty('background', '#ffffff', 'important');
                    btn.style.setProperty('border', '1px solid #ffffff', 'important');
                    btn.style.setProperty('color', '#09090b', 'important');
                  } else {
                    // Unselected state: Frosted glass bg, White text, semi-transparent border
                    btn.style.setProperty('background', 'rgba(255, 255, 255, 0.08)', 'important');
                    btn.style.setProperty('border', '1px solid rgba(255, 255, 255, 0.14)', 'important');
                    btn.style.setProperty('color', 'rgba(255, 255, 255, 0.85)', 'important');

                    // Setup hover listeners
                    if (!btn.dataset.jocketHoverBound) {
                      btn.dataset.jocketHoverBound = "true";
                      btn.addEventListener('mouseenter', () => {
                        btn.style.setProperty('background', 'rgba(255, 255, 255, 0.18)', 'important');
                        btn.style.setProperty('border-color', 'rgba(255, 255, 255, 0.24)', 'important');
                        btn.querySelectorAll('*').forEach(child => {
                          child.style.setProperty('color', '#ffffff', 'important');
                          child.style.setProperty('-webkit-text-fill-color', '#ffffff', 'important');
                        });
                      });
                      btn.addEventListener('mouseleave', () => {
                        btn.style.setProperty('background', 'rgba(255, 255, 255, 0.08)', 'important');
                        btn.style.setProperty('border-color', 'rgba(255, 255, 255, 0.14)', 'important');
                        btn.querySelectorAll('*').forEach(child => {
                          child.style.setProperty('color', 'rgba(255, 255, 255, 0.85)', 'important');
                          child.style.setProperty('-webkit-text-fill-color', 'rgba(255, 255, 255, 0.85)', 'important');
                        });
                      });
                    }
                  }

                  // Force children text styles
                  btn.querySelectorAll('*').forEach(child => {
                    child.style.setProperty('color', isPrimary ? '#09090b' : 'rgba(255, 255, 255, 0.85)', 'important');
                    child.style.setProperty('-webkit-text-fill-color', isPrimary ? '#09090b' : 'rgba(255, 255, 255, 0.85)', 'important');
                    child.style.setProperty('font-weight', isPrimary ? '650' : '500', 'important');
                    child.style.setProperty('margin', '0', 'important');
                    child.style.setProperty('padding', '0', 'important');
                  });
                });
              };

              const enhanceAiInputLoading = () => {
                const marker = doc.getElementById("jocket-current-page");
                const currentPage = marker ? marker.getAttribute("data-page") : "";
                const composerMarker = doc.querySelector(".ai-composer-shell");
                if (composerMarker) {
                  const composerBlock = composerMarker.closest('[data-testid="stVerticalBlock"]');
                  const composerForm = composerBlock ? composerBlock.querySelector('[data-testid="stForm"]') : null;
                  if (composerForm) composerForm.classList.add("jocket-ai-composer-form");
                }
                const inputWrap = doc.querySelector('[class*="st-key-ai_market_prompt"] [data-baseweb="input"]');
                const inputElem = doc.querySelector('[class*="st-key-ai_market_prompt"] input');
                const sendBtn = doc.querySelector('[class*="st-key-ai_market_submit"] button')
                  || doc.querySelector('.jocket-dock-host [data-testid="stFormSubmitButton"] button');
                const aiProcessing = doc.getElementById("jocket-ai-processing");
                
                if (currentPage !== "AI洞察" || !inputWrap) return;

                const hasSpinner = !!doc.querySelector('div[data-testid="stSpinner"]');
                const isAiRunning = hasSpinner || (aiProcessing && aiProcessing.getAttribute("data-running") === "true");
                
                if (isAiRunning) {
                  inputWrap.setAttribute("data-ai-loading", "true");
                  if (sendBtn) sendBtn.setAttribute("data-laicai-running", "true");
                } else if (inputWrap.getAttribute("data-ai-loading") === "true") {
                  inputWrap.removeAttribute("data-ai-loading");
                  if (sendBtn) sendBtn.removeAttribute("data-laicai-running");
                }

                if (sendBtn && !sendBtn.dataset.jocketSubmitBound) {
                  sendBtn.dataset.jocketSubmitBound = "true";
                  sendBtn.addEventListener("click", () => {
                    if (inputElem && inputElem.value.trim()) {
                      inputWrap.setAttribute("data-ai-loading", "true");
                      sendBtn.setAttribute("data-laicai-running", "true");
                    }
                  });
                }

                if (inputElem && !inputElem.dataset.jocketEnterBound) {
                  inputElem.dataset.jocketEnterBound = "true";
                  inputElem.addEventListener("keydown", (e) => {
                    if (e.key === "Enter" && inputElem.value.trim()) {
                      inputWrap.setAttribute("data-ai-loading", "true");
                      if (sendBtn) sendBtn.setAttribute("data-laicai-running", "true");
                    }
                  });
                }
              };

              const enhanceAiPromptRail = () => {
                const inputElem = doc.querySelector('[class*="st-key-ai_market_prompt"] input')
                               || doc.querySelector('[class*="st-key-stock_query"] input')
                               || doc.querySelector('[class*="st-key-ta_input_ticker"] input')
                               || doc.querySelector('[class*="st-key-hedge_tickers"] input')
                               || doc.querySelector('[class*="st-key-sentiment_date"] input')
                               || doc.querySelector('[class*="st-key-ta_input_date"] input')
                               || doc.querySelector('[class*="st-key-hedge_start_date"] input')
                               || doc.querySelector('[class*="st-key-hedge_end_date"] input');
                if (!inputElem) return;
                const inputWrap = inputElem.closest('[data-baseweb="input"]');
                doc.querySelectorAll(".ai-prompt-rail [data-ai-prompt]").forEach((chip) => {
                  if (chip.dataset.jocketPromptBound) return;
                  chip.dataset.jocketPromptBound = "true";
                  const applyPrompt = () => {
                    const prompt = chip.getAttribute("data-ai-prompt") || (chip.innerText || chip.textContent || "").trim();
                    inputElem.focus();
                    const valueSetter = Object.getOwnPropertyDescriptor(window.parent.HTMLInputElement.prototype, "value")?.set;
                    if (valueSetter) {
                      valueSetter.call(inputElem, prompt);
                    } else {
                      inputElem.value = prompt;
                    }
                    inputElem.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: prompt }));
                    inputElem.dispatchEvent(new Event("change", { bubbles: true }));
                    if (inputWrap) inputWrap.setAttribute("data-ai-suggested", "true");
                    chip.dataset.jocketPromptApplied = "true";
                    setTimeout(() => {
                      chip.dataset.jocketPromptApplied = "false";
                      if (inputWrap) inputWrap.removeAttribute("data-ai-suggested");
                    }, 900);
                  };
                  chip.addEventListener("click", applyPrompt);
                  chip.addEventListener("keydown", (event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      applyPrompt();
                    }
                  });
                });
              };

              const enhanceAiPromptHotkeys = () => {
                if (window.parent._jocketAiPromptHotkeysBound) return;
                window.parent._jocketAiPromptHotkeysBound = true;
                doc.addEventListener("keydown", (event) => {
                  const marker = doc.getElementById("jocket-current-page");
                  const currentPage = marker ? marker.getAttribute("data-page") : "";
                  if (currentPage !== "AI洞察") return;
                  const target = event.target;
                  const tagName = (target && target.tagName || "").toLowerCase();
                  const isTyping = tagName === "input" || tagName === "textarea" || (target && target.isContentEditable);
                  const wantsFocus = event.key === "/" && !event.metaKey && !event.ctrlKey && !event.altKey && !isTyping;
                  const wantsCommand = event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey);
                  if (!wantsFocus && !wantsCommand) return;
                  const inputElem = doc.querySelector('[class*="st-key-ai_market_prompt"] input');
                  const inputWrap = doc.querySelector('[class*="st-key-ai_market_prompt"] [data-baseweb="input"]');
                  if (!inputElem) return;
                  event.preventDefault();
                  inputElem.focus();
                  inputElem.select();
                  setTimeout(() => {
                    inputElem.focus();
                    inputElem.select();
                    if (inputElem.value) inputElem.setSelectionRange(0, inputElem.value.length);
                  }, 30);
                  if (inputWrap) {
                    inputWrap.setAttribute("data-ai-hotkey-focus", "true");
                    setTimeout(() => inputWrap.removeAttribute("data-ai-hotkey-focus"), 900);
                  }
                });
              };

              const animateCommandBarHeight = () => {
                const container = doc.querySelector('.jocket-dock-host');
                if (!container) return;
                container.style.removeProperty("height");
                container.style.removeProperty("top");
                container.style.removeProperty("overflow");
                return;

                const block = container.querySelector('[data-testid="stVerticalBlock"]');
                if (!block) return;

                if (!window.parent._jocketObservedBlocks) {
                  window.parent._jocketObservedBlocks = new WeakMap();
                }

                if (!window.parent._jocketObservedBlocks.has(block)) {
                  container.style.setProperty("transition", "height 500ms cubic-bezier(0.16, 1, 0.3, 1), opacity 500ms cubic-bezier(0.16, 1, 0.3, 1)", "important");
                  container.style.setProperty("will-change", "height, opacity", "important");
                  container.style.setProperty("box-sizing", "border-box", "important");
                  container.style.setProperty("overflow", "hidden", "important");

                  const computed = window.parent.getComputedStyle(container);
                  const paddingTop = parseFloat(computed.paddingTop) || 26;
                  const paddingBottom = parseFloat(computed.paddingBottom) || 28;
                  const borderTop = parseFloat(computed.borderTopWidth) || 1;
                  const borderBottom = parseFloat(computed.borderBottomWidth) || 1;
                  const chromeHeight = paddingTop + paddingBottom + borderTop + borderBottom;

                  const lastKnownHeight = window.parent._jocketLastCommandBarHeight;
                  const targetHeight = block.offsetHeight + chromeHeight;

                  if (lastKnownHeight && Math.abs(lastKnownHeight - targetHeight) > 3) {
                    container.style.setProperty("height", `${lastKnownHeight}px`, "important");
                    block.style.setProperty("opacity", "0.4", "important");
                    block.style.setProperty("transform", "translateY(10px)", "important");
                    block.style.setProperty("transition", "opacity 300ms ease, transform 350ms cubic-bezier(0.16, 1, 0.3, 1)", "important");

                    container.offsetHeight; // Force reflow

                    container.style.setProperty("height", `${targetHeight}px`, "important");
                    
                    setTimeout(() => {
                      block.style.setProperty("opacity", "1", "important");
                      block.style.setProperty("transform", "none", "important");
                    }, 50);
                  } else {
                    container.style.setProperty("height", `${targetHeight}px`, "important");
                  }

                  window.parent._jocketLastCommandBarHeight = targetHeight;

                  const resizeObserver = new window.parent.ResizeObserver((entries) => {
                    for (let entry of entries) {
                      const freshComputed = window.parent.getComputedStyle(container);
                      const pTop = parseFloat(freshComputed.paddingTop) || 26;
                      const pBottom = parseFloat(freshComputed.paddingBottom) || 28;
                      const bTop = parseFloat(freshComputed.borderTopWidth) || 1;
                      const bBottom = parseFloat(freshComputed.borderBottomWidth) || 1;
                      const chromeH = pTop + pBottom + bTop + bBottom;

                      const naturalHeight = entry.contentRect.height + chromeH;
                      const currentH = container.offsetHeight;

                      if (Math.abs(naturalHeight - currentH) > 3) {
                        container.style.setProperty("overflow", "hidden", "important");
                        container.style.setProperty("height", `${currentH}px`, "important");
                        container.offsetHeight; // Force reflow
                        container.style.setProperty("height", `${naturalHeight}px`, "important");

                        window.parent._jocketLastCommandBarHeight = naturalHeight;

                        if (container.dataset.jocketTimeoutId) {
                          clearTimeout(parseInt(container.dataset.jocketTimeoutId));
                        }
                        const timeoutId = setTimeout(() => {
                          container.style.setProperty("overflow", "visible", "important");
                          container.style.removeProperty("height");
                        }, 500);
                        container.dataset.jocketTimeoutId = timeoutId.toString();
                      }
                    }
                  });

                  resizeObserver.observe(block);
                  window.parent._jocketObservedBlocks.set(block, resizeObserver);

                  container.addEventListener("transitionend", (e) => {
                    if (e.propertyName === "height") {
                      container.style.setProperty("overflow", "visible", "important");
                      container.style.removeProperty("height");
                    }
                  });
                }
              };

              const enhanceLaicaiButtons = () => {
                const explicitButtons = [
                  ...doc.querySelectorAll('.st-key-run_stock_quote button'),
                  ...doc.querySelectorAll('.st-key-run_market_sentiment button'),
                  ...doc.querySelectorAll('.st-key-run_stock_analysis button'),
                  ...doc.querySelectorAll('.st-key-run_ta_analysis button'),
                  ...doc.querySelectorAll('.st-key-run_hedge_analysis button'),
                  ...doc.querySelectorAll('.st-key-ai_market_submit button'),
                  ...doc.querySelectorAll('.jocket-dock-host [data-testid="stFormSubmitButton"] button')
                ];
                const primaryButtons = [...doc.querySelectorAll(
                  '.stButton > button[kind="primary"], ' +
                  '.stDownloadButton > button[kind="primary"], ' +
                  '[data-testid="stFormSubmitButton"] > button[kind="primary"]'
                )];
                const textLaicaiButtons = [...doc.querySelectorAll('button')].filter(btn => {
                  const text = (btn.innerText || btn.textContent || "").trim();
                  return text.includes("来财来财");
                });
                const buttons = [...new Set([...explicitButtons, ...primaryButtons, ...textLaicaiButtons])];
                const aiProcessing = doc.getElementById("jocket-ai-processing");
                const hasSpinner = !!doc.querySelector('div[data-testid="stSpinner"]');
                const isAiRunning = aiProcessing && aiProcessing.getAttribute("data-running") === "true";
                buttons.forEach(btn => {
                  btn.setAttribute("data-jocket-button-style", "Style L");
                  if (btn.closest(".jocket-dock-host")) {
                    btn.style.setProperty("height", "42px", "important");
                    btn.style.setProperty("min-height", "42px", "important");
                    btn.style.setProperty("max-height", "42px", "important");
                    btn.style.setProperty("padding-top", "0", "important");
                    btn.style.setProperty("padding-bottom", "0", "important");
                    btn.style.setProperty("transform", "none", "important");
                  }
                  const isBtnDisabled = btn.disabled || btn.getAttribute("disabled") !== null;
                  if (hasSpinner || isAiRunning || isBtnDisabled) {
                    btn.setAttribute("data-laicai-running", "true");
                  } else {
                    btn.removeAttribute("data-laicai-running");
                  }
                });
              };

              const enhanceDetailsTransition = () => {
                const details = doc.querySelectorAll('.rating-row');
                details.forEach(detail => {
                  if (detail.dataset.jocketTransitionBound) return;
                  detail.dataset.jocketTransitionBound = "true";
                  
                  const summary = detail.querySelector('summary');
                  const content = detail.querySelector('p');
                  if (!summary || !content) return;
                  
                  summary.addEventListener('click', (e) => {
                    if (detail.classList.contains('collapsing')) {
                      e.preventDefault();
                      return;
                    }
                    
                    if (detail.hasAttribute('open')) {
                      e.preventDefault();
                      detail.classList.add('collapsing');
                      
                      content.style.setProperty('max-height', '0', 'important');
                      content.style.setProperty('opacity', '0', 'important');
                      content.style.setProperty('margin-top', '0', 'important');
                      content.style.setProperty('margin-bottom', '0', 'important');
                      
                      setTimeout(() => {
                        detail.removeAttribute('open');
                        detail.classList.remove('collapsing');
                        content.style.removeProperty('max-height');
                        content.style.removeProperty('opacity');
                        content.style.removeProperty('margin-top');
                        content.style.removeProperty('margin-bottom');
                      }, 300);
                    } else {
                      content.style.removeProperty('max-height');
                      content.style.removeProperty('opacity');
                      content.style.removeProperty('margin-top');
                      content.style.removeProperty('margin-bottom');
                    }
                  });
                });
              };

              const enhanceSplitText = () => {
                const headings = doc.querySelectorAll(".page-empty-state h1");
                headings.forEach((h1) => {
                  const text = (h1.getAttribute("data-jocket-title") || h1.textContent || "").trim();
                  if (!text) return;
                  
                  const isSplit = h1.querySelector(".split-char") !== null;
                  const lastText = h1.getAttribute("data-original-text");
                  
                  if (!isSplit || lastText !== text) {
                    h1.setAttribute("data-original-text", text);
                    h1.setAttribute("data-split-text-animated", "true");
                    h1.innerHTML = "";
                    
                    const chars = [...text];
                    chars.forEach((char, index) => {
                      const span = doc.createElement("span");
                      if (char === " ") {
                        span.innerHTML = "&nbsp;";
                      } else {
                        span.textContent = char;
                      }
                      span.className = "split-char";
                      span.style.animationDelay = `${index * 35}ms`;
                      h1.appendChild(span);
                    });
                  }
                });
              };

              const enhanceMagicBentoCards = () => {
                const landingVisible = [...doc.querySelectorAll(".page-empty-state")].some((node) => {
                  const rect = node.getBoundingClientRect();
                  const style = window.parent.getComputedStyle(node);
                  return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
                });
                const resultSignal = doc.querySelector([
                  "#jocket-ai-chat-active[data-active='true']",
                  ".stock-terminal-hero",
                  ".market-spectrum-terminal",
                  ".ai-thread .ai-message-row",
                  ".ta-stat-card",
                  ".hedge-update-card",
                  ".metric-card",
                  ".profile-card"
                ].join(","));
                const isResultPage = !landingVisible && Boolean(resultSignal);
                doc.body.classList.toggle("jocket-results-page", isResultPage);

                let spotlight = doc.getElementById("global-cursor-glow");
                if (!isResultPage) {
                  if (spotlight) spotlight.style.opacity = "0";
                  return;
                }

                const glowColor = "218, 220, 224";
                const spotlightRadius = 300;
                const cardSelector = [
                  ".stock-terminal-hero",
                  ".stock-live-price",
                  ".stock-ai-thesis",
                  ".stock-ai-score",
                  ".stock-rating-card",
                  ".stock-score-ring",
                  ".metric-card",
                  ".insight-card",
                  ".rank-card",
                  ".chart-card",
                  "[class*='st-key-result_chart_']",
                  ".result-chart-surface",
                  ".section-card",
                  ".profile-card",
                  ".market-cycle-card",
                  ".market-narrative-card",
                  ".market-ladder-card",
                  ".market-distribution-card",
                  ".market-pulse-panel",
                  ".market-pulse-card",
                  ".market-pos-card",
                  ".market-timeline-card",
                  ".sentiment-card",
                  ".sentiment-hero",
                  ".sentiment-flow-card",
                  ".sentiment-command-strip",
                  ".sentiment-cycle-metrics .mini-metric",
                  ".sentiment-metric-card",
                  ".sentiment-index-card",
                  ".sentiment-board-card",
                  ".sentiment-method-card",
                  ".sentiment-alert",
                  ".glass-table-wrap",
                  ".ta-stat-card",
                  ".hedge-update-card"
                ].join(",");

                const sizeClasses = [
                  "bento-size-1x1",
                  "bento-size-2x1",
                  "bento-size-2x2",
                  "bento-size-2x3",
                  "bento-size-4x1",
                  "bento-size-4x2",
                  "bento-size-4x4",
                  "bento-size-8x2",
                  "bento-size-8x4"
                ];

                const assignBentoSize = (card) => {
                  card.classList.remove(...sizeClasses);
                  const explicitSize = card.dataset.bentoSize;
                  let size = explicitSize || "2x1";

                  if (!explicitSize && card.matches(".metric-card, .ta-stat-card, .sentiment-index-card, .sentiment-cycle-metrics .mini-metric")) {
                    size = "1x1";
                  } else if (!explicitSize && card.matches(".stock-score-ring, .sentiment-metric-card, .sentiment-board-card, .sentiment-method-card")) {
                    size = "2x2";
                  } else if (!explicitSize && card.matches(".stock-live-price, .stock-ai-thesis, .insight-card, .rank-card, .market-pos-card, .market-timeline-card, .chart-card, [class*='st-key-result_chart_'], .result-chart-surface")) {
                    size = "2x2";
                  } else if (!explicitSize && card.matches(".glass-table-wrap")) {
                    size = "8x4";
                  } else if (!explicitSize && card.matches(".stock-terminal-hero, .profile-card, .market-cycle-card, .market-narrative-card, .market-ladder-card, .market-distribution-card, .market-pulse-panel, .sentiment-hero, .sentiment-flow-card, .sentiment-command-strip")) {
                    size = "4x2";
                  }

                  card.classList.add(`bento-size-${size}`);
                  card.dataset.bentoSize = size;
                };

                doc.querySelectorAll(".result-text-card, .result-action-card, .result-bento-card, .section-heading-card").forEach((node) => {
                  node.classList.remove(
                    "result-text-card",
                    "result-action-card",
                    "result-bento-card",
                    "section-heading-card",
                    "magic-bento-card",
                    "magic-bento-card--border-glow",
                    ...sizeClasses
                  );
                  delete node.dataset.bentoSize;
                });

                doc.querySelectorAll("[data-testid='stVerticalBlockBorderWrapper']").forEach((frame) => {
                  if (frame.classList.contains("jocket-dock-host")) return;
                  frame.classList.add("result-frame-only");
                  frame.classList.remove(
                    "result-bento-card",
                    "result-text-card",
                    "chart-card",
                    "magic-bento-card",
                    "magic-bento-card--border-glow",
                    ...sizeClasses
                  );
                });

                doc.querySelectorAll(".result-chart-surface").forEach((element) => {
                  element.classList.remove("result-chart-surface");
                });
                doc.querySelectorAll("[data-testid='stPlotlyChart']").forEach((chart) => {
                  if (chart.closest("[class*='st-key-result_chart_']")) return;
                  chart.closest("[data-testid='stElementContainer']")?.classList.add("result-chart-surface");
                });

                doc.querySelectorAll(".magic-bento-card").forEach((card) => {
                  if (!card.matches(cardSelector)) {
                    card.classList.remove("magic-bento-card", "magic-bento-card--border-glow", ...sizeClasses);
                    delete card.dataset.bentoSize;
                  }
                });

                const candidates = [...doc.querySelectorAll(cardSelector)];
                candidates.forEach((card) => {
                  const parentCard = card.parentElement?.closest(".magic-bento-card");
                  if (parentCard) {
                    card.classList.remove("magic-bento-card", "magic-bento-card--border-glow", "particle-container", ...sizeClasses);
                    delete card.dataset.bentoSize;
                    return;
                  }
                  card.classList.add("magic-bento-card", "magic-bento-card--border-glow");
                  card.classList.remove("particle-container");
                  assignBentoSize(card);
                  card.style.setProperty("--glow-color", glowColor);
                  card.style.setProperty("--glow-radius", `${spotlightRadius}px`);
                  if (card.dataset.reactBitsMagicBound === "stable-v2") return;
                  card.dataset.reactBitsMagicBound = "stable-v2";
                  card.style.setProperty("--glow-intensity", "0");

                  const handleClick = (event) => {
                    if (window.parent.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
                    const rect = card.getBoundingClientRect();
                    const x = event.clientX - rect.left;
                    const y = event.clientY - rect.top;
                    const maxDistance = Math.max(
                      Math.hypot(x, y),
                      Math.hypot(x - rect.width, y),
                      Math.hypot(x, y - rect.height),
                      Math.hypot(x - rect.width, y - rect.height)
                    );
                    const ripple = doc.createElement("span");
                    ripple.className = "magic-bento-ripple";
                    ripple.style.setProperty("--ripple-x", `${x - maxDistance}px`);
                    ripple.style.setProperty("--ripple-y", `${y - maxDistance}px`);
                    ripple.style.setProperty("--ripple-size", `${maxDistance * 2}px`);
                    card.appendChild(ripple);
                    window.parent.setTimeout(() => ripple.remove(), 840);
                  };

                  card.addEventListener("click", handleClick, { passive: true });
                });

                doc.querySelectorAll(".particle").forEach((node) => node.remove());

                if (!spotlight) {
                  spotlight = doc.createElement("div");
                  spotlight.id = "global-cursor-glow";
                  doc.body.appendChild(spotlight);
                }
                spotlight.style.setProperty("--glow-color", glowColor);

                if (!window.parent._jocketResultMagicBentoStableBound) {
                  window.parent._jocketResultMagicBentoStableBound = true;
                  doc.addEventListener("mousemove", (event) => {
                    const disableMotion = window.parent.matchMedia("(max-width: 768px), (prefers-reduced-motion: reduce)").matches;
                    if (!doc.body.classList.contains("jocket-results-page") || disableMotion) return;
                    window.parent._jocketResultPointer = { x: event.clientX, y: event.clientY };
                    if (window.parent._jocketResultPointerFrame) return;
                    window.parent._jocketResultPointerFrame = window.parent.requestAnimationFrame(() => {
                      window.parent._jocketResultPointerFrame = null;
                      const pointer = window.parent._jocketResultPointer;
                      const activeSpotlight = doc.getElementById("global-cursor-glow");
                      if (!pointer || !activeSpotlight || !doc.body.classList.contains("jocket-results-page")) return;
                      activeSpotlight.style.left = `${pointer.x}px`;
                      activeSpotlight.style.top = `${pointer.y}px`;

                      const cards = [...doc.querySelectorAll(".magic-bento-card")];
                      const proximity = spotlightRadius * 0.5;
                      const fadeDistance = spotlightRadius * 0.75;
                      let minDistance = Infinity;
                      cards.forEach((card) => {
                        const rect = card.getBoundingClientRect();
                        if (!rect.width || !rect.height) return;
                        const centerX = rect.left + rect.width / 2;
                        const centerY = rect.top + rect.height / 2;
                        const effectiveDistance = Math.max(
                          0,
                          Math.hypot(pointer.x - centerX, pointer.y - centerY) - Math.max(rect.width, rect.height) / 2
                        );
                        minDistance = Math.min(minDistance, effectiveDistance);
                        const intensity = effectiveDistance <= proximity
                          ? 1
                          : effectiveDistance <= fadeDistance
                            ? (fadeDistance - effectiveDistance) / (fadeDistance - proximity)
                            : 0;
                        card.style.setProperty("--glow-x", `${((pointer.x - rect.left) / rect.width) * 100}%`);
                        card.style.setProperty("--glow-y", `${((pointer.y - rect.top) / rect.height) * 100}%`);
                        card.style.setProperty("--glow-intensity", `${intensity}`);
                      });
                      const localOpacity = minDistance <= proximity
                        ? 0.8
                        : minDistance <= fadeDistance
                          ? ((fadeDistance - minDistance) / (fadeDistance - proximity)) * 0.8
                          : 0;
                      activeSpotlight.style.opacity = `${Math.max(0.28, localOpacity)}`;
                    });
                  }, { passive: true });

                  doc.addEventListener("mouseleave", () => {
                    const activeSpotlight = doc.getElementById("global-cursor-glow");
                    if (activeSpotlight) activeSpotlight.style.opacity = "0";
                    doc.querySelectorAll(".magic-bento-card").forEach((card) => {
                      card.style.setProperty("--glow-intensity", "0");
                    });
                  }, { passive: true });
                }
              };

              // Native port of React Bits Text Type for Streamlit-rendered
              // loading copy. The animation state lives on the parent window
              // so the 2-second progress fragment refresh cannot restart it.
              const enhanceLoadingTextType = () => {
                const visibleNodes = [...doc.querySelectorAll("[data-jocket-text-type]")]
                  .filter((candidate) => candidate.isConnected && candidate.getClientRects().length > 0);
                const node = visibleNodes[visibleNodes.length - 1];
                if (!node) {
                  const staleController = window.parent._jocketLoadingTextTypeController;
                  if (staleController?.timer) window.parent.clearTimeout(staleController.timer);
                  window.parent._jocketLoadingTextTypeController = null;
                  return;
                }

                  const signature = node.getAttribute("data-messages") || "";
                  if (!signature) return;

                  let messages = [];
                  try {
                    messages = JSON.parse(signature);
                  } catch (error) {
                    return;
                  }
                  messages = messages.map((message) => String(message || "")).filter(Boolean);
                  if (!messages.length) return;

                  const output = node.querySelector(".jocket-text-type-output");
                  const cursor = node.querySelector(".jocket-text-type-cursor");
                  if (!output || !cursor) return;

                  if (window.parent.matchMedia("(prefers-reduced-motion: reduce)").matches) {
                    output.textContent = messages[0];
                    cursor.hidden = true;
                    return;
                  }

                  const typingSpeed = 90;
                  const deletingSpeed = 50;
                  const pauseDuration = 4000;
                  const betweenMessages = 350;
                  let controller = window.parent._jocketLoadingTextTypeController;

                  const renderControllerText = (activeController) => {
                    doc.querySelectorAll("[data-jocket-text-type]").forEach((activeNode) => {
                      if (!activeNode.isConnected || activeNode.getClientRects().length === 0) return;
                      if (activeNode.getAttribute("data-messages") !== activeController.signature) return;
                      const activeOutput = activeNode.querySelector(".jocket-text-type-output");
                      const activeCursor = activeNode.querySelector(".jocket-text-type-cursor");
                      if (activeOutput) activeOutput.textContent = activeController.renderedText;
                      if (activeCursor) activeCursor.hidden = false;
                    });
                  };

                  if (controller && controller.signature === signature) {
                    renderControllerText(controller);
                    return;
                  }

                  if (controller?.timer) {
                    window.parent.clearTimeout(controller.timer);
                  }
                  controller = {
                    signature,
                    messages,
                    messageIndex: 0,
                    characterIndex: 0,
                    deleting: false,
                    renderedText: "",
                    timer: null
                  };
                  window.parent._jocketLoadingTextTypeController = controller;

                  const tick = () => {
                    if (window.parent._jocketLoadingTextTypeController !== controller) return;
                    const characters = Array.from(controller.messages[controller.messageIndex]);

                    if (!controller.deleting) {
                      controller.characterIndex = Math.min(controller.characterIndex + 1, characters.length);
                      controller.renderedText = characters.slice(0, controller.characterIndex).join("");
                      renderControllerText(controller);
                      if (controller.characterIndex >= characters.length) {
                        controller.deleting = true;
                        controller.timer = window.parent.setTimeout(tick, pauseDuration);
                        return;
                      }
                      controller.timer = window.parent.setTimeout(tick, typingSpeed);
                      return;
                    }

                    controller.characterIndex = Math.max(controller.characterIndex - 1, 0);
                    controller.renderedText = characters.slice(0, controller.characterIndex).join("");
                    renderControllerText(controller);
                    if (controller.characterIndex === 0) {
                      controller.deleting = false;
                      controller.messageIndex = (controller.messageIndex + 1) % controller.messages.length;
                      controller.timer = window.parent.setTimeout(tick, betweenMessages);
                      return;
                    }
                    controller.timer = window.parent.setTimeout(tick, deletingSpeed);
                  };

                  tick();
              };

              enhanceAiInputLoading();
              enhanceDockHosts();
              animateCommandBarHeight();
              enhanceNav();
              enhanceProvider();
              enhanceHedgeMode();
              fixSkillsLayout();
              fixHistoryLayout();
              fixAnalystLayout();
              enhanceLaicaiButtons();
              enhanceDetailsTransition();
              enhanceAiPromptRail();
              enhanceAiPromptHotkeys();
              enhanceMagicBentoCards();
              enhanceSplitText();
              enhanceLoadingTextType();
              if (!window.parent._jocketMagicBentoEnhancerBound) {
                window.parent._jocketMagicBentoEnhancerBound = true;
                const MagicObserver = window.parent.MutationObserver || window.MutationObserver;
                let magicRefreshTimer = null;
                const magicObserver = new MagicObserver(() => {
                  try { enhanceNav(); } catch (error) {}
                  try { enhanceProvider(); } catch (error) {}
                  try { enhanceHedgeMode(); } catch (error) {}
                  try { enhanceDockHosts(); } catch (error) {}
                  
                  if (magicRefreshTimer !== null) return;
                  magicRefreshTimer = window.parent.setTimeout(() => {
                    magicRefreshTimer = null;
                    try { enhanceMagicBentoCards(); } catch (error) {}
                    try { enhanceSplitText(); } catch (error) {}
                    try { enhanceLoadingTextType(); } catch (error) {}
                  }, 120);
                });
                if (doc.body && typeof doc.body.nodeType === "number") {
                  try {
                    magicObserver.observe(doc.body, { childList: true, subtree: true });
                    window.parent._jocketMagicBentoObserver = magicObserver;
                  } catch (error) {}
                }
              }
              manageSplashCursor();
              manageDotField();
              if (win.__jocketUiRefreshInterval) {
                win.clearInterval(win.__jocketUiRefreshInterval);
              }
              win.__jocketUiRefreshInterval = win.setInterval(() => { enhanceNav(); enhanceProvider(); enhanceDockHosts(); enhanceHedgeMode(); fixSkillsLayout(); fixHistoryLayout(); fixAnalystLayout(); enhanceAiInputLoading(); enhanceAiPromptRail(); enhanceAiPromptHotkeys(); enhanceSplitText(); enhanceLoadingTextType(); animateCommandBarHeight(); enhanceLaicaiButtons(); enhanceDetailsTransition(); manageSplashCursor(); manageDotField(); }, 240);
              
              // Cancel button speed-up listener: closes the modal instantly on client-side!
              doc.addEventListener("click", (event) => {
                const cancelBtn = event.target.closest('[class*="st-key-cancel_del_btn"] button');
                if (cancelBtn) {
                  const dialog = doc.querySelector('div[role="dialog"]');
                  const backdrop = doc.querySelector('[data-testid="stDialog"], [data-testid="stModal"]');
                  if (dialog) dialog.style.setProperty('display', 'none', 'important');
                  if (backdrop) backdrop.style.setProperty('display', 'none', 'important');
                  
                  const closeBtn = doc.querySelector('button[aria-label="Close"], [class*="stDialogHeader"] button, [data-testid="stDialog"] button');
                  if (closeBtn) closeBtn.click();
                }
              }, { passive: true });

              // ──────────────── Popover Fade-In/Out Animation ────────────────
              if (!win.__jocketPopoverAnimObserver) {
                const popAnim = new MutationObserver((mutations) => {
                  mutations.forEach((mutation) => {
                    mutation.addedNodes.forEach((node) => {
                      if (node.nodeType !== 1) return;
                      const body = (node.getAttribute && node.getAttribute('data-testid') === 'stPopoverBody')
                        ? node
                        : (node.querySelector && node.querySelector('[data-testid="stPopoverBody"]'));
                      if (body) {
                        body.style.setProperty('animation', 'none', 'important');
                        void body.offsetWidth;
                        body.style.setProperty('animation', 'jocket-popover-in 0.22s cubic-bezier(0.16, 1, 0.3, 1) both', 'important');
                      }
                    });
                  });
                });
                try {
                  popAnim.observe(doc.body, { childList: true, subtree: true });
                  win.__jocketPopoverAnimObserver = popAnim;
                } catch(e) {}
              }

              // ──────────────── Variable Proximity Title Animation ────────────────
              if (!window.parent._jocketProximityBound) {
                window.parent._jocketProximityBound = true;
                window.parent._jocketMouseX = null;
                window.parent._jocketMouseY = null;
                
                doc.addEventListener("mousemove", (event) => {
                  window.parent._jocketMouseX = event.clientX;
                  window.parent._jocketMouseY = event.clientY;
                }, { passive: true });
                
                doc.addEventListener("mouseleave", () => {
                  window.parent._jocketMouseX = null;
                  window.parent._jocketMouseY = null;
                }, { passive: true });
                
                doc.addEventListener("touchmove", (event) => {
                  if (event.touches && event.touches[0]) {
                    window.parent._jocketMouseX = event.touches[0].clientX;
                    window.parent._jocketMouseY = event.touches[0].clientY;
                  }
                }, { passive: true });

                const runProximityAnimation = () => {
                  const chars = doc.querySelectorAll(".page-empty-state h1 .split-char");
                  if (chars.length > 0) {
                    const radius = 175; // px (Proximity detection radius)
                    const fromWght = 300;
                    const toWght = 900;
                    const mouseX = window.parent._jocketMouseX;
                    const mouseY = window.parent._jocketMouseY;
                    
                    chars.forEach((char) => {
                      if (mouseX === null || mouseY === null) {
                        char.style.setProperty("font-variation-settings", `'wght' ${fromWght}`, "important");
                        return;
                      }
                      const rect = char.getBoundingClientRect();
                      const charX = rect.left + rect.width / 2;
                      const charY = rect.top + rect.height / 2;
                      
                      const distance = Math.hypot(mouseX - charX, mouseY - charY);
                      if (distance >= radius) {
                        char.style.setProperty("font-variation-settings", `'wght' ${fromWght}`, "important");
                      } else {
                        const norm = 1 - distance / radius;
                        const currentWght = fromWght + (toWght - fromWght) * norm;
                        char.style.setProperty("font-variation-settings", `'wght' ${currentWght}`, "important");
                      }
                    });
                  }
                  window.parent.requestAnimationFrame(runProximityAnimation);
                };
                
                window.parent.requestAnimationFrame(runProximityAnimation);
              }

            })();
            </script>
            """,
            height=0,
        )

        # Keep the sector bubbles physically responsive to the pointer. This is
        # deliberately separate from the ambient drift animation so mouse input
        # never restarts or snaps the motion timeline.
        components.html(
            """
            <script>
            (() => {
              const doc = window.parent.document;
              const bindBubbleStages = () => {
                doc.querySelectorAll(".market-bubble-stage").forEach((stage) => {
                  if (stage.dataset.jocketBubblePointer === "v3") return;
                  stage.dataset.jocketBubblePointer = "v3";
                  const reset = () => stage.querySelectorAll(".market-bubble").forEach((bubble) => {
                    bubble.style.setProperty("--pointer-x", "0px");
                    bubble.style.setProperty("--pointer-y", "0px");
                  });
                  stage.addEventListener("pointermove", (event) => {
                    if (window.parent.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
                    const rect = stage.getBoundingClientRect();
                    if (!rect.width || !rect.height) return;
                    const x = ((event.clientX - rect.left) / rect.width - 0.5) * 2;
                    const y = ((event.clientY - rect.top) / rect.height - 0.5) * 2;
                    stage.querySelectorAll(".market-bubble").forEach((bubble, index) => {
                      const depth = 5 + index * 1.8;
                      bubble.style.setProperty("--pointer-x", `${(x * depth).toFixed(2)}px`);
                      bubble.style.setProperty("--pointer-y", `${(y * depth).toFixed(2)}px`);
                    });
                  }, { passive: true });
                  stage.addEventListener("pointerleave", reset, { passive: true });
                });
              };
              bindBubbleStages();
              if (!window.parent._jocketBubbleObserverV3) {
                const observer = new window.parent.MutationObserver(bindBubbleStages);
                observer.observe(doc.body, { childList: true, subtree: true });
                window.parent._jocketBubbleObserverV3 = observer;
              }
            })();
            </script>
            """,
            height=0,
        )



def _safe(value, default="-"):
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    return value


def _fmt_count(value) -> str:
    try:
        return str(int(float(value)))
    except Exception:
        return "-"

def format_number_cn(value, digits: int = 2, suffix: str = "") -> str:
    value = _safe(value, None)
    if value is None:
        return "-"
    try:
        num = float(value)
    except Exception:
        return str(value)
    sign = "-" if num < 0 else ""
    num = abs(num)
    if num >= 100_000_000:
        return f"{sign}{num / 100_000_000:.{digits}f}亿{suffix}"
    if num >= 10_000:
        return f"{sign}{num / 10_000:.{digits}f}万{suffix}"
    return f"{sign}{num:,.{digits}f}{suffix}"


def format_percent(value, digits: int = 2) -> str:
    value = _safe(value, None)
    if value is None:
        return "-"
    try:
        num = float(value)
    except Exception:
        return str(value)
    if abs(num) <= 1:
        num *= 100
    return f"{num:+.{digits}f}%"


def format_percent_or_na(value, digits: int = 2) -> str:
    text = format_percent(value, digits)
    return "N/A" if text == "-" else text


def format_price(value, digits: int = 2) -> str:
    value = _safe(value, None)
    if value is None:
        return "-"
    try:
        return f"{float(value):,.{digits}f}"
    except Exception:
        return str(value)


def render_hero(
    code: str = "-",
    data_source: str = "-",
    latest_date: str = "-",
    updated_at: str | None = None,
    title: str | None = None,
    subtitle: str | None = None,
    ai_summary: str | None = None,
    custom_html: str | None = None,
) -> None:
    updated_at = updated_at or datetime.now().strftime("%Y-%m-%d %H:%M")
    title = title or "A股智能雷达"
    subtitle = subtitle or "基于最新行情、技术指标和基本面信息生成中文研究视图。"
    
    ai_block = ""
    if ai_summary:
        ai_block = (
            f'<div class="ai-hero-summary">'
            f'<span class="ai-sparkle">✨</span>'
            f'<span class="ai-summary-text">{escape(str(ai_summary))}</span>'
            f'</div>'
        )

    custom_block = ""
    if custom_html:
        custom_block = custom_html

    html = (
        f'<section class="hero-shell jocket-enter">'
        f'<div class="hero-content">'
        f'<div>'
        f'<div class="eyebrow">A股智能分析仪表盘</div>'
        f'<h1 class="hero-title">{escape(str(title))}</h1>'
        f'<p class="hero-subtitle">{escape(str(subtitle))}</p>'
        f'{ai_block}'
        f'</div>'
        f'<div class="hero-meta-grid">'
        f'<div class="hero-meta-item">'
        f'<div class="meta-label">股票代码</div>'
        f'<div class="meta-value">{escape(str(code or "-"))}</div>'
        f'</div>'
        f'<div class="hero-meta-item">'
        f'<div class="meta-label">状态</div>'
        f'<div class="meta-value">{escape(str(data_source or "-"))}</div>'
        f'</div>'
        f'<div class="hero-meta-item">'
        f'<div class="meta-label">最新交易日</div>'
        f'<div class="meta-value">{escape(str(latest_date or "-"))}</div>'
        f'</div>'
        f'<div class="hero-meta-item">'
        f'<div class="meta-label">更新时间</div>'
        f'<div class="meta-value">{escape(str(updated_at))}</div>'
        f'</div>'
        f'</div>'
        f'</div>'
        f'</section>'
        f'{custom_block}'
    )
    st.markdown(html, unsafe_allow_html=True)


@st.fragment(run_every="2s")
def render_inline_progress_fragment(job_state_key: str) -> None:
    import streamlit as st
    from html import escape
    import sys
    import os

    job = st.session_state.get(job_state_key)
    if not job:
        st.write("")
        return

    pct_val = "0%"
    text_val = "正在初始化..."

    # Case 1: Standard background job state represented by a dict
    if isinstance(job, dict):
        future = job.get("future")
        if future is not None and future.done():
            st.rerun()

        progress = job.get("progress") or {}
        stage = str(progress.get("stage") or "fetch")
        
        pct_map = {
            "fetch": "33%",
            "compute": "66%",
            "view": "90%",
            "done": "100%"
        }
        pct_val = pct_map.get(stage, "33%")
        
        text_map = {
            "fetch": "正在检索多维行情数据...",
            "compute": "正在计算量化指标与财务评分...",
            "view": "正在生成智能视图与AI诊断...",
            "done": "任务已完成"
        }
        text_val = text_map.get(stage, "正在拉取行情...")

    # Case 2: ProgressTracker object (from tradingagents_ui.py)
    elif hasattr(job, "completed_stages") and hasattr(job, "ticker"):
        _TA_SRC = os.path.join(os.path.dirname(__file__), "tradingagents_src")
        if _TA_SRC not in sys.path:
            sys.path.insert(0, _TA_SRC)
        from web.progress import PIPELINE_STAGES
        
        completed = len(job.completed_stages)
        total = len(PIPELINE_STAGES)
        pct = completed / total if total else 0
        pct_val = f"{int(pct * 100)}%"

        # Current active stage name
        active_stage = "初始化分析环境..."
        for s in PIPELINE_STAGES:
            s_id = s["id"]
            if s_id not in job.completed_stages:
                active_stage = f"正在执行：{s['name']}..."
                break
        if completed == total:
            active_stage = "分析已完成"
        
        text_val = f"投研智能体群组分析中 ({job.ticker}) - {active_stage}"

    # Case 3: HedgeProgressTracker object (from hedge_ui.py)
    elif hasattr(job, "tickers") and hasattr(job, "current_status"):
        text_val = f"量化对冲运行中 - {job.current_status or '初始化数据层'}"
        if job.current_ticker:
            text_val += f" ({job.current_ticker})"

        if job.is_complete:
            pct_val = "100%"
        else:
            done_count = len([u for u in job.agent_updates if u.get("status", "").lower() == "done"])
            total_expected = len(job.tickers) * max(1, len(st.session_state.get("selected_hedge_agents", [])))
            if total_expected > 0:
                pct = min(0.95, done_count / total_expected)
                pct_val = f"{int(pct * 100)}%"
            else:
                pct_val = "33%"

    st.markdown(
        f"""
        <div class="jocket-global-progress-bar" aria-live="polite">
          <div class="jocket-progress-text-row">
            <span class="jocket-progress-status-text">{escape(text_val)}</span>
            <span class="jocket-progress-percentage-text">{pct_val}</span>
          </div>
          <div class="jocket-progress-track-outer">
            <div class="jocket-progress-track-inner">
              <div class="jocket-progress-fill" style="width: {pct_val};"></div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.fragment(run_every="2s")
def render_unified_loading_state_fragment(title: str, capsules: list, show_progress_key: str) -> None:
    import json
    import streamlit as st
    from html import escape
    import sys
    import os

    job = st.session_state.get(show_progress_key)
    if not job:
        st.write("")
        return

    pct_val = "0%"
    text_val = "正在初始化..."

    # Case 1: Standard background job state represented by a dict
    if isinstance(job, dict):
        future = job.get("future")
        if future is not None and future.done():
            st.rerun()

        progress = job.get("progress") or {}
        stage = str(progress.get("stage") or "fetch")
        
        pct_map = {
            "fetch": "33%",
            "compute": "66%",
            "view": "90%",
            "done": "100%"
        }
        pct_val = pct_map.get(stage, "33%")
        
        text_map = {
            "fetch": "正在检索多维行情数据...",
            "compute": "正在计算量化指标与财务评分...",
            "view": "正在生成智能视图与AI诊断...",
            "done": "任务已完成"
        }
        text_val = text_map.get(stage, "正在拉取行情...")

    # Case 2: ProgressTracker object (from tradingagents_ui.py)
    elif hasattr(job, "completed_stages") and hasattr(job, "ticker"):
        _TA_SRC = os.path.join(os.path.dirname(__file__), "tradingagents_src")
        if _TA_SRC not in sys.path:
            sys.path.insert(0, _TA_SRC)
        from web.progress import PIPELINE_STAGES
        
        completed = len(job.completed_stages)
        total = len(PIPELINE_STAGES)
        pct = completed / total if total else 0
        pct_val = f"{int(pct * 100)}%"

        # Current active stage name
        active_stage = "初始化分析环境..."
        for s in PIPELINE_STAGES:
            s_id = s["id"]
            if s_id not in job.completed_stages:
                active_stage = f"正在执行：{s['name']}..."
                break
        if completed == total:
            active_stage = "分析已完成"
        
        text_val = f"投研智能体群组分析中 ({job.ticker}) - {active_stage}"

    # Case 3: HedgeProgressTracker object (from hedge_ui.py)
    elif hasattr(job, "tickers") and hasattr(job, "current_status"):
        text_val = f"量化对冲运行中 - {job.current_status or '初始化数据层'}"
        if job.current_ticker:
            text_val += f" ({job.current_ticker})"

        if job.is_complete:
            pct_val = "100%"
        else:
            done_count = len([u for u in job.agent_updates if u.get("status", "").lower() == "done"])
            total_expected = len(job.tickers) * max(1, len(st.session_state.get("selected_hedge_agents", [])))
            if total_expected > 0:
                pct = min(0.95, done_count / total_expected)
                pct_val = f"{int(pct * 100)}%"
            else:
                pct_val = "33%"

    capsules_html = ""
    for capsule in capsules:
        if isinstance(capsule, dict):
            lbl = capsule.get("label", "")
            prt = capsule.get("prompt", "")
            button_style = capsule.get("style", "")
        else:
            lbl = str(capsule)
            prt = str(capsule)
            button_style = ""
        style_attr = f' data-jocket-button-style="{escape(button_style)}"' if button_style else ""
        capsules_html += f'<span data-ai-prompt="{escape(prt)}"{style_attr}>{escape(lbl)}</span>'

    rail_html = ""
    if capsules_html:
        rail_html = f'<div class="ai-prompt-rail">{capsules_html}</div>'
    else:
        rail_html = '<div class="ai-prompt-rail" style="opacity: 0 !important; pointer-events: none !important; height: 47px !important; min-height: 47px !important; margin-top: 24px !important; margin-bottom: 0 !important; padding: 0 !important; width: 385px !important; max-width: 100% !important;"></div>'

    loading_messages = [
        text_val,
        f"当前加载进度 {pct_val}，请耐心等待",
        "分析仍在后台继续，您可以稍后回来查看",
        "请稍候，Jocket 正在整理最终结果",
    ]
    loading_messages_json = escape(json.dumps(loading_messages, ensure_ascii=False), quote=True)

    # Keep the subtitle and its original vertical footprint, while replacing
    # the progress bar itself with the looping Text Type copy.
    subtitle_progress_html = (
        f'<p class="hero-subtitle jocket-loading-subtitle">'
        f'<span class="jocket-loading-subtitle-text jocket-loading-text-type" '
        f'data-jocket-text-type="true" data-messages="{loading_messages_json}" '
        f'aria-label="{escape(text_val)}, 当前加载进度 {pct_val}">'
        f'<span class="jocket-text-type-output" aria-hidden="true">{escape(text_val)}</span>'
        f'<span class="jocket-text-type-cursor" aria-hidden="true">_</span>'
        f'</span>'
        f'</p>'
        f'<div class="jocket-loading-progress-spacer" aria-hidden="true"></div>'
    )

    st.markdown(
        f'<div class="jocket-loading-marker" data-jocket-loading-active="true" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<section class="ai-empty-state ai-chat-shell page-empty-state page-g-standard">'
        f'<div class="ai-chat-shell-text">'
        f'<div class="jocket-empty-state-orb-anchor"></div>'
        f'<h1 data-jocket-title="{escape(title)}">{escape(title)}</h1>'
        f'{subtitle_progress_html}'
        f'<div class="jocket-landing-action-container">{rail_html}</div>'
        f'</div>'
        f'</section>',
        unsafe_allow_html=True,
    )


def render_jocket_unified_empty_state(
    title: str,
    subtitle: str,
    capsules: list,
    show_model_selector: bool = False,
    show_progress_key: str | None = None
) -> None:
    import streamlit as st
    from html import escape
    from datetime import datetime

    if show_progress_key:
        render_unified_loading_state_fragment(title, capsules, show_progress_key)
        return

    # Pre-render capsules HTML
    capsules_html = ""
    for capsule in capsules:
        if isinstance(capsule, dict):
            lbl = capsule.get("label", "")
            prt = capsule.get("prompt", "")
            button_style = capsule.get("style", "")
        else:
            lbl = str(capsule)
            prt = str(capsule)
            button_style = ""
        style_attr = f' data-jocket-button-style="{escape(button_style)}"' if button_style else ""
        capsules_html += f'<span data-ai-prompt="{escape(prt)}"{style_attr}>{escape(lbl)}</span>'

    rail_html = ""
    if capsules_html:
        rail_html = f'<div class="ai-prompt-rail">{capsules_html}</div>'

    st.markdown(
        f'<section class="ai-empty-state ai-chat-shell page-empty-state page-g-standard">'
        f'<div class="ai-chat-shell-text">'
        f'<div class="jocket-empty-state-orb-anchor"></div>'
        f'<h1 data-jocket-title="{escape(title)}">{escape(title)}</h1>'
        f'<p>{escape(subtitle)}</p>'
        f'<div class="jocket-landing-action-container">{rail_html}</div>'
        f'</div>'
        f'</section>',
        unsafe_allow_html=True,
    )

    # 2. Render model selector segmented control second (so it sits centered below the text greeting!)
    if show_model_selector:
        provider_options = ["Gemini", "DeepSeek"]
        selected_label = st.segmented_control(
            "AI模型",
            provider_options,
            default=st.session_state.get("ai_market_provider_label", "DeepSeek"),
            key="ai_market_provider_label",
            label_visibility="collapsed",
        )
            
        st.markdown(f'<div id="jocket-ai-provider" data-provider="{escape(str(selected_label))}"></div>', unsafe_allow_html=True)


def metric_card(label: str, value: str, footnote: str = "", tone: str = "cyan", indicator: str = "neutral", size: str = "2x1") -> str:
    pill_class = {
        "green": "pill-green",
        "red": "pill-red",
        "cyan": "pill-cyan",
        "purple": "pill-purple",
        "orange": "pill-orange",
        "blue": "pill-cyan",
    }.get(tone, "pill-cyan")
    tone_color = {
        "green": "#33D69F",
        "red": "#FF5C7A",
        "cyan": "#37E8FF",
        "purple": "#9B5CFF",
        "orange": "#FFB86B",
        "blue": "#5B8CFF",
    }.get(tone, "#37E8FF")
    icon_map = {
        "up": "上行",
        "down": "下行",
        "neutral": "中性",
        "high": "偏高",
        "low": "偏低",
        "good": "较好",
        "weak": "弱势",
        "active": "活跃",
        "strong": "强势",
        "fresh": "已更新",
        "mild_strong": "偏强",
        "mild_weak": "偏弱",
        "bull_win": "多方胜",
        "bear_win": "空方胜",
        "draw": "平手",
    }
    icon = icon_map.get(indicator, indicator)
    return (
        f'<div class="metric-card bento-size-{escape(size)}" data-bento-size="{escape(size)}" style="--card-glow:{tone_color}">'
        f'<div class="metric-inner">'
        f'<div class="metric-label">{escape(label)}</div>'
        f'<div class="metric-value">{escape(value)}</div>'
        f'<div class="metric-foot"><span>{escape(footnote)}</span><span class="pill {pill_class}">{icon}</span></div>'
        f'</div></div>'
    )


def render_bento_grid(cards: Iterable[str]) -> None:
    st.markdown('<div class="bento-grid">' + "".join(cards) + "</div>", unsafe_allow_html=True)


def render_glass_dataframe(df: pd.DataFrame, height: int | None = None) -> None:
    if df is None:
        df = pd.DataFrame()
    frame = df.copy()
    max_height = f"max-height:{int(height)}px;" if height else ""
    html = frame.to_html(index=False, escape=True, classes="glass-dataframe-table", border=0)
    st.markdown(f'<div class="glass-table-wrap" style="{max_height}">{html}</div>', unsafe_allow_html=True)


def bento_card_start(title: str = "", badge: str = "") -> None:
    badge_html = f'<span class="pill pill-cyan">{escape(badge)}</span>' if badge else ""
    st.markdown(
        f'<div class="section-card"><div class="chart-title"><span>{escape(title)}</span>{badge_html}</div>',
        unsafe_allow_html=True,
    )


def bento_card_end() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


def render_score_badge(score) -> str:
    try:
        num = float(score)
    except Exception:
        num = 0
    if num >= 75:
        cls = "pill-green"
        label = "强势"
    elif num >= 60:
        cls = "pill-cyan"
        label = "观察"
    else:
        cls = "pill-orange"
        label = "谨慎"
    return f'<span class="pill {cls}">{label} {num:.1f}</span>'


def render_warning_badge(text: str) -> str:
    return f'<span class="risk-badge" data-tip="{escape(text)}">{escape(text[:18])}{"..." if len(text) > 18 else ""}</span>'


def render_section_title(title: str, subtitle: str = "") -> None:
    st.markdown(f'<h2 class="section-title">{escape(title)}</h2>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<p class="section-subtitle">{escape(subtitle)}</p>', unsafe_allow_html=True)


def render_insight_cards(insights: list[dict]) -> None:
    cards = []
    for item in insights:
        tone = item.get("tone", "cyan")
        pill_class = {
            "green": "pill-green",
            "red": "pill-red",
            "orange": "pill-orange",
            "purple": "pill-purple",
            "cyan": "pill-cyan",
        }.get(tone, "pill-cyan")
        cards.append(
            f'<div class="insight-card">'
            f'<div class="insight-label">{escape(item.get("label", "观察点"))}</div>'
            f'<div class="insight-title">{escape(item.get("title", "-"))}</div>'
            f'<div class="insight-body">{escape(item.get("body", "-"))}</div>'
            f'<div class="insight-foot"><span class="pill {pill_class}">{escape(item.get("badge", "信号"))}</span></div>'
            f'</div>'
        )
    st.markdown('<div class="insight-grid bento-section">' + "".join(cards) + "</div>", unsafe_allow_html=True)


def _base_fig(fig: go.Figure, height: int = 420) -> go.Figure:
    fig.update_layout(
        height=height,
        paper_bgcolor=PAPER_BG,
        plot_bgcolor=PLOT_BG,
        font=dict(color=TEXT, family="Inter, system-ui, sans-serif"),
        margin=dict(l=16, r=16, t=46, b=16),
        hovermode="x unified",
        dragmode="pan",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(color=MUTED, size=12),
            bgcolor="rgba(7,11,18,0.20)",
        ),
        hoverlabel=dict(
            bgcolor=GLASS_HOVER_BG,
            bordercolor=GLASS_HOVER_BORDER,
            font=dict(color=TEXT, size=13, family="Inter, system-ui, sans-serif"),
            align="left",
        ),
        transition=dict(duration=250, easing="cubic-in-out"),
    )
    fig.update_xaxes(
        showgrid=True,
        gridcolor="rgba(255,255,255,0.035)",
        zerolinecolor="rgba(255,255,255,0.12)",
        color=MUTED,
        rangeslider_visible=False,
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikecolor="rgba(245,247,250,0.52)",
        spikedash="dot",
        spikethickness=1,
        tickfont=dict(color=MUTED, size=12),
        title_font=dict(color=MUTED, size=13),
    )
    fig.update_yaxes(
        gridcolor="rgba(255,255,255,0.075)",
        zerolinecolor="rgba(255,255,255,0.13)",
        color=MUTED,
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikecolor="rgba(245,247,250,0.42)",
        spikedash="dot",
        spikethickness=1,
        tickfont=dict(color=MUTED, size=12),
        title_font=dict(color=MUTED, size=13),
    )
    return fig


def style_plotly_figure(fig: go.Figure, height: int = 420) -> go.Figure:
    return _base_fig(fig, height)


def _apply_recent_x_window(fig: go.Figure, data: pd.DataFrame, visible_days: int = 14, show_rangeslider: bool = False) -> go.Figure:
    if data is not None and not data.empty and "date" in data.columns:
        dates = pd.to_datetime(data["date"], errors="coerce").dropna()
        if not dates.empty:
            start_idx = max(0, len(dates) - int(visible_days))
            fig.update_xaxes(range=[dates.iloc[start_idx], dates.iloc[-1]], rangeslider_visible=show_rangeslider)
            fig.update_layout(dragmode="pan")
    return fig


def plot_price_trend(df: pd.DataFrame) -> go.Figure:
    data = df.tail(120).copy()
    fig = go.Figure()
    has_ohlc = all(col in data.columns for col in ["open", "high", "low", "close"])
    if has_ohlc:
        fig.add_trace(
            go.Candlestick(
                x=data["date"],
                open=data["open"],
                high=data["high"],
                low=data["low"],
                close=data["close"],
                name="K线",
                increasing=dict(line=dict(color=GREEN, width=1.8), fillcolor="rgba(51,214,159,0.52)"),
                decreasing=dict(line=dict(color=RED, width=1.8), fillcolor="rgba(255,92,122,0.50)"),
                whiskerwidth=0.45,
                hovertext=[
                    f"K线<br>{x}<br>开 {o:.2f}<br>高 {h:.2f}<br>低 {l:.2f}<br>收 {c:.2f}"
                    for x, o, h, l, c in zip(data["date"], data["open"], data["high"], data["low"], data["close"])
                ],
                hoverinfo="text",
            )
        )
    else:
        _add_glow_line(fig, x=data["date"], y=data["close"], name="收盘价", color=CYAN, width=3.0)
    for ma, color in [("ma20", CYAN), ("ma60", BLUE), ("ma120", PURPLE)]:
        if ma in data.columns and data[ma].notna().any():
            _add_glow_line(fig, x=data["date"], y=data[ma], name=ma.upper(), color=color, width=2.35, hovertemplate=f"{ma.upper()}<br>%{{x}}<br>%{{y:.2f}}<extra></extra>")
    return _apply_recent_x_window(_base_fig(fig, 460), data, 14, True)


def plot_market_sentiment_cycle(history: pd.DataFrame) -> go.Figure:
    data = history.tail(90).copy() if history is not None else pd.DataFrame()
    fig = go.Figure()
    if data.empty:
        return _base_fig(fig, 420)
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    missing = pd.to_numeric(data.get("history_missing", 0), errors="coerce").fillna(0)
    counts = (
        pd.to_numeric(data.get("limit_up_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(data.get("broken_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(data.get("limit_down_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(data.get("strong_count", 0), errors="coerce").fillna(0)
    )
    data = data[(missing <= 0) & (counts > 0)].copy()
    if data.empty:
        return _base_fig(fig, 420)
    limit_count = pd.to_numeric(data.get("limit_up_count", 0), errors="coerce").fillna(0)
    broken_count = pd.to_numeric(data.get("broken_count", 0), errors="coerce").fillna(0)
    down_count = pd.to_numeric(data.get("limit_down_count", 0), errors="coerce").fillna(0)
    max_streak = pd.to_numeric(data.get("max_streak", 0), errors="coerce").fillna(0)
    broken_rate = pd.to_numeric(data.get("broken_rate", 0), errors="coerce").fillna(0) * 100
    if "emotion_score" in data.columns:
        score = pd.to_numeric(data["emotion_score"], errors="coerce").fillna(0)
    else:
        score = (
            (limit_count / max(limit_count.max(), 1) * 45)
            + (max_streak / max(max_streak.max(), 1) * 25)
            + (pd.to_numeric(data.get("strong_count", 0), errors="coerce").fillna(0) / max(pd.to_numeric(data.get("strong_count", 0), errors="coerce").fillna(0).max(), 1) * 20)
            - broken_rate * 0.18
            - down_count * 1.2
            + 12
        ).clip(0, 100)
    # Convert date to string format for categorical axis to naturally exclude non-trading days
    date_str = data["date"].dt.strftime("%m/%d")
    _add_glow_line(fig, x=date_str, y=score, name="情绪指数", color=RED, width=3.0, mode="lines+markers")
    _add_glow_line(fig, x=date_str, y=(limit_count / max(limit_count.max(), 1) * 100).clip(0, 100), name="涨停强度", color=PURPLE, width=2.2)
    _add_glow_line(fig, x=date_str, y=broken_rate.clip(0, 100), name="炸板率", color=ORANGE, width=2.2)
    _add_glow_line(fig, x=date_str, y=(down_count / max(down_count.max(), 1) * 100).clip(0, 100), name="冰点压力", color=BLUE, width=2.2)
    fig.add_hrect(y0=80, y1=100, fillcolor="rgba(255,92,122,0.08)", line_width=0)
    fig.add_hrect(y0=0, y1=20, fillcolor="rgba(91,140,255,0.10)", line_width=0)
    fig.update_yaxes(title="指数 (0-100)", range=[0, 100])
    fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    fig = _base_fig(fig, 430)
    fig.update_xaxes(type="category")
    return fig


def plot_market_sentiment_heatmap(heatmap: pd.DataFrame) -> go.Figure:
    data = heatmap.copy() if heatmap is not None else pd.DataFrame()
    fig = go.Figure()
    if data.empty:
        return _base_fig(fig, 430)
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.strftime("%m/%d")
    pivot = data.pivot_table(index="board_name", columns="date", values="heat", aggfunc="max", fill_value=0)
    raw = data.pivot_table(index="board_name", columns="date", values="raw_heat", aggfunc="max", fill_value=0).reindex(index=pivot.index, columns=pivot.columns, fill_value=0)
    limits = data.pivot_table(index="board_name", columns="date", values="limit_count", aggfunc="max", fill_value=0).reindex(index=pivot.index, columns=pivot.columns, fill_value=0)
    streaks = data.pivot_table(index="board_name", columns="date", values="max_streak", aggfunc="max", fill_value=0).reindex(index=pivot.index, columns=pivot.columns, fill_value=0)
    seal = data.pivot_table(index="board_name", columns="date", values="seal_fund", aggfunc="max", fill_value=0).reindex(index=pivot.index, columns=pivot.columns, fill_value=0)
    pivot = pivot.loc[pivot.max(axis=1).sort_values(ascending=False).index]
    raw = raw.reindex(index=pivot.index)
    limits = limits.reindex(index=pivot.index)
    streaks = streaks.reindex(index=pivot.index)
    seal = seal.reindex(index=pivot.index)
    custom = np.stack([raw.values, limits.values, streaks.values, seal.values], axis=-1)
    fig.add_trace(
        go.Heatmap(
            z=pivot.values,
            x=pivot.columns,
            y=pivot.index,
            customdata=custom,
            colorscale=[
                [0, "rgba(91,140,255,0.10)"],
                [0.35, "rgba(255,230,109,0.70)"],
                [0.7, "rgba(255,184,107,0.82)"],
                [1, "rgba(255,92,122,0.95)"],
            ],
            colorbar=dict(title="热度"),
            hovertemplate="%{y}<br>%{x}<br>归一化热度 %{z:.1f}<br>原始热度 %{customdata[0]:,.1f}<br>涨停 %{customdata[1]:.0f} 家<br>最高 %{customdata[2]:.0f} 板<br>封板资金 %{customdata[3]:,.0f}<extra></extra>",
        )
    )
    return _base_fig(fig, 470)


def plot_ice_point_month_stats(month_stats: pd.DataFrame) -> go.Figure:
    data = month_stats.copy() if month_stats is not None else pd.DataFrame()
    fig = go.Figure()
    if data.empty:
        return _base_fig(fig, 320)
    fig.add_trace(
        go.Bar(
            x=data["month"],
            y=data["ice_points"],
            name="冰点次数",
            marker=_bar_marker(BLUE, 0.72),
            hovertemplate="%{x}<br>冰点 %{y} 次<extra></extra>",
        )
    )
    fig.update_yaxes(title="次数", rangemode="tozero")
    return _base_fig(fig, 320)


def plot_limit_ecology(history: pd.DataFrame) -> go.Figure:
    data = history.tail(20).copy() if history is not None else pd.DataFrame()
    fig = go.Figure()
    if data.empty:
        return _base_fig(fig, 330)
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    missing = pd.to_numeric(data.get("history_missing", 0), errors="coerce").fillna(0)
    counts = (
        pd.to_numeric(data.get("limit_up_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(data.get("broken_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(data.get("limit_down_count", 0), errors="coerce").fillna(0)
    )
    data = data[(missing <= 0) & (counts > 0)].copy()
    if data.empty:
        return _base_fig(fig, 330)
    # Convert date to string format for categorical axis to naturally exclude non-trading days
    date_str = data["date"].dt.strftime("%m/%d")
    fig.add_trace(go.Bar(x=date_str, y=data.get("limit_up_count", 0), name="涨停", marker=_bar_marker(RED, 0.70)))
    fig.add_trace(go.Bar(x=date_str, y=data.get("broken_count", 0), name="炸板", marker=_bar_marker(ORANGE, 0.65)))
    fig.add_trace(go.Bar(x=date_str, y=data.get("limit_down_count", 0), name="跌停", marker=_bar_marker(GREEN, 0.60)))
    fig.update_layout(barmode="group", legend=dict(orientation="h"))
    fig.update_yaxes(title="家数")
    fig = _base_fig(fig, 340)
    fig.update_xaxes(type="category")
    return fig


def plot_recent_5d_emotion(history: pd.DataFrame) -> go.Figure:
    data = history.copy() if history is not None else pd.DataFrame()
    fig = go.Figure()
    if data.empty:
        return _base_fig(fig, 240)
    missing = pd.to_numeric(data.get("history_missing", 0), errors="coerce").fillna(0)
    counts = (
        pd.to_numeric(data.get("limit_up_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(data.get("broken_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(data.get("limit_down_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(data.get("strong_count", 0), errors="coerce").fillna(0)
    )
    data = data[(missing <= 0) & (counts > 0)].tail(5).copy()
    if data.empty:
        return _base_fig(fig, 240)
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.strftime("%m/%d")
    
    limit_count = pd.to_numeric(data.get("limit_up_count", 0), errors="coerce").fillna(0)
    max_streak = pd.to_numeric(data.get("max_streak", 0), errors="coerce").fillna(0)
    strong_count = pd.to_numeric(data.get("strong_count", 0), errors="coerce").fillna(0)
    broken_rate = pd.to_numeric(data.get("broken_rate", 0), errors="coerce").fillna(0) * 100
    down_count = pd.to_numeric(data.get("limit_down_count", 0), errors="coerce").fillna(0)
    
    if "emotion_score" in data.columns:
        emotion = pd.to_numeric(data["emotion_score"], errors="coerce").fillna(0)
    else:
        emotion = (
            (limit_count / max(limit_count.max(), 1) * 45)
            + (max_streak / max(max_streak.max(), 1) * 25)
            + (strong_count / max(strong_count.max(), 1) * 20)
            - broken_rate * 0.18
            - down_count * 1.2
            + 12
        ).clip(0, 100)
    
    _add_glow_line(fig, x=data["date"], y=emotion, name="综合评分", color=RED, width=2.4, mode="lines+markers")
    fig.update_yaxes(title="评分", range=[0, 100])
    fig.update_xaxes(nticks=5)
    return _base_fig(fig, 320)


def plot_recent_5d_limit_counts(history: pd.DataFrame) -> go.Figure:
    data = history.copy() if history is not None else pd.DataFrame()
    fig = go.Figure()
    if data.empty:
        return _base_fig(fig, 240)
    missing = pd.to_numeric(data.get("history_missing", 0), errors="coerce").fillna(0)
    counts = (
        pd.to_numeric(data.get("limit_up_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(data.get("broken_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(data.get("limit_down_count", 0), errors="coerce").fillna(0)
    )
    data = data[(missing <= 0) & (counts > 0)].tail(5).copy()
    if data.empty:
        return _base_fig(fig, 240)
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.strftime("%m/%d")
    limit_up = pd.to_numeric(data.get("limit_up_count", pd.Series(0, index=data.index)), errors="coerce").fillna(0)
    broken = pd.to_numeric(data.get("broken_count", pd.Series(0, index=data.index)), errors="coerce").fillna(0)
    limit_down = pd.to_numeric(data.get("limit_down_count", pd.Series(0, index=data.index)), errors="coerce").fillna(0)
    
    fig.add_trace(go.Bar(x=data["date"], y=limit_up, name="涨停", marker=_bar_marker(RED, 0.70)))
    fig.add_trace(go.Bar(x=data["date"], y=broken, name="炸板", marker=_bar_marker(ORANGE, 0.65)))
    fig.add_trace(go.Bar(x=data["date"], y=limit_down, name="跌停", marker=_bar_marker(GREEN, 0.60)))
    fig.update_layout(barmode="group", legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    fig.update_xaxes(nticks=5)
    return _base_fig(fig, 320)


def plot_recent_5d_amount(history: pd.DataFrame) -> go.Figure:
    data = history.copy() if history is not None else pd.DataFrame()
    fig = go.Figure()
    if data.empty:
        return _base_fig(fig, 320)
    missing = pd.to_numeric(data.get("history_missing", 0), errors="coerce").fillna(0)
    counts = (
        pd.to_numeric(data.get("limit_up_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(data.get("broken_count", 0), errors="coerce").fillna(0)
        + pd.to_numeric(data.get("limit_down_count", 0), errors="coerce").fillna(0)
    )
    data = data[(missing <= 0) & (counts > 0)].tail(5).copy()
    if data.empty:
        return _base_fig(fig, 320)
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.strftime("%m/%d")
    amount = pd.to_numeric(data.get("limit_amount", pd.Series(0, index=data.index)), errors="coerce").fillna(0)
    _add_glow_line(fig, x=data["date"], y=amount / 1_0000_0000, name="涨停成交额(亿)", color=CYAN, width=2.4, mode="lines+markers")
    fig.update_yaxes(title="亿元", rangemode="tozero")
    fig.update_xaxes(nticks=5)
    return _base_fig(fig, 320)


def plot_volume(df: pd.DataFrame) -> go.Figure:
    data = df.tail(120).copy()
    prev_close = data["close"].shift(1)
    colors = np.where(data["close"] >= prev_close, _rgba(GREEN, 0.70), _rgba(RED, 0.70))
    fig = go.Figure(
        go.Bar(
            x=data["date"],
            y=data.get("volume", pd.Series(index=data.index, data=0)),
            marker=dict(color=colors, line=dict(color="rgba(255,255,255,0.18)", width=0.8)),
            name="成交量",
            hovertemplate="%{x}<br>成交量 %{y:,.0f}<extra></extra>",
        )
    )
    return _apply_recent_x_window(_base_fig(fig, 460), data)


def plot_price_volume_scatter(df: pd.DataFrame) -> go.Figure:
    data = df.tail(120).copy()
    amount = data.get("amount_est")
    if amount is None:
        amount = data["close"] * data.get("volume", 0)
    size = np.clip((amount.fillna(0) / max(float(amount.fillna(0).max() or 1), 1)) * 34 + 8, 8, 42)
    colors = np.where(data.get("ret_1d", data["close"].pct_change()).fillna(0) >= 0, _rgba(GREEN, 0.72), _rgba(RED, 0.72))
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=data["close"],
            y=amount,
            mode="markers",
            marker=dict(size=size, color=colors, opacity=0.82, line=dict(color="rgba(245,247,250,0.34)", width=1.2)),
            text=data["date"].dt.strftime("%Y-%m-%d") if pd.api.types.is_datetime64_any_dtype(data["date"]) else data["date"].astype(str),
            name="交易日",
            hovertemplate="%{text}<br>收盘价 %{x:.2f}<br>成交额 %{y:,.0f}<extra></extra>",
        )
    )
    if len(data):
        latest = data.iloc[-1]
        latest_amount = float((latest.get("amount_est") if "amount_est" in data.columns else latest["close"] * latest.get("volume", 0)) or 0)
        fig.add_trace(
            go.Scatter(
                x=[latest["close"]],
                y=[latest_amount],
                mode="markers",
                marker=dict(size=24, color=_rgba(CYAN, 0.88), line=dict(color=TEXT, width=2.2), symbol="diamond"),
                name="最新",
                hovertemplate="最新<br>收盘价 %{x:.2f}<br>成交额 %{y:,.0f}<extra></extra>",
            )
        )
    fig.update_xaxes(title="收盘价")
    fig.update_yaxes(title="成交额")
    return _base_fig(fig, 430)


def plot_rsi(df: pd.DataFrame) -> go.Figure:
    data = df.tail(120).copy()
    fig = go.Figure()
    if "rsi14" in data.columns:
        _add_glow_line(fig, x=data["date"], y=data["rsi14"], name="RSI 14", color=ORANGE, width=2.8, hovertemplate="RSI 14<br>%{x}<br>%{y:.1f}<extra></extra>")
    fig.add_hrect(y0=70, y1=100, fillcolor="rgba(255,92,122,0.12)", line_width=0)
    fig.add_hrect(y0=0, y1=30, fillcolor="rgba(51,214,159,0.12)", line_width=0)
    fig.add_hline(y=70, line_dash="dot", line_color="rgba(255,92,122,0.55)")
    fig.add_hline(y=30, line_dash="dot", line_color="rgba(51,214,159,0.55)")
    fig.update_yaxes(range=[0, 100])
    return _apply_recent_x_window(_base_fig(fig, 430), data)


def plot_macd(df: pd.DataFrame) -> go.Figure:
    data = df.tail(120).copy()
    fig = go.Figure()
    if "macd_hist" in data.columns:
        colors = np.where(data["macd_hist"].fillna(0) >= 0, _rgba(GREEN, 0.68), _rgba(RED, 0.68))
        fig.add_trace(go.Bar(x=data["date"], y=data["macd_hist"], marker=dict(color=colors, line=dict(color="rgba(255,255,255,0.16)", width=0.7)), name="柱体"))
    if "macd_diff" in data.columns:
        _add_glow_line(fig, x=data["date"], y=data["macd_diff"], name="DIF", color=CYAN, width=2.4)
    if "macd_dea" in data.columns:
        _add_glow_line(fig, x=data["date"], y=data["macd_dea"], name="DEA", color=PURPLE, width=2.4)
    return _apply_recent_x_window(_base_fig(fig, 430), data)


def plot_kdj(df: pd.DataFrame) -> go.Figure:
    data = df.tail(120).copy()
    fig = go.Figure()
    for col, name, color in [("kdj_k", "K", CYAN), ("kdj_d", "D", PURPLE), ("kdj_j", "J", ORANGE)]:
        if col in data.columns:
            _add_glow_line(fig, x=data["date"], y=data[col], name=name, color=color, width=2.4)
    return _apply_recent_x_window(_base_fig(fig, 430), data)


def plot_score_breakdown(score_detail: dict, title: str = "评分拆解") -> go.Figure:
    labels = list(score_detail.keys()) or ["评分"]
    values = [float(score_detail.get(label, 0) or 0) for label in labels]
    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker=dict(
                color=values,
                colorscale=[[0, _rgba(RED, 0.82)], [0.5, _rgba(BLUE, 0.82)], [1, _rgba(GREEN, 0.82)]],
                line=dict(color=BAR_LINE, width=1.1),
            ),
            hovertemplate="%{y}<br>评分 %{x:.1f}<extra></extra>",
        )
    )
    fig.update_layout(title=dict(text=title, font=dict(size=15, color=TEXT)), yaxis=dict(autorange="reversed"))
    return _base_fig(fig, 330)


def _breakdown_frame(breakdown: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "dimension": item.get("dimension"),
            "score": float(item.get("score", 0) or 0),
            "max_score": float(item.get("max_score", 0) or 0),
            "score_rate": float(item.get("score_rate", 0) or 0),
        }
        for item in breakdown
    ])


def plot_explainable_bar(breakdown: list[dict], title: str = "评分维度") -> go.Figure:
    data = _breakdown_frame(breakdown)
    if data.empty:
        return _base_fig(go.Figure(), 340)
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=data["max_score"],
            y=data["dimension"],
            orientation="h",
            marker=dict(color="rgba(255,255,255,0.08)", line=dict(color="rgba(255,255,255,0.14)", width=1)),
            name="满分",
            hovertemplate="%{y}<br>满分 %{x:.1f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=data["score"],
            y=data["dimension"],
            orientation="h",
            marker=dict(color=data["score_rate"], colorscale=[[0, _rgba(RED, 0.88)], [0.55, _rgba(BLUE, 0.88)], [1, _rgba(GREEN, 0.88)]], line=dict(color=BAR_LINE, width=1.1)),
            name="当前得分",
            hovertemplate="%{y}<br>得分 %{x:.1f}<extra></extra>",
        )
    )
    fig.update_layout(title=dict(text=title, font=dict(size=15, color=TEXT)), barmode="overlay", yaxis=dict(autorange="reversed"))
    return _base_fig(fig, 350)


def plot_score_radar(breakdown: list[dict], title: str = "得分率雷达") -> go.Figure:
    data = _breakdown_frame(breakdown)
    if data.empty:
        return _base_fig(go.Figure(), 340)
    labels = data["dimension"].tolist()
    values = (data["score_rate"] * 100).round(1).tolist()
    labels.append(labels[0])
    values.append(values[0])
    fig = go.Figure(
        go.Scatterpolar(
            r=values,
            theta=labels,
            fill="toself",
            name="得分率",
            line=dict(color=CYAN, width=2.8),
            fillcolor="rgba(55,232,255,0.20)",
            hovertemplate="%{theta}<br>得分率 %{r:.1f}%<extra></extra>",
        )
    )
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=TEXT)),
        polar=dict(
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(range=[0, 100], gridcolor=GRID, color=MUTED),
            angularaxis=dict(gridcolor=GRID, color=MUTED),
        ),
        showlegend=False,
    )
    return _base_fig(fig, 360)


def plot_score_waterfall(breakdown: list[dict], title: str = "贡献度瀑布图") -> go.Figure:
    data = _breakdown_frame(breakdown)
    if data.empty:
        return _base_fig(go.Figure(), 340)
    fig = go.Figure(
        go.Waterfall(
            name="贡献",
            orientation="v",
            measure=["relative"] * len(data) + ["total"],
            x=data["dimension"].tolist() + ["总分"],
            y=data["score"].tolist() + [0],
            connector={"line": {"color": "rgba(255,255,255,0.28)", "width": 1}},
            increasing={"marker": {"color": _rgba(GREEN, 0.76), "line": {"color": GREEN, "width": 1}}},
            decreasing={"marker": {"color": _rgba(RED, 0.76), "line": {"color": RED, "width": 1}}},
            totals={"marker": {"color": _rgba(CYAN, 0.82), "line": {"color": CYAN, "width": 1.2}}},
            hovertemplate="%{x}<br>%{y:.1f}<extra></extra>",
        )
    )
    fig.update_layout(title=dict(text=title, font=dict(size=15, color=TEXT)))
    return _base_fig(fig, 360)


def plot_risk_deductions(breakdown: list[dict], title: str = "风险扣分 / 缺口") -> go.Figure:
    rows = []
    for item in breakdown:
        gap = float(item.get("max_score", 0) or 0) - float(item.get("score", 0) or 0)
        if gap > 0:
            rows.append({"dimension": item.get("dimension"), "gap": gap})
    data = pd.DataFrame(rows)
    if data.empty:
        data = pd.DataFrame([{"dimension": "暂无明显扣分", "gap": 0}])
    fig = go.Figure(
        go.Bar(
            x=data["gap"],
            y=data["dimension"],
            orientation="h",
            marker=dict(color=_rgba(ORANGE, 0.75), line=dict(color=_rgba(ORANGE, 0.98), width=1.1)),
            hovertemplate="%{y}<br>扣分/缺口 %{x:.1f}<extra></extra>",
        )
    )
    fig.update_layout(title=dict(text=title, font=dict(size=15, color=TEXT)), yaxis=dict(autorange="reversed"))
    return _base_fig(fig, 360)


def format_evidence_value(key: str, value) -> str:
    if value is None or value == "":
        return "暂未获取"
    if isinstance(value, str):
        return value
    if key in {"return_1d", "return_5d", "return_20d", "return_60d", "return_120d", "distance_to_20d_high", "distance_to_ma20", "volatility_60d", "max_drawdown_60d", "amplitude", "roe", "roa", "dividend_yield", "dcf_discount_pct", "top_board_pct", "avg_top3_board_pct"}:
        return format_percent(value)
    if key in {"volume", "volume_ma5", "volume_ma20", "amount_est", "amount_avg_20d"}:
        return format_number_cn(value)
    if key in {"history_days"}:
        return f"{int(value)}"
    return format_price(value, 2)


def render_evidence_table(evidence: dict) -> None:
    labels = {
        "close": "最新收盘价",
        "open": "开盘价",
        "high": "最高价",
        "low": "最低价",
        "ma5": "MA5",
        "ma10": "MA10",
        "ma20": "MA20",
        "ma60": "MA60",
        "ma120": "MA120",
        "ma250": "MA250",
        "return_1d": "当日涨跌幅",
        "return_5d": "近5日涨跌幅",
        "return_20d": "近20日涨跌幅",
        "return_60d": "近60日涨跌幅",
        "return_120d": "近120日涨跌幅",
        "volume": "成交量",
        "volume_ma5": "5日均量",
        "volume_ma20": "20日均量",
        "volume_ratio_5": "5日量比",
        "volume_ratio_20": "20日量比",
        "amount_est": "估算成交额",
        "amount_avg_20d": "20日平均成交额",
        "turnover_rate": "换手率",
        "rsi14": "RSI14",
        "macd_diff": "MACD DIF",
        "macd_dea": "MACD DEA",
        "macd_hist": "MACD 柱体",
        "kdj_k": "KDJ K",
        "kdj_d": "KDJ D",
        "kdj_j": "KDJ J",
        "high_20d": "近20日最高价",
        "distance_to_20d_high": "距20日高点",
        "distance_to_ma20": "距MA20偏离",
        "volatility_60d": "60日波动率",
        "max_drawdown_60d": "60日最大回撤",
        "history_days": "历史样本天数",
        "industry": "行业",
        "industry_cn": "中文行业/主板块",
        "sector": "海外行业分类",
        "belong_boards": "所属板块/概念",
        "top_board": "最强所属板块",
        "top_board_pct": "最强板块涨幅",
        "avg_top3_board_pct": "前三板块均涨幅",
        "positive_board_count": "上涨板块数",
        "board_net_flow_sum": "匹配板块资金净额",
    }
    rows = [
        {"指标": label, "数值": format_evidence_value(key, evidence.get(key))}
        for key, label in labels.items()
        if key in evidence
    ]
    render_glass_dataframe(pd.DataFrame(rows), height=420)


def render_dimension_cards(breakdown: list[dict], namespace: str = "score") -> None:
    for idx, item in enumerate(breakdown):
        title = f"{item.get('dimension', '-')}: {format_price(item.get('score'), 1)} / {format_price(item.get('max_score'), 0)}"
        with st.expander(title, expanded=idx == 0):
            rate = float(item.get("score_rate", 0) or 0)
            if rate >= 0.78:
                stance = "该维度当前是明显贡献项，可以提高研究优先级，但仍要和风险项一起看。"
            elif rate >= 0.55:
                stance = "该维度提供中等支撑，结论偏观察，需要等待其他维度共振。"
            elif rate >= 0.35:
                stance = "该维度贡献有限，暂时不适合作为主要买点依据。"
            else:
                stance = "该维度是当前拖累项，需要优先排查数据背后的风险。"
            positives = [str(x) for x in item.get("positive_factors", []) if x]
            negatives = [str(x) for x in item.get("negative_factors", []) if x]
            driver = positives[0] if positives else "暂无明确正向驱动"
            drag = negatives[0] if negatives else "暂无显著扣分项"
            st.markdown(f"**本轮结论：** {stance} 关键驱动是：{driver}；主要约束是：{drag}")
            st.markdown(f"**评分逻辑：** {item.get('logic', '-')}")
            st.markdown(f"**权重：** {float(item.get('weight', 0) or 0):.0%}　**得分率：** {float(item.get('score_rate', 0) or 0):.1%}")
            st.markdown("**关键数据：**")
            data_points = item.get("data_points", {}) or {}
            rows = [{"数据项": key, "当前值": format_evidence_value(key, value)} for key, value in data_points.items()]
            render_glass_dataframe(pd.DataFrame(rows), height=min(260, 44 + 36 * max(1, len(rows))))
            col_pos, col_neg = st.columns(2)
            with col_pos:
                st.markdown("**加分项**")
                for factor in item.get("positive_factors", []):
                    st.markdown(f"- {factor}")
            with col_neg:
                st.markdown("**扣分项 / 限制**")
                for factor in item.get("negative_factors", []):
                    st.markdown(f"- {factor}")
            st.info(item.get("decision_impact", "-"))


def format_ratio(value, digits: int = 2) -> str:
    value = _safe(value, None)
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.{digits}f}x"
    except Exception:
        return str(value)


def format_na(value, formatter=None) -> str:
    value = _safe(value, None)
    if value is None or value == "":
        return "暂未获取"
    if formatter:
        return formatter(value)
    return str(value)


def render_company_profile(profile: dict, summary: str = "") -> None:
    left_badges = [
        ("市场", profile.get("market")),
        ("行业", profile.get("industry_cn") or profile.get("industry")),
    ]
    badges_html = "".join(
        f'<span class="pill pill-cyan">{escape(label)} · {escape(str(value or "暂未获取"))}</span>'
        for label, value in left_badges
    )
    # Format list date if it's in YYYYMMDD string format
    list_date = profile.get("list_date") or ""
    s_date = str(list_date)
    if len(s_date) == 8 and s_date.isdigit():
        list_date = f"{s_date[:4]}-{s_date[4:6]}-{s_date[6:]}"

    kv = [
        ("交易所", profile.get("exchange")),
        ("上市时间", list_date),
        ("总市值", format_number_cn(profile.get("market_cap")) if profile.get("market_cap") else "暂未获取"),
        ("流通市值", format_number_cn(profile.get("float_market_cap")) if profile.get("float_market_cap") else "暂未获取"),
        ("总股本", format_number_cn(profile.get("shares_outstanding")) if profile.get("shares_outstanding") else "暂未获取"),
        ("流通股本", format_number_cn(profile.get("float_shares")) if profile.get("float_shares") else "暂未获取"),
        ("最新收盘价", format_price(profile.get("latest_price")) if profile.get("latest_price") else "暂未获取"),
        ("数据更新", profile.get("updated_at")),
        ("员工数", format_number_cn(profile.get("employees"), 0) if profile.get("employees") else "暂未获取"),
        ("海外行业分类", profile.get("sector")),
    ]
    kv_html = "".join(
        f'<div class="profile-kv"><span>{escape(label)}</span><strong>{escape(str(value or "暂未获取"))}</strong></div>'
        for label, value in kv
    )
    business = profile.get("business") or "暂未获取"
    # Prioritise the passed summary (which should be the translated/curated business intro)
    display_summary = summary or str(business)
    if len(str(display_summary)) > 1200:
        display_summary = str(display_summary)[:1200] + "..."

    html = f"""
    <div class="profile-card">
      <div class="profile-main">
        <div class="eyebrow">公司画像</div>
        <h3>{escape(str(profile.get("name") or profile.get("code") or "-"))}</h3>
        <div class="profile-code">{escape(str(profile.get("code") or "-"))} · {escape(str(profile.get("yahoo_code") or "-"))}</div>
        <div class="profile-badges">{badges_html}</div>
        <div class="profile-summary-text">{escape(display_summary)}</div>
      </div>
      <div class="profile-kv-grid">{kv_html}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)
    boards = profile.get("belong_boards") or []
    if boards:
        st.caption("所属板块 / 概念：" + "、".join(map(str, boards[:8])))


def render_valuation_metric_cards(metrics: dict) -> None:
    def money_or_na(value):
        return "N/A" if _safe(value, None) is None else format_number_cn(value)

    def percent_or_na(value):
        return "N/A" if _safe(value, None) is None else format_percent(value)

    def status(value, metric):
        if value is None:
            return "数据不足", "orange", "数据不足"
        try:
            num = float(value)
        except Exception:
            return "数据异常", "cyan", "数据异常"
        if metric == "market_cap":
            if num >= 1000_0000_0000:
                return "大市值", "green", "大市值"
            if num >= 100_0000_0000:
                return "中大市值", "cyan", "中大市值"
            return "中小市值", "orange", "中小市值"
        if metric == "pe":
            if 0 < num <= 15:
                return "极具吸引力", "green", "极低估值"
            if 15 < num <= 28:
                return "合理偏低", "green", "合理偏低"
            if 28 < num <= 45:
                return "合理偏高", "cyan", "合理偏高"
            if 45 < num <= 60:
                return "估值偏贵", "orange", "估值偏贵"
            return "估值高压" if num > 0 else "亏损异常", "red", "估值高压" if num > 0 else "亏损异常"
        if metric == "pb":
            if 0 < num <= 1.5:
                return "极具吸引力", "green", "极低PB"
            if 1.5 < num <= 3.2:
                return "合理区间", "green", "合理PB"
            if 3.2 < num <= 5.0:
                return "估值中等", "cyan", "合理偏高"
            return "估值偏贵", "orange", "估值偏贵"
        if metric == "ps":
            if 0 < num <= 1.5:
                return "低估吸引力", "green", "低估吸引"
            if 1.5 < num <= 3.5:
                return "估值合理", "green", "估值合理"
            if 3.5 < num <= 6.0:
                return "估值中等", "cyan", "合理偏高"
            return "估值偏贵", "orange", "估值偏贵"
        if metric == "dy":
            if num >= 0.05:
                return "高股息率", "green", "高股息率"
            if num >= 0.03:
                return "股息优秀", "green", "股息优秀"
            if num >= 0.015:
                return "分红适中", "cyan", "分红适中"
            return "低分红率", "orange", "低分红率"
        if metric == "roe":
            if num >= 0.20:
                return "超强盈利", "green", "超强盈利"
            if num >= 0.12:
                return "盈利优秀", "green", "盈利优秀"
            if num >= 0.07:
                return "盈利适中", "cyan", "盈利适中"
            return "盈利偏弱", "orange", "盈利偏弱"
        if metric == "roa":
            if num >= 0.10:
                return "高资产回报", "green", "资产高效"
            if num >= 0.06:
                return "回报优秀", "green", "回报优秀"
            if num >= 0.03:
                return "回报适中", "cyan", "回报适中"
            return "回报偏弱", "orange", "回报偏弱"
        if metric == "de":
            if num < 0.6:
                return "轻资产/无债", "green", "无债健康"
            if num < 1.2:
                return "杠杆健康", "green", "杠杆健康"
            if num < 2.0:
                return "杠杆适中", "cyan", "杠杆适中"
            return "债务偏高", "orange", "债务偏高"
        return "中性", "cyan", "中性"

    def metric_note(label, raw, key, base_note, status_label):
        if raw is None:
            return f"{base_note} · 暂缺该项，结论降权"
        try:
            num = float(raw)
        except Exception:
            return f"{base_note} · {status_label}"
        if key == "pe":
            if num <= 0:
                return "盈利口径为负或异常，PE 暂不适合单独判断"
            if num <= 25:
                return "盈利定价不算激进，继续看增长和行业分位"
            if num <= 45:
                return "估值需要业绩兑现支撑，追高容错变低"
            return "PE 已偏高，短线催化强度要足以覆盖估值压力"
        if key == "pb":
            if num <= 1:
                return "账面估值偏低，需确认资产质量和盈利弹性"
            if num <= 3:
                return "PB 处于可解释区间，关键看 ROE 能否匹配"
            return "PB 偏高，若 ROE 不强则估值性价比下降"
        if key == "ps":
            if num <= 2:
                return "收入估值较克制，适合继续核对毛利和利润率"
            if num <= 6:
                return "收入估值中性，需看收入增速能否延续"
            return "收入估值偏高，增长放缓时回撤弹性会放大"
        if key == "dy":
            if num >= 0.04:
                return "股息提供一定安全垫，更适合耐心跟踪"
            if num >= 0.015:
                return "分红贡献中等，主要回报仍取决于价格和业绩"
            return "股息保护较弱，研究重点应放在增长 and 趋势"
        if key == "roe":
            if num >= 0.15:
                return "ROE 较强，说明权益资本回报对估值有支撑"
            if num >= 0.08:
                return "ROE 中等，需要结合 PB 判断是否匹配"
            return "ROE 偏弱，中长期吸引力需要其他优势补足"
        if key == "roa":
            if num >= 0.07:
                return "ROA 较强，资产使用效率对质量评分有贡献"
            if num >= 0.03:
                return "ROA 中性，质量结论还要看杠杆 and 现金流"
            return "ROA 偏弱，说明资产盈利效率仍需验证"
        if key == "de":
            if num < 1:
                return "杠杆压力较轻，基本面风险项相对温和"
            if num <= 2:
                return "杠杆中等，需继续看现金流覆盖能力"
            return "杠杆偏高，中长期结论必须加入风控折扣"
        return f"{base_note} · {status_label}"

    specs = [
        ("市值", money_or_na(metrics.get("market_cap")), "总市值", "market_cap", "cyan"),
        ("PE TTM", format_ratio(metrics.get("pe_ttm")), "市盈率，盈利为正时更有解释力", "pe", None),
        ("PB", format_ratio(metrics.get("pb")), "市净率，需结合 ROE", "pb", None),
        ("PS", format_ratio(metrics.get("ps")), "市销率，适合收入型比较", "ps", "blue"),
        ("股息率", percent_or_na(metrics.get("dividend_yield")), "现金分红收益率", "dy", "purple"),
        ("ROE", percent_or_na(metrics.get("roe")), "净利润 / 股东权益", "roe", None),
        ("ROA", percent_or_na(metrics.get("roa")), "净利润 / 总资产", "roa", None),
        ("D/E", format_ratio(metrics.get("debt_to_equity")), "总负债 / 股东权益代理", "de", None),
    ]
    cards = []
    for label, value, note, key, forced_tone in specs:
        raw_map = {"pe": "pe_ttm", "pb": "pb", "roe": "roe", "roa": "roa", "de": "debt_to_equity", "ps": "ps", "dy": "dividend_yield"}
        raw = metrics.get(raw_map.get(key, key))
        status_label, tone, indicator_label = status(raw, key)
        if forced_tone:
            tone = forced_tone
        cards.append(metric_card(label, value, metric_note(label, raw, key, note, status_label), tone, indicator_label))
    render_bento_grid(cards)


def plot_ratings_snapshot(ratings: dict, height: int = 530) -> go.Figure:
    scores = ratings.get("scores", {}) if ratings else {}
    usable = {key: value for key, value in scores.items() if key != "DCF" and value is not None}
    if not usable:
        return _base_fig(go.Figure(), height)
    
    translation_map = {
        "ROE": "ROE",
        "ROA": "ROA",
        "D/E": "D/E",
        "P/E": "P/E",
        "P/B": "P/B",
        "P/S": "P/S",
        "Gross Margin": "毛利率",
        "Net Margin": "净利率",
        "Debt Ratio": "资产负债率",
        "Cashflow Quality": "现金流质量",
        "Dividend Yield": "股息率",
        "Revenue Growth": "收入增长",
        "Net Profit Growth": "净利润增长",
    }
    
    labels = [translation_map.get(key, key) for key in usable.keys()]
    values = [float(v) for v in usable.values()]
    labels.append(labels[0])
    values.append(values[0])
    fig = go.Figure(
        go.Scatterpolar(
            r=values,
            theta=labels,
            fill="toself",
            name="评级",
            line=dict(color=CYAN, width=2.8),
            marker=dict(size=7, color=CYAN, line=dict(color="rgba(255,255,255,0.30)", width=1)),
            fillcolor="rgba(55,232,255,0.20)",
            hovertemplate="%{theta}<br>评分 %{r:.1f} / 5<extra></extra>",
        )
    )
    fig.update_layout(
        polar=dict(
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(range=[0, 5], tickvals=[1, 2, 3, 4, 5], gridcolor=GRID, color=MUTED),
            angularaxis=dict(gridcolor=GRID, color=MUTED),
        ),
        showlegend=False,
    )
    return _base_fig(fig, height)


def _rating_basis_sentence(key: str, score: float | None, metrics: dict) -> str:
    if score is None:
        return "暂无可比数据，本项不进入综合评分。"
    level = "高" if score >= 4 else "中等" if score >= 3 else "偏低"
    ref_map = {
        "ROE": f"参考 ROE={format_percent_or_na(metrics.get('roe'))}，盈利能力越强得分越高。",
        "ROA": f"参考 ROA={format_percent_or_na(metrics.get('roa'))}，资产使用效率越强得分越高。",
        "D/E": f"参考 D/E={format_ratio(metrics.get('debt_to_equity'))}，杠杆越低、财务弹性越好得分越高。",
        "P/E": f"参考 PE TTM={format_ratio(metrics.get('pe_ttm'))}，盈利估值压力越可解释得分越高。",
        "P/B": f"参考 PB={format_ratio(metrics.get('pb'))}，需结合 ROE 判断资产估值是否合理。",
        "P/S": f"参考 PS={format_ratio(metrics.get('ps'))}，收入估值越克制且增长可验证得分越高。",
        "Dividend Yield": f"参考股息率={format_percent_or_na(metrics.get('dividend_yield'))}，现金分红保护越强得分越高。",
        "Revenue Growth": f"参考最近可比营收增长，增长越稳定得分越高。",
        "Net Profit Growth": f"参考最近可比净利润增长，利润兑现越好得分越高。",
    }
    return f"本项评分{level}：{ref_map.get(key, '参考可得财务与估值数据进行 1-5 分映射。')}"


def render_ratings_list(ratings: dict, metrics: dict | None = None) -> None:
    metrics = metrics or {}
    scores = ratings.get("scores", {}) if ratings else {}
    label_map = {
        "ROE": "净资产收益率",
        "ROA": "总资产收益率",
        "D/E": "债务权益比",
        "P/E": "市盈率",
        "P/B": "市净率",
        "P/S": "市销率",
        "Dividend Yield": "股息率",
        "Revenue Growth": "收入增长",
        "Net Profit Growth": "净利润增长",
    }
    rows = []
    for key, label in label_map.items():
        value = scores.get(key)
        value_text = "N/A" if value is None else f"{float(value):.1f}"
        reason = _rating_basis_sentence(key, None if value is None else float(value), metrics)
        row_class = "rating-row muted" if value is None else "rating-row"
        rows.append(
            f'<details class="{row_class}">'
            f'<summary><span>{escape(label)}</span><strong>{escape(value_text)}</strong></summary>'
            f'<p>{escape(reason)}</p>'
            f'</details>'
        )
    overall = ratings.get("overall")
    rating = ratings.get("rating", "数据受限")
    html = (
        '<div class="rating-list">'
        + "".join(rows)
        + f'<div class="rating-overall"><span>综合评分</span><strong>{escape("N/A" if overall is None else f"{overall:.1f}")}</strong><em>{escape(str(rating))}</em></div>'
        + "</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


def _financial_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    view = df.copy()
    rename = {
        "period": "报告期",
        "totalRevenue": "营业收入",
        "grossProfit": "毛利润",
        "netIncome": "净利润",
        "deductedNetIncome": "扣非净利润",
        "operatingCashFlow": "经营现金流",
        "freeCashFlow": "自由现金流",
        "totalAssets": "总资产",
        "totalLiab": "总负债",
        "totalStockholderEquity": "股东权益",
        "grossMargin": "毛利率",
        "netMargin": "净利率",
        "roe": "ROE",
        "roa": "ROA",
        "debtToEquity": "D/E",
        "eps": "EPS",
        "bvps": "BVPS",
        "dividend": "分红金额",
        "dividendYield": "股息率",
    }
    keep = [col for col in rename if col in view.columns]
    view = view[keep].rename(columns=rename)
    for col in ["营业收入", "毛利润", "净利润", "扣非净利润", "经营现金流", "自由现金流", "总资产", "总负债", "股东权益", "分红金额"]:
        if col in view.columns:
            view[col] = view[col].map(lambda x: format_number_cn(x))
    for col in ["毛利率", "净利率", "ROE", "ROA", "股息率"]:
        if col in view.columns:
            view[col] = view[col].map(lambda x: format_percent(x))
    for col in ["D/E", "EPS", "BVPS"]:
        if col in view.columns:
            view[col] = view[col].map(lambda x: format_price(x))
    return view


def render_financial_table(df: pd.DataFrame) -> None:
    view = _financial_frame(df)
    if view.empty:
        st.info("暂未取得可展示的财务表。")
        return
    with st.expander("完整财务表", expanded=False):
        render_glass_dataframe(view)


def _period_values(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    data = df.copy()
    if "period" in data.columns:
        data["period"] = pd.to_datetime(data["period"], errors="coerce")
        data = data.sort_values("period")
    return data


def plot_financial_revenue_profit(df: pd.DataFrame) -> go.Figure:
    data = _period_values(df)
    fig = go.Figure()
    if data.empty:
        return _base_fig(fig, 340)
    if "totalRevenue" in data.columns:
        fig.add_trace(go.Bar(x=data["period"], y=data["totalRevenue"], name="营业收入", marker=_bar_marker(BLUE, 0.62), hovertemplate="%{x|%Y-%m-%d}<br>营业收入 %{y:,.0f}<extra></extra>"))
    if "netIncome" in data.columns:
        _add_glow_line(fig, x=data["period"], y=data["netIncome"], name="净利润", color=GREEN, width=2.8, mode="lines+markers", hovertemplate="%{x|%Y-%m-%d}<br>净利润 %{y:,.0f}<extra></extra>")
    fig.update_yaxes(title="金额")
    return _base_fig(fig, 350)


def plot_profitability(df: pd.DataFrame) -> go.Figure:
    data = _period_values(df)
    fig = go.Figure()
    for col, name, color in [("roe", "ROE", CYAN), ("roa", "ROA", PURPLE), ("grossMargin", "毛利率", GREEN), ("netMargin", "净利率", ORANGE)]:
        if col in data.columns and data[col].notna().any():
            _add_glow_line(fig, x=data["period"], y=data[col] * 100, name=name, color=color, width=2.6, mode="lines+markers", hovertemplate=f"{name}<br>%{{x|%Y-%m-%d}}<br>%{{y:.2f}}%<extra></extra>")
    fig.update_yaxes(title="%")
    return _base_fig(fig, 350)


def plot_cashflow_vs_profit(df: pd.DataFrame) -> go.Figure:
    data = _period_values(df)
    fig = go.Figure()
    if data.empty:
        return _base_fig(fig, 340)
    if "operatingCashFlow" in data.columns:
        fig.add_trace(go.Bar(x=data["period"], y=data["operatingCashFlow"], name="经营现金流", marker=_bar_marker(CYAN, 0.62), hovertemplate="%{x|%Y-%m-%d}<br>经营现金流 %{y:,.0f}<extra></extra>"))
    if "netIncome" in data.columns:
        fig.add_trace(go.Bar(x=data["period"], y=data["netIncome"], name="净利润", marker=_bar_marker(GREEN, 0.58), hovertemplate="%{x|%Y-%m-%d}<br>净利润 %{y:,.0f}<extra></extra>"))
    fig.update_layout(barmode="group")
    return _base_fig(fig, 350)


def _render_metric_explanations(metrics: dict) -> None:
    rows = metrics.get("explanations", []) or []
    with st.expander("核心指标的数据依据与公式", expanded=False):
        if not rows:
            st.info("当前未生成指标解释。")
            return
        view = pd.DataFrame(rows)
        if "当前值" in view.columns:
            view["当前值"] = view["当前值"].map(lambda x: format_percent(x) if isinstance(x, float) and abs(x) <= 1 else format_price(x, 2) if _sent_num(x) is not None else "-")
        render_glass_dataframe(view, height=min(520, 64 + len(view) * 70))


def _render_emotion_cycle_position(metrics: dict) -> None:
    period = metrics.get("period", "周期待确认")
    phases = ["退潮", "冰点", "常态", "启动", "发酵", "高潮"]
    
    html = '<div class="sentiment-cycle-timeline" style="display:flex; justify-content:space-between; align-items:center; margin: 16px 0 24px; position:relative;">\n'
    html += '<div style="position:absolute; top:50%; left:5%; right:5%; height:2px; background:rgba(255,255,255,0.1); z-index:0;"></div>\n'
    
    for phase in phases:
        is_active = (phase == period)
        color = "var(--accent-red)" if is_active else "rgba(255,255,255,0.3)"
        bg = "rgba(255,92,122,0.2)" if is_active else "rgba(255,255,255,0.05)"
        border = f"2px solid {color}" if is_active else f"1px solid {color}"
        weight = "900" if is_active else "500"
        shadow = "0 0 16px rgba(255,92,122,0.4)" if is_active else "none"
        
        html += f'<div style="display:flex; flex-direction:column; align-items:center; z-index:1; gap:8px;">\n'
        html += f'<div style="width:16px; height:16px; border-radius:50%; background:{bg}; border:{border}; box-shadow:{shadow};"></div>\n'
        html += f'<span style="color:{color}; font-size:0.85rem; font-weight:{weight};">{phase}</span>\n'
        html += f'</div>\n'
    html += '</div>\n'
    
    # 4 small metrics with explicit reference bands.
    short = metrics.get("short_emotion") or 0
    big = metrics.get("big_market_factor") or 0
    div = abs(short - big)
    broken_rate = (metrics.get("broken_rate") or 0) * 100
    limit = metrics.get("limit_up_count", 0)
    down = metrics.get("limit_down_count", 0)
    broken = metrics.get("broken_count", 0)
    amount_yi = (metrics.get("market_amount") or 0) / 100000000

    def mini_card(label: str, value: str, note: str, width: float, tone: str) -> str:
        safe_width = max(0, min(100, width))
        return (
            f'<div class="mini-metric sentiment-mini {tone}">'
            f'<span>{label}</span>'
            f'<strong>{value}</strong>'
            f'<div class="sentiment-strength {tone}"><i style="width:{safe_width:.1f}%"></i></div>'
            f'<small>{note}</small>'
            f'</div>\n'
        )
    
    html += '<div class="sentiment-cycle-metrics">\n'
    div_tone = "danger" if div >= 25 else "warning" if div >= 14 else "watch"
    html += mini_card("大小盘分歧", format_price(div, 1), f"超短 {format_price(short, 1)} / 宽度 {format_price(big, 1)}，低于 14 更顺。", min(div / 30 * 100, 100), div_tone)
    broken_tone = "danger" if broken_rate >= 35 else "warning" if broken_rate >= 25 else "watch"
    html += mini_card("炸板压力", f"{format_price(broken_rate, 1)}%", f"炸板 {int(broken or 0)} 家，25% 以上代表分歧抬升。", min(broken_rate / 40 * 100, 100), broken_tone)
    eco_tone = "good" if limit >= 60 and down <= 5 else "warning" if down >= 8 else "watch"
    html += mini_card("涨跌停生态", f"{_fmt_count(limit)} / {_fmt_count(down)}", "涨停 / 跌停，观察赚钱效应是否扩散。", min((limit or 0) / 90 * 100, 100), eco_tone)
    amount_tone = "good" if amount_yi >= 10000 else "watch" if amount_yi >= 7000 else "cool"
    html += mini_card("两市成交额", f"{format_price(amount_yi, 0)}亿", "万亿以上更利于主线持续，缩量时降低预期。", min(amount_yi / 12000 * 100, 100), amount_tone)
    
    html += '</div>\n'
    
    st.markdown(html, unsafe_allow_html=True)


def plot_score_distribution(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for col, name, color in [("short_score", "短线", CYAN), ("long_score", "中长线", PURPLE)]:
        if col in df.columns:
            fig.add_trace(go.Histogram(x=df[col], name=name, opacity=0.70, marker=_bar_marker(color, 0.64), nbinsx=16))
    fig.update_layout(barmode="overlay")
    return _base_fig(fig, 340)


def plot_score_scatter(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if {"short_score", "long_score"}.issubset(df.columns):
        fig.add_trace(
            go.Scatter(
                x=df["short_score"],
                y=df["long_score"],
                mode="markers+text",
                text=df.get("code", pd.Series([""] * len(df))),
                textposition="top center",
                marker=dict(size=15, color=df.get("composite_score", df["short_score"]), colorscale=[[0, RED], [0.55, BLUE], [1, GREEN]], opacity=0.88, line=dict(color="rgba(245,247,250,0.34)", width=1.2)),
                hovertext=df.get("name", ""),
                hovertemplate="%{hovertext}<br>短线 %{x:.1f}<br>中长线 %{y:.1f}<extra></extra>",
            )
        )
    fig.update_xaxes(title="短线评分", range=[0, 100])
    fig.update_yaxes(title="中长线评分", range=[0, 100])
    return _base_fig(fig, 340)


def _prepare_recent_table(df: pd.DataFrame, rows: int = 10) -> pd.DataFrame:
    view = df.tail(rows).sort_values("date", ascending=False).copy()
    if "amount_est" not in view.columns and {"close", "volume"}.issubset(view.columns):
        view["amount_est"] = view["close"] * view["volume"]
    if "date" in view.columns:
        view["date"] = pd.to_datetime(view["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    rename = {
        "date": "日期",
        "open": "开盘",
        "high": "最高",
        "low": "最低",
        "close": "收盘",
        "adj_close": "复权收盘",
        "volume": "成交量",
        "amount_est": "估算成交额",
        "amount": "成交额",
        "turnover_rate": "换手率",
        "yahoo_code": "Yahoo代码",
    }
    keep = [col for col in ["date", "open", "high", "low", "close", "adj_close", "volume", "amount_est", "amount", "turnover_rate"] if col in view.columns]
    view = view[keep].rename(columns=rename)
    for col in ["开盘", "最高", "最低", "收盘", "复权收盘", "换手率"]:
        if col in view.columns:
            view[col] = view[col].map(lambda x: format_price(x))
    for col in ["成交量", "估算成交额", "成交额"]:
        if col in view.columns:
            view[col] = view[col].map(lambda x: format_number_cn(x))
    return view


def render_recent_data_table(df: pd.DataFrame, rows: int = 10) -> None:
    view = _prepare_recent_table(df, rows)
    render_glass_dataframe(view, height=min(420, 44 + len(view) * 38))
    with st.expander("Raw Data", expanded=False):
        render_glass_dataframe(df.sort_values("date", ascending=False))
