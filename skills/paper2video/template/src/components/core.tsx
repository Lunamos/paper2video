import katex from "katex";
import "katex/dist/katex.min.css";
import React, { useEffect, useMemo, useState } from "react";
import { AbsoluteFill, continueRender, delayRender, interpolate } from "remotion";
import "../theme/katex-colors.css";
import { clamp, color, ease, font, layout, type } from "../theme";
import { typo, Words } from "../typography/ZhText";

// ---------------------------------------------------------------- animation helpers
/** 0..1 progress of an animation that starts at `start` and lasts `dur` frames (clamped, eased). */
export const prog = (frame: number, start: number, dur: number, easing = ease.smooth) =>
  interpolate(frame, [start, start + Math.max(1, dur)], [0, 1], { ...clamp, easing });

/** Fade + small rise, the default "appear" of the film. */
export const appear = (p: number, rise = 14): React.CSSProperties => ({
  opacity: p,
  translate: `0px ${(1 - p) * rise}px`,
});

/** Blocks rendering until all web fonts are loaded (call once at the top of each composition). */
export const useFontsReady = () => {
  const [handle] = useState(() => delayRender("fonts"));
  useEffect(() => {
    document.fonts.ready.then(() => continueRender(handle));
  }, [handle]);
};

// ---------------------------------------------------------------- KaTeX
// Put the paper's own \newcommand macros here (copied verbatim from its LaTeX preamble) so on-screen equations are
// written exactly like the paper. The colour helpers only wrap, they never change the written form.
export const TEX_MACROS: Record<string, string> = {
  "\\R": "\\mathbb{R}",
  // colour helpers: \A{x} = accent, \B{x} = accent2, \H{x} = highlight, \D{x} = dimmed
  "\\A": "\\htmlClass{c-accent}{#1}",
  "\\B": "\\htmlClass{c-accent2}{#1}",
  "\\H": "\\htmlClass{c-highlight}{#1}",
  "\\D": "\\htmlClass{c-dim}{#1}",
};

export const Tex: React.FC<{
  tex: string;
  display?: boolean;
  size?: number;
  color?: string;
  style?: React.CSSProperties;
}> = ({ tex, display = false, size = 40, color: c = color.text, style }) => {
  const html = useMemo(
    () =>
      katex.renderToString(tex, {
        displayMode: display,
        throwOnError: true,
        trust: true,
        strict: "ignore",
        macros: { ...TEX_MACROS },
        output: "html",
      }),
    [tex, display],
  );
  return <span style={{ fontSize: size, color: c, whiteSpace: "nowrap", ...style }} dangerouslySetInnerHTML={{ __html: html }} />;
};

/** Left-to-right "writing" reveal for any content (equations, labels). p: 0..1 */
export const WipeReveal: React.FC<{ p: number; children: React.ReactNode; style?: React.CSSProperties; feather?: number }> = ({
  p,
  children,
  style,
  feather = 8,
}) => {
  const edge = p * (100 + feather);
  const mask = `linear-gradient(90deg, black ${edge - feather}%, transparent ${edge}%)`;
  return <div style={{ display: "inline-block", maskImage: mask, WebkitMaskImage: mask, ...style }}>{children}</div>;
};

// ---------------------------------------------------------------- frame furniture
/** Global backdrop: radial lift + faint film grain. Rendered once per composition, below all scenes. */
export const Backdrop: React.FC<{ glowAt?: string; width?: number; height?: number }> = ({
  glowAt = "50% 42%",
  width = layout.w,
  height = layout.h,
}) => (
  <AbsoluteFill
    style={{
      background: `radial-gradient(1300px 820px at ${glowAt}, ${color.bgLift} 0%, ${color.bg} 58%, ${color.bgDeep} 100%)`,
    }}
  >
    <svg width={width} height={height} style={{ position: "absolute", inset: 0, opacity: 0.045 }}>
      <filter id="grain">
        <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves={2} seed={7} stitchTiles="stitch" />
        <feColorMatrix type="saturate" values="0" />
      </filter>
      <rect width="100%" height="100%" filter="url(#grain)" />
    </svg>
  </AbsoluteFill>
);

