"use client";

import { useEffect, useRef } from "react";

/**
 * The footer wordmark as a dot matrix. The word is rasterised once, sampled onto a dot grid, and
 * each dot is lit by two sources: the cursor (deep orange, falling off with distance) and a slow
 * ambient sheen that sweeps across so the mark is alive even untouched. Pointer position lives in
 * a ref, not React state; rendering stops when off-screen; static under reduced motion.
 */
export function DotWordmark({ text = "Countersign" }: { text?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const pointer = { x: -9999, y: -9999, active: false };
    let dots: { x: number; y: number; heat: number }[] = [];
    let gap = 8;
    let frame = 0;
    let running = false;
    let t0 = performance.now();

    const build = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const { width, height } = canvas.getBoundingClientRect();
      // A zero-size canvas (hidden tab, mid-resize) has nothing to sample; getImageData
      // throws on it. The resize observer builds again once it has a size.
      if (width < 1 || height < 1) {
        dots = [];
        return;
      }
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      gap = width < 768 ? 4 : width < 1280 ? 6 : 7;
      // Rasterise the word offscreen at CSS-pixel scale, then sample it on the dot grid.
      const off = document.createElement("canvas");
      off.width = Math.floor(width);
      off.height = Math.floor(height);
      const o = off.getContext("2d");
      if (!o) return;
      let size = height * 0.95;
      o.font = `600 ${size}px ${getComputedStyle(document.body).fontFamily}`;
      const measured = o.measureText(text).width;
      size *= Math.min(1, (width * 0.98) / measured);
      o.font = `600 ${size}px ${getComputedStyle(document.body).fontFamily}`;
      o.textAlign = "center";
      o.textBaseline = "alphabetic";
      o.fillStyle = "#fff";
      o.fillText(text, width / 2, height * 0.86);
      const data = o.getImageData(0, 0, off.width, off.height).data;

      dots = [];
      for (let y = gap / 2; y < off.height; y += gap) {
        for (let x = gap / 2; x < off.width; x += gap) {
          const a = data[(Math.floor(y) * off.width + Math.floor(x)) * 4 + 3];
          if (a > 128) dots.push({ x, y, heat: 0 });
        }
      }
      draw(performance.now());
    };

    const draw = (now: number) => {
      const { width, height } = canvas.getBoundingClientRect();
      ctx.clearRect(0, 0, width, height);
      const t = (now - t0) / 1000;
      const sweepX = ((t * 0.12) % 1.4) * width - width * 0.2; // slow left-to-right sheen
      const reach = Math.max(120, width * 0.11);
      const r = gap * 0.36;

      for (const d of dots) {
        let target = 0;
        if (pointer.active) {
          const dist = Math.hypot(d.x - pointer.x, d.y - pointer.y);
          target = Math.max(0, 1 - dist / reach);
        }
        // Ease heat toward the target so the glow trails the cursor instead of snapping.
        d.heat += (target - d.heat) * (reduce ? 1 : 0.18);
        const sheen = reduce ? 0 : Math.max(0, 1 - Math.abs(d.x - sweepX) / (width * 0.12)) * 0.35;
        const glow = Math.min(1, d.heat + sheen);
        // Interpolate dim warm grey (idle) toward deep orange (lit).
        const red = Math.round(46 + (242 - 46) * glow);
        const green = Math.round(43 + (85 - 43) * glow);
        const blue = Math.round(40 + (29 - 40) * glow);
        ctx.fillStyle = `rgb(${red},${green},${blue})`;
        ctx.beginPath();
        ctx.arc(d.x, d.y, r * (1 + glow * 0.45), 0, Math.PI * 2);
        ctx.fill();
      }
    };

    const loop = (now: number) => {
      if (!running) return;
      draw(now);
      frame = requestAnimationFrame(loop);
    };

    const onMove = (e: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      pointer.x = e.clientX - rect.left;
      pointer.y = e.clientY - rect.top;
      pointer.active = true;
      if (reduce) draw(performance.now());
    };
    const onLeave = () => {
      pointer.active = false;
      if (reduce) draw(performance.now());
    };

    const io = new IntersectionObserver(([entry]) => {
      const visible = entry?.isIntersecting ?? false;
      if (visible && !running && !reduce) {
        running = true;
        t0 = performance.now();
        frame = requestAnimationFrame(loop);
      } else if (!visible && running) {
        running = false;
        cancelAnimationFrame(frame);
      }
    });
    const ro = new ResizeObserver(build);

    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerleave", onLeave);
    io.observe(canvas);
    ro.observe(canvas);
    document.fonts?.ready.then(build);

    return () => {
      running = false;
      cancelAnimationFrame(frame);
      io.disconnect();
      ro.disconnect();
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerleave", onLeave);
    };
  }, [text]);

  return (
    <canvas
      ref={canvasRef}
      role="img"
      aria-label={text}
      className="block h-[20vw] w-full cursor-crosshair md:h-[17vw]"
    />
  );
}
