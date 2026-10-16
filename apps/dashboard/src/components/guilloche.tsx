"use client";

import { useEffect, useRef } from "react";

/**
 * A guilloche rosette: the engraved line pattern printed on cheques and banknotes so a
 * signature can't be forged. Here it is the brand mark for "countersigning" an action.
 * Drawn on a canvas, rendered only while visible, static under prefers-reduced-motion.
 */
type Layer = { radius: number; amp: number; m: number; n: number; wobble: number; color: string };

const LAYERS: Layer[] = [
  { radius: 0.36, amp: 0.075, m: 18, n: 5, wobble: 0.02, color: "242,85,29" },
  { radius: 0.29, amp: 0.065, m: 24, n: 7, wobble: 0.018, color: "255,122,64" },
  { radius: 0.21, amp: 0.05, m: 30, n: 9, wobble: 0.014, color: "237,234,229" },
  { radius: 0.45, amp: 0.035, m: 36, n: 4, wobble: 0.012, color: "237,234,229" },
  { radius: 0.13, amp: 0.04, m: 12, n: 3, wobble: 0.01, color: "242,85,29" },
];

export function Guilloche({ className }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let frame = 0;
    let running = false;
    let phase = 0;

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const { width, height } = canvas.getBoundingClientRect();
      canvas.width = Math.max(1, Math.floor(width * dpr));
      canvas.height = Math.max(1, Math.floor(height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      draw();
    };

    const draw = () => {
      const { width, height } = canvas.getBoundingClientRect();
      ctx.clearRect(0, 0, width, height);
      const mobile = width < 768;
      const size = mobile ? width * 1.15 : Math.min(width * 0.95, height * 1.3);
      // Desktop: rosette to the right of the copy. Mobile: below it, so text stays readable.
      const cx = width * (mobile ? 0.5 : 0.7);
      const cy = height * (mobile ? 0.8 : 0.5);
      const steps = 1400;

      // A warm core behind the rosette, like light coming through a watermark.
      const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, size * 0.5);
      glow.addColorStop(0, "rgba(242,85,29,0.20)");
      glow.addColorStop(0.45, "rgba(242,85,29,0.07)");
      glow.addColorStop(1, "rgba(242,85,29,0)");
      ctx.globalCompositeOperation = "source-over";
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, width, height);
      // Additive blending makes the line crossings glow.
      ctx.globalCompositeOperation = "lighter";

      LAYERS.forEach((layer, li) => {
        const strands = 8;
        for (let s = 0; s < strands; s++) {
          const offset = (s / strands) * Math.PI * 2;
          const p = phase * (li % 2 === 0 ? 1 : -0.7) + offset;
          ctx.beginPath();
          for (let i = 0; i <= steps; i++) {
            const t = (i / steps) * Math.PI * 2;
            const r =
              size * (layer.radius + layer.amp * Math.cos(layer.m * t + p)) +
              size * layer.wobble * Math.sin(layer.n * t - p * 0.5);
            const x = cx + r * Math.cos(t);
            const y = cy + r * Math.sin(t);
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
          }
          const alpha = layer.color.startsWith("237") ? 0.1 : 0.26;
          ctx.strokeStyle = `rgba(${layer.color},${alpha})`;
          ctx.lineWidth = 0.85;
          ctx.stroke();
        }
      });
    };

    const tick = () => {
      if (!running) return;
      phase += 0.0025;
      draw();
      frame = requestAnimationFrame(tick);
    };

    const observer = new IntersectionObserver(([entry]) => {
      const visible = entry?.isIntersecting ?? false;
      if (visible && !running && !reduce) {
        running = true;
        frame = requestAnimationFrame(tick);
      } else if (!visible && running) {
        running = false;
        cancelAnimationFrame(frame);
      }
    });

    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(canvas);
    observer.observe(canvas);
    resize();

    return () => {
      running = false;
      cancelAnimationFrame(frame);
      observer.disconnect();
      resizeObserver.disconnect();
    };
  }, []);

  return <canvas ref={canvasRef} aria-hidden="true" className={className} />;
}
