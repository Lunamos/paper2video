// Phone captions: two short lines at most, very large, centred in the safe width, spoken words bright.
import React, { useMemo } from "react";
import { useCurrentFrame } from "remotion";
import { color, font } from "../theme";
import type { Timeline, TimedWord } from "../timeline/timeline";
import { captionShown, lineWidth } from "../typography/breaks";
import { CAPTION, captionPages } from "../typography/captions";
import { typo } from "../typography/ZhText";
import { CAP } from "./layout";

type Page = { from: number; to: number; lines: TimedWord[][] };

// Pages of ≤ 2 lines from typography/captions.ts: clause boundaries first, never inside a word (Chinese words from
// scripts/zh_breaks.py → public/data/zh_breaks.json; the renderer's Intl.Segmenter alone splits 金门大桥 as 金门|大|桥),
// kinsoku, no orphan line, the two lines balanced (top equal or longer). A line may run ≤ 10 % over the measure:
// the font shrinks ≤ 6 %, the rest widens the box symmetrically.

export const VCaptions: React.FC<{ timeline: Timeline; zh?: boolean }> = ({ timeline, zh = true }) => {
  const frame = useCurrentFrame();
  const pages: Page[] = useMemo(() => {
    const out: Page[] = [];
    for (const s of timeline.scenes) {
      for (const l of s.lines) {
        const abs = l.words.map((w) => ({ ...w, from: w.from + s.from, to: w.to + s.from }));
        const { toks, pages: pgs } = captionPages(abs, `${s.id}:${l.id}`, "vertical", zh);
        for (const rows of pgs) {
          const lines = rows.map(([a, b]) => toks.slice(a, b));
          out.push({ from: lines[0][0].from, to: lines[lines.length - 1][lines[lines.length - 1].length - 1].to, lines });
        }
      }
    }
    return out.map((p, i) => {
      const next = out[i + 1];
      const hold = p.to + Math.round(0.5 * timeline.fps);
      return { ...p, to: next ? Math.min(hold, next.from) : hold };
    });
  }, [timeline, zh]);
  const page = pages.find((p) => frame >= p.from && frame < p.to);
  if (!page) return null;
  const fadeIn = Math.min(1, (frame - page.from + 1) / 3);
  // a line over the measure: font −6 % at most, then the box widens symmetrically (the layout keeps it ≤ +10 %)
  const m = CAPTION.vertical[zh ? "zh" : "en"];
  const longest = Math.max(...page.lines.map((l) => lineWidth(l, zh, m.latin)));
  const scale = Math.max(0.94, Math.min(1, (m.per + 0.6) / longest));
  const size = Math.floor((zh ? CAP.size.zh : CAP.size.en) * scale);
  const widen = Math.max(0, ((longest * scale) / (m.per + 0.6) - 1) * (CAP.right - CAP.left));
  return (
    <div
      style={{
        position: "absolute",
        left: CAP.left - widen / 2,
        width: CAP.right - CAP.left + widen,
        top: CAP.top,
        height: CAP.height,
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        alignItems: "center",
        pointerEvents: "none",
        opacity: fadeIn,
      }}
    >
      {page.lines.map((ln, li) => (
        <div
          key={li}
          style={{
            fontFamily: zh ? font.zh : font.sans,
            fontWeight: 800,
            fontSize: size,
            lineHeight: 1.28,
            letterSpacing: zh ? "0.03em" : "-0.01em",
            textAlign: "center",
            whiteSpace: "pre",
            ...typo.cjk,
            textShadow: "0 3px 14px rgba(0,0,0,0.95)",
            WebkitTextStroke: "5px rgba(0,0,0,0.92)",
            paintOrder: "stroke fill",
          }}
        >
          {ln.map((w, i) => {
            // every line end drops its ，。 (a trailing gap would push the centred line off-centre)
            const s = captionShown(w.w, zh, i === ln.length - 1);
            return (
              <span key={i} style={{ color: frame >= w.from ? color.text : "rgba(236,239,244,0.42)" }}>
                {i > 0 && w.sp ? " " : ""}
                {s.text}
                {s.gap ? " " : ""}
              </span>
            );
          })}
        </div>
      ))}
    </div>
  );
};
