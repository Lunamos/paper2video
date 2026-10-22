import React, { useMemo } from "react";
import { useCurrentFrame } from "remotion";
import { color, font, layout, type } from "../theme";
import type { Timeline, TimedWord } from "../timeline/timeline";
import { captionShown } from "../typography/breaks";
import { captionPages } from "../typography/captions";
import { typo } from "../typography/ZhText";

type Page = { from: number; to: number; words: TimedWord[] };

/**
 * Global caption layer (positioned at the bottom of its container). Words already spoken are bright; upcoming words
 * are dimmed. One line per page, laid out by typography/captions.ts (clause boundaries first, never inside a word,
 * kinsoku, no orphan page, balanced); Chinese pages drop commas / full stops (a gap replaces inner ones).
 */
export const Captions: React.FC<{ timeline: Timeline; fontFamily?: string; zh?: boolean; maxWidth?: number }> = ({
  timeline,
  fontFamily = font.sans,
  zh = false,
  maxWidth = 1480,
}) => {
  const frame = useCurrentFrame();
  const pages: Page[] = useMemo(() => {
    const out: Page[] = [];
    for (const s of timeline.scenes) {
      for (const l of s.lines) {
        const abs = l.words.map((w) => ({ ...w, from: w.from + s.from, to: w.to + s.from }));
        const { toks, pages: pgs } = captionPages(abs, `${s.id}:${l.id}`, "wide", zh);
        for (const [[a, b]] of pgs) out.push({ from: toks[a].from, to: toks[b - 1].to, words: toks.slice(a, b) });
      }
    }
    // hold each page until the next one starts (max 0.6s after its last word)
    return out.map((p, i) => {
      const next = out[i + 1];
      const hold = p.to + Math.round(0.6 * timeline.fps);
      return { ...p, to: next ? Math.min(hold, next.from) : hold };
    });
  }, [timeline, zh]);

  const page = pages.find((p) => frame >= p.from && frame < p.to);
  if (!page) return null;
  const fadeIn = Math.min(1, (frame - page.from + 1) / 4);
  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: zh ? 84 : layout.captionBottom,
        display: "flex",
        justifyContent: "center",
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          maxWidth,
          textAlign: "center",
          fontFamily,
          fontSize: zh ? 50 : type.caption,
          fontWeight: zh ? 600 : 500,
          lineHeight: 1.35,
          letterSpacing: zh ? "0.04em" : "-0.005em",
          textShadow: "0 2px 18px rgba(0,0,0,0.85), 0 0 3px rgba(0,0,0,0.9)",
          opacity: fadeIn,
          whiteSpace: "pre", // the page is one line by construction; a slightly long one runs into the margin, never wraps
          ...typo.cjk,
        }}
      >
        {page.words.map((w, i) => {
          const last = i === page.words.length - 1;
          const shown = captionShown(w.w, zh, last);
          const lead = i > 0 && w.sp ? " " : "";
          return (
            <span key={i} style={{ color: frame >= w.from ? color.text : "rgba(236,239,244,0.5)" }}>
              {lead}
              {shown.text}
              {shown.gap ? " " : ""}
            </span>
          );
        })}
      </div>
    </div>
  );
};