/** Small top-left chapter marker: "02 — THE PROBLEM". */
export const ChapterTag: React.FC<{ index: string; title: string; p?: number }> = ({ index, title, p = 1 }) => (
  <div
    style={{
      position: "absolute",
      left: layout.marginX,
      top: 64,
      display: "flex",
      alignItems: "center",
      gap: 14,
      fontFamily: font.mono,
      fontSize: type.micro,
      letterSpacing: "0.16em",
      color: color.text3,
      textTransform: "uppercase",
      opacity: p,
    }}
  >
    <span style={{ color: color.accent }}>{index}</span>
    <span style={{ width: 28 * p, height: 1, background: color.gridStrong }} />
    <span>{title}</span>
  </div>
);

export const Headline: React.FC<{ children: React.ReactNode; p?: number; top?: number; size?: number; fontFamily?: string }> = ({
  children,
  p = 1,
  top = layout.headlineTop,
  size = type.headline,
  fontFamily = font.serif,
}) => (
  <div
    style={{
      position: "absolute",
      left: layout.marginX,
      top,
      fontFamily,
      fontSize: size,
      color: color.text,
      letterSpacing: "-0.01em",
      ...typo.block,
      ...appear(p, 18),
    }}
  >
    <Words>{children}</Words>
  </div>
);

/**
 * Provenance line, bottom-left of every data shot. Conventional labels:
 *   "source" (a figure/table of the paper), "data" (a result file), "paper" (a quoted claim),
 *   "schematic" (an illustration, not data), "selected example" (a cherry-picked real output).
 */
export const SourceNote: React.FC<{
  label?: string;
  children: React.ReactNode;
  p?: number;
  bottom?: number;
  left?: number;
  maxWidth?: number;
}> = ({ label = "source", children, p = 1, bottom = layout.footnoteBottom, left = layout.marginX, maxWidth = 1680 }) => (
  <div
    style={{
      position: "absolute",
      left,
      bottom,
      maxWidth,
      display: "flex",
      gap: 16,
      fontFamily: font.mono,
      fontSize: type.micro,
      lineHeight: 1.5,
      color: color.text3,
      opacity: p,
    }}
  >
    <span style={{ textTransform: "uppercase", letterSpacing: "0.16em", flexShrink: 0 }}>{label}</span>
    <span style={{ color: color.text2, opacity: 0.8 }}>{children}</span>
  </div>
);

export type Tone = "accent" | "accent2" | "highlight" | "neutral";
export const toneColor = (tone: Tone) =>
  tone === "accent"
    ? { c: color.accent, bg: color.accentSoft }
    : tone === "accent2"
      ? { c: color.accent2, bg: color.accent2Soft }
      : tone === "highlight"
        ? { c: color.highlight, bg: color.highlightSoft }
        : { c: color.text2, bg: "rgba(255,255,255,0.05)" };

export const Pill: React.FC<{
  label?: string;
  children: React.ReactNode;
  tone?: Tone;
  size?: number;
  style?: React.CSSProperties;
}> = ({ label, children, tone = "neutral", size = 22, style }) => {
  const { c, bg } = toneColor(tone);
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "baseline",
        gap: 10,
        padding: "7px 16px 8px",
        borderRadius: 999,
        border: `1px solid ${c}55`,
        background: bg,
        fontFamily: font.sans,
        fontSize: size,
        color: c,
        whiteSpace: "nowrap",
        ...style,
      }}
    >
      {label ? (
        <span style={{ fontFamily: font.mono, fontSize: size * 0.72, letterSpacing: "0.12em", textTransform: "uppercase", opacity: 0.75 }}>
          {label}
        </span>
      ) : null}
      {children}
    </span>
  );
};

export const MonoLabel: React.FC<{ children: React.ReactNode; c?: string; size?: number; style?: React.CSSProperties }> = ({
  children,
  c = color.text3,
  size = 16,
  style,
}) => (
  <span
    style={{
      fontFamily: font.mono,
      fontSize: size,
      letterSpacing: "0.14em",
      textTransform: "uppercase",
      color: c,
      whiteSpace: "nowrap",
      ...style,
    }}
  >
    {children}
  </span>
);

