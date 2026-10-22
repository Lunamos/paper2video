// Shared building blocks for the vertical (9:16) scenes: big headline, accent word, sub-line, honesty chip, source
// line(s), big number, panel, full-frame backdrop. Owned by the lead; scene agents import them read-only.
import React, { useRef } from "react";
import { AbsoluteFill } from "remotion";
import { appear } from "../components/core";
import { color, font } from "../theme";
import { textOf, typo, useNearFit, Words } from "../typography/ZhText";
import { CONTENT, HEAD, SAFE, STAGE, VT } from "./layout";

/** Huge keyword / headline. `hot` words in the flow colour. Centred in the safe width unless `align="left"`.
 * Typography (typography/ZhText.tsx): words never split, balanced lines, no trailing ，。; a headline that overflows
 * one line by ≤ 10 % stays on one line (font −6 % at most, then the box widens). */
export const VHead: React.FC<{
  children: React.ReactNode;
  p?: number;
  y?: number;
  size?: number;
  color?: string;
  align?: "center" | "left";
  zh?: boolean;
}> = ({ children, p = 1, y = HEAD.y, size = VT.head, color: c = color.text, align = "center", zh = true }) => {
  const ref = useRef<HTMLDivElement>(null);
  const fit = useNearFit(ref, textOf(children));
  return (
    <div
      ref={ref}
      style={{
        position: "absolute",
        left: SAFE.left - (align === "center" ? fit.widen / 2 : 0),
        width: SAFE.right - SAFE.left + fit.widen,
        top: y,
        textAlign: align,
        fontFamily: zh ? font.zh : font.sans,
        fontWeight: 900,
        fontSize: size * fit.scale,
        lineHeight: 1.12,
        letterSpacing: zh ? "0.01em" : "-0.03em",
        color: c,
        ...typo.block,
        whiteSpace: fit.one ? "nowrap" : undefined,
        // full-frame pictures run under the headline: a soft dark halo keeps it readable
        textShadow: "0 0 28px rgba(11,14,19,0.85), 0 0 8px rgba(11,14,19,0.9)",
        ...appear(p, 24),
      }}
    >
      <Words>{children}</Words>
    </div>
  );
};

/** A word or phrase in the flow (FLAS) colour, with glow. */
export const Hot: React.FC<{ children: React.ReactNode; c?: string; glow?: string }> = ({ children, c = color.accent, glow = color.accentGlow }) => (
  <span style={{ color: c, textShadow: `0 0 40px ${glow}` }}>{children}</span>
);

/** Secondary line under a headline (same typography as `VHead`). */
export const VSub: React.FC<{ children: React.ReactNode; p?: number; y: number; size?: number; zh?: boolean; c?: string }> = ({
  children,
  p = 1,
  y,
  size = VT.sub,
  zh = true,
  c = color.text2,
}) => {
  const ref = useRef<HTMLDivElement>(null);
  const fit = useNearFit(ref, textOf(children));
  return (
    <div
      ref={ref}
      style={{
        position: "absolute",
        left: SAFE.left - fit.widen / 2,
        width: SAFE.right - SAFE.left + fit.widen,
        top: y,
        textAlign: "center",
        fontFamily: zh ? font.zh : font.sans,
        fontWeight: 700,
        fontSize: size * fit.scale,
        lineHeight: 1.25,
        color: c,
        ...typo.block,
        whiteSpace: fit.one ? "nowrap" : undefined,
        ...appear(p, 16),
      }}
    >
      <Words>{children}</Words>
    </div>
  );
};

/** Small honesty tag (SCHEMATIC / 示意图 / 精选样例 / 演示). Still readable on a phone. */
export const VChip: React.FC<{ children: React.ReactNode; p?: number; x?: number; y: number; c?: string }> = ({
  children,
  p = 1,
  x,
  y,
  c = color.text2,
}) => (
  <div
    style={{
      position: "absolute",
      top: y,
      left: x ?? SAFE.left,
      padding: "6px 16px 8px",
      borderRadius: 10,
      border: `1.5px solid ${color.panelBorder}`,
      background: "rgba(255,255,255,0.05)",
      fontFamily: font.zh,
      fontWeight: 600,
      fontSize: VT.chip,
      color: c,
      opacity: p,
    }}
  >
    {children}
  </div>
);

