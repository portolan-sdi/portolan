"use client";

import { useEffect, useRef, useState } from "react";
import {
  Scene,
  OrthographicCamera,
  WebGLRenderer,
  PlaneGeometry,
  MeshBasicMaterial,
  Mesh,
  TextureLoader,
  RepeatWrapping,
  Vector2,
  LinearFilter,
  Color,
} from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { ShaderPass } from "three/examples/jsm/postprocessing/ShaderPass.js";
import { DitherShader } from "./dither-shader";

interface DitherMapCanvasProps {
  className?: string;
  panSpeed?: number;
}

// Monochrome dither: a quiet textural backdrop, not a colored feature. Warm
// near-black on cream (light) and warm near-white on the warm-dark bg (dark).
const LIGHT_MODE_COLOR = new Color(0x2c2b22);
const DARK_MODE_COLOR = new Color(0xdcdacd);

export default function DitherMapCanvas({
  className = "",
  panSpeed = 0.00008,
}: DitherMapCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;

    let disposed = false;
    let animFrameId: number;

    const prefersReducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;

    const rect = container.getBoundingClientRect();
    let width = rect.width || window.innerWidth;
    let height = rect.height || window.innerHeight;

    if (width === 0 || height === 0) {
      width = window.innerWidth;
      height = window.innerHeight * 0.85;
    }

    try {
      const scene = new Scene();
      const aspect = width / height;
      const camera = new OrthographicCamera(-aspect, aspect, 1, -1, 0.1, 10);
      camera.position.z = 1;

      const renderer = new WebGLRenderer({
        canvas,
        antialias: false,
        alpha: true,
      });
      renderer.setSize(width, height);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.setClearColor(0x000000, 0);

      const composer = new EffectComposer(renderer);
      composer.addPass(new RenderPass(scene, camera));

      const ditherPass = new ShaderPass(DitherShader);
      ditherPass.uniforms.resolution.value = new Vector2(
        width * renderer.getPixelRatio(),
        height * renderer.getPixelRatio()
      );

      function isDarkMode() {
        return document.documentElement.dataset.theme === "dark";
      }

      function updateColor() {
        const dark = isDarkMode();
        ditherPass.uniforms.ditherColor.value.copy(
          dark ? DARK_MODE_COLOR : LIGHT_MODE_COLOR
        );
      }

      updateColor();

      const themeObserver = new MutationObserver(updateColor);
      themeObserver.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["data-theme"],
      });

      composer.addPass(ditherPass);

      let plane: Mesh | null = null;
      let offsetX = 0;

      const loader = new TextureLoader();
      loader.load(
        "/img/earth-gray.jpg",
        (texture) => {
          if (disposed) return;

          texture.wrapS = RepeatWrapping;
          texture.wrapT = RepeatWrapping;
          texture.minFilter = LinearFilter;
          texture.magFilter = LinearFilter;

          const viewportAspect = width / height;
          const mapAspect = 2;
          const planeHeight = 2.2;
          const planeWidth = planeHeight * Math.max(mapAspect, viewportAspect * 1.1);

          const geo = new PlaneGeometry(planeWidth, planeHeight);
          const mat = new MeshBasicMaterial({
            map: texture,
            transparent: false,
          });
          plane = new Mesh(geo, mat);
          scene.add(plane);

          setReady(true);
        },
        undefined,
        () => setError(true)
      );

      function handleResize() {
        if (disposed || !container) return;
        const r = container.getBoundingClientRect();
        width = r.width || window.innerWidth;
        height = r.height || window.innerHeight * 0.85;
        const newAspect = width / height;

        camera.left = -newAspect;
        camera.right = newAspect;
        camera.updateProjectionMatrix();

        renderer.setSize(width, height);
        composer.setSize(width, height);
        ditherPass.uniforms.resolution.value.set(
          width * renderer.getPixelRatio(),
          height * renderer.getPixelRatio()
        );
      }

      window.addEventListener("resize", handleResize);

      function animate() {
        if (disposed) return;
        animFrameId = requestAnimationFrame(animate);

        if (plane && !prefersReducedMotion) {
          offsetX += panSpeed;
          if (offsetX > 1) offsetX -= 1;
          (plane.material as MeshBasicMaterial).map!.offset.x = offsetX;
        }

        composer.render();
      }

      animate();

      return () => {
        disposed = true;
        cancelAnimationFrame(animFrameId);
        window.removeEventListener("resize", handleResize);
        themeObserver.disconnect();
        composer.dispose();
        renderer.dispose();
        if (plane) {
          plane.geometry.dispose();
          (plane.material as MeshBasicMaterial).map?.dispose();
          (plane.material as MeshBasicMaterial).dispose();
        }
      };
    } catch (err) {
      console.error("WebGL initialization failed:", err);
      // One-shot fallback when imperative WebGL init throws; defer out of the
      // effect body so it isn't a synchronous set-state-in-effect.
      queueMicrotask(() => setError(true));
    }
  }, [panSpeed]);

  if (error) {
    return null;
  }

  return (
    <div
      ref={containerRef}
      className={`relative overflow-hidden ${className}`}
      aria-hidden="true"
    >
      <canvas
        ref={canvasRef}
        className={`absolute inset-0 w-full h-full transition-opacity duration-700 ${
          ready ? "opacity-100" : "opacity-0"
        }`}
      />
    </div>
  );
}