// ---------------------------------------------------------------- text with highlighted phrases
export const highlightRuns = (text: string, phrases: string[]): { t: string; hl: number }[] => {
  // hl = index of the phrase occurrence (in order of appearance), -1 = plain
  const marks: [number, number][] = [];
  for (const ph of phrases) {
    let from = 0;
    for (;;) {
      const i = text.indexOf(ph, from);
      if (i < 0) break;
      marks.push([i, i + ph.length]);
      from = i + ph.length;
    }
  }
  marks.sort((a, b) => a[0] - b[0]);
  const runs: { t: string; hl: number }[] = [];
  let cur = 0;
  let k = 0;
  for (const [s, e] of marks) {
    if (s < cur) continue;
    if (s > cur) runs.push({ t: text.slice(cur, s), hl: -1 });
    runs.push({ t: text.slice(s, e), hl: k++ });
    cur = e;
  }
  if (cur < text.length) runs.push({ t: text.slice(cur), hl: -1 });
  return runs;
};

/**
 * Typewriter text whose key phrases "ignite" one after another (e.g. a model output where the relevant words light up).
 * reveal: 0..1 fraction of characters shown; ignite: 0..1 over the highlight sequence.
 */
export const StreamText: React.FC<{
  text: string;
  phrases?: string[];
  reveal?: number;
  ignite?: number;
  hlColor?: string;
  hlGlow?: string;
}> = ({ text, phrases = [], reveal = 1, ignite = 1, hlColor = color.accent2, hlGlow = color.accent2Glow }) => {
  const runs = highlightRuns(text, phrases);
  const nHl = runs.filter((r) => r.hl >= 0).length || 1;
  const cut = Math.floor(text.length * reveal);
  let pos = 0;
  return (
    <>
      {runs.map((r, i) => {
        const start = pos;
        pos += r.t.length;
        if (start >= cut) return null;
        const visible = r.t.slice(0, Math.max(0, cut - start));
        if (r.hl < 0) return <span key={i}>{visible}</span>;
        const on = interpolate(ignite * nHl - r.hl, [0, 0.6], [0, 1], clamp);
        return (
          <span
            key={i}
            style={{
              color: on > 0.5 ? hlColor : undefined,
              backgroundImage: `linear-gradient(transparent 62%, ${hlColor}${Math.round(40 * on)
                .toString(16)
                .padStart(2, "0")} 62%)`,
              textShadow: on > 0 ? `0 0 ${14 * on}px ${hlGlow}` : undefined,
            }}
          >
            {visible}
          </span>
        );
      })}
    </>
  );
};

// ---------------------------------------------------------------- card
/**
 * Absolutely positioned panel. To emphasise a card on a beat, animate the card itself (`emphasis` 0..1: border
 * + glow + a slight lift) — never zoom/push the whole frame (full-frame scale caused visible jitter).
 */
export const Card: React.FC<{
  x: number;
  y: number;
  w: number;
  h: number;
  accent?: boolean;
  emphasis?: number;
  children: React.ReactNode;
  style?: React.CSSProperties;
}> = ({ x, y, w, h, accent, emphasis = 0, children, style }) => {
  const on = accent || emphasis > 0;
  const e = accent ? Math.max(1, emphasis) : emphasis;
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: w,
        height: h,
        borderRadius: 22,
        background: on ? `rgba(92,200,232,${0.035 * e})` : color.panel,
        border: `1px solid ${on ? `rgba(92,200,232,${0.09 + 0.19 * e})` : color.panelBorder}`,
        boxShadow: on ? `0 0 ${80 * e}px rgba(92,200,232,${0.08 * e})` : undefined,
        translate: emphasis > 0 ? `0px ${-4 * emphasis}px` : undefined,
        overflow: "hidden",
        ...style,
      }}
    >
      {children}
    </div>
  );
};