/** Source lines under a data shot (pass several strings in `lines` for 2–3 short lines, the last one ends at `y`). */
export const VSourceLines: React.FC<{ lines: string[]; p?: number; y?: number }> = ({ lines, p = 1, y = CONTENT.y + CONTENT.h - 30 }) => (
  <>
    {lines.map((l, i) => (
      <VSource key={i} p={p} y={y - (lines.length - 1 - i) * 32}>
        {l}
      </VSource>
    ))}
  </>
);

/** One-line source note, the only small text allowed (rigor: every data shot says where it comes from). */
export const VSource: React.FC<{ children: React.ReactNode; p?: number; y?: number }> = ({ children, p = 1, y = CONTENT.y + CONTENT.h - 30 }) => (
  <div
    style={{
      position: "absolute",
      left: SAFE.left,
      width: SAFE.rightLow - SAFE.left,
      top: y,
      textAlign: "center",
      fontFamily: font.mono,
      fontSize: VT.source,
      color: color.text3,
      // pictures may run under the source line (full-frame layout): a soft dark halo keeps it readable
      textShadow: "0 0 10px rgba(11,14,19,0.95), 0 0 3px rgba(11,14,19,1)",
      opacity: p,
      whiteSpace: "nowrap",
      overflow: "hidden",
      textOverflow: "ellipsis",
    }}
  >
    {children}
  </div>
);

/** A number at its final value only (no count-up), huge. */
export const VBigNumber: React.FC<{ value: string; p?: number; y: number; c?: string; size?: number; unit?: string }> = ({
  value,
  p = 1,
  y,
  c = color.accent,
  size = VT.big,
  unit,
}) => (
  <div
    style={{
      position: "absolute",
      left: SAFE.left,
      width: SAFE.right - SAFE.left,
      top: y,
      textAlign: "center",
      fontFamily: font.sans,
      fontWeight: 800,
      fontSize: size,
      lineHeight: 1,
      letterSpacing: "-0.04em",
      color: c,
      textShadow: `0 0 50px ${c}55`,
      ...appear(p, 20),
    }}
  >
    {value}
    {unit ? <span style={{ fontSize: size * 0.4, marginLeft: 12, color: color.text2 }}>{unit}</span> : null}
  </div>
);

/** A centred panel in the stage (cards, chat bubbles). */
export const VPanel: React.FC<{ children: React.ReactNode; p?: number; y: number; h?: number; x?: number; w?: number; border?: string }> = ({
  children,
  p = 1,
  y,
  h,
  x = STAGE.x,
  w = STAGE.w,
  border = color.panelBorder,
}) => (
  <div
    style={{
      position: "absolute",
      left: x,
      top: y,
      width: w,
      height: h,
      borderRadius: 28,
      background: "rgba(255,255,255,0.04)",
      border: `2px solid ${border}`,
      padding: "34px 40px",
      boxSizing: "border-box",
      ...appear(p, 20),
    }}
  >
    {children}
  </div>
);

/** Full-frame backdrop for 1080×1920 (the 16:9 Backdrop's grain layer is 1920×1080 and would end at y = 1080). */
export const VBackdrop: React.FC<{ glowAt?: string }> = ({ glowAt = "50% 36%" }) => (
  <AbsoluteFill
    style={{
      background: `radial-gradient(1100px 1500px at ${glowAt}, ${color.bgLift} 0%, ${color.bg} 58%, ${color.bgDeep} 100%)`,
    }}
  >
    <svg width={1080} height={1920} style={{ position: "absolute", inset: 0, opacity: 0.045 }}>
      <filter id="vgrain">
        <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves={2} seed={7} stitchTiles="stitch" />
        <feColorMatrix type="saturate" values="0" />
      </filter>
      <rect width="100%" height="100%" filter="url(#vgrain)" />
    </svg>
  </AbsoluteFill>
);
