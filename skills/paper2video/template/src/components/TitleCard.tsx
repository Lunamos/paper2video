// Full-screen title card, shown right after the hook (hook → title → body): within 10–20 s the viewer knows what they
// are watching — the paper's title, its authors and institutions, where it is published, and its one-sentence claim.
// The narration names the paper on the same beat. Works at 16:9 and 9:16 (the layout follows the composition size).
//
// Optional `shot`: the first page of the paper's PDF (or the first screen of its web article), made with
// scripts/paper_shot.mjs, shown as a sheet of paper on the screen — solid white, never dimmed or blurred, thin edge,
// rounded corners, soft shadow, a slight tilt. It says "this is the paper we are reading": it should be obvious at a
// glance, not necessarily readable, and it never covers the text. Only its upper part shows (title, authors, abstract);
// the lower edge fades out above the captions. It eases in on beats.shot (fade + a small slide), then drifts very
// slowly upwards.
//   16:9  text column on the left (x 150–1070, type capped at the column's sizes), the sheet centre-right
//         (x ≈ 1160–1860, y ≈ 110–880).
//   9:16  the sheet large right under the title block (placed from the measured text) while the title is read; on
//         beats.shotMove (default: the authors beat, at least 3 s after the sheet appears) it slides down into the band
//         under the captions, its header still showing, and the authors, institutions and claim appear where it was.
// With a shot the text block is measured once its fonts are loaded and, if it would run into the captions, scaled down
// to fit — so `shot` (plus beats) is all a card needs. Only the sheet moves, never the whole frame (no zoom, no shake).
import React, { useLayoutEffect, useRef, useState } from "react";
import { AbsoluteFill, continueRender, delayRender, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { appear, prog } from "./core";
import { color, ease, font } from "../theme";
import { typo, Words } from "../typography/ZhText";

// author lists break between names, never inside one ("Yuri / Burda")
const names = (s: string) =>
  s.split(/(\s*[,，、;；]\s*|\s+·\s+|\s+and\s+|\s*&\s*)/).map((part, i) => (i % 2 ? part : <span key={i} style={{ whiteSpace: "nowrap" }}>{part}</span>));

export type TitleCardProps = {
  kicker?: string; // e.g. "arXiv 2603.12228 · 2026" or "NeurIPS 2025"
  title: React.ReactNode; // the paper's short title / name
  subtitle?: string; // the rest of the title, or the original title under a translation
  authors: string;
  affiliation?: string;
  claim?: React.ReactNode; // one sentence, appears on its beat
  note?: string; // e.g. "Unofficial explainer"
  bg?: string; // optional staticFile image, shown blurred behind the card
  // frames (relative to the scene). shot: when the paper sheet eases in (default: with the title).
  // shotMove (9:16 only): when the sheet slides down out of the way (default: the authors beat, ≥ 90 frames after
  // shot); the authors and claim wait for it.
  beats?: { title?: number; authors?: number; claim?: number; shot?: number; shotMove?: number };
  hot?: string; // accent colour of the title
  serif?: boolean;
  titleSize?: number;
  subtitleSize?: number;
  authorsSize?: number;
  claimSize?: number;
  top?: number; // y of the block (default 22% of the height, 330 px vertical; 16:9 with a shot 18%)
  // titleSize / subtitleSize / authorsSize / claimSize: shrink for a long title or author list (check the 9:16 card clears the captions)
  shot?: string; // staticFile path of the paper page, e.g. "shots/paper.png" (scripts/paper_shot.mjs)
  shotWidth?: number; // px, width of the sheet (16:9 default 700; 9:16 900)
  shotLeft?: number; // x of its left edge (16:9 default 1160; 9:16 centred)
  shotTop?: number; // y of its top edge (16:9 default 110; 9:16: just under the measured title block)
  shotTilt?: number; // degrees, clockwise (16:9 default 1.5; 9:16 -1.5; 0 = straight)
  shotCrop?: { x?: number; top?: number }; // page margins cropped away, as fractions of the page (default x 0.08 per side, top 0.05)
  shotDrift?: number; // slow upward drift in px per second after the entrance (default 3; 0 = still)
};

// 16:9 text column with a shot: x 150–1070 and type no larger than these
const WIDE = { title: 96, subtitle: 40, authors: 38, claim: 38 };
const FIT_BOTTOM = { wide: 890, vertical: 1270 }; // the text block is scaled down if it would end below this y
const SHEET_BOTTOM = { wide: 880, vertical: 1290 }; // y where the sheet's lower edge has faded out (above the captions)
const PARK_TOP = 1530; // 9:16: the sheet's top edge after beats.shotMove (the band under the captions)

export const TitleCard: React.FC<TitleCardProps> = ({
  kicker,
  title,
  subtitle,
  authors,
  affiliation,
  claim,
  note,
  bg,
  beats = {},
  hot = color.text,
  serif = true,
  titleSize,
  subtitleSize,
  authorsSize,
  claimSize,
  top,
  shot,
  shotWidth,
  shotLeft,
  shotTop,
  shotTilt,
  shotCrop = {},
  shotDrift = 3,
}) => {
  const f = useCurrentFrame();
  const { width: W, height: H, fps } = useVideoConfig();
  const vertical = H > W;
  const wide = Boolean(shot) && !vertical; // 16:9 with the sheet: a narrower text column on the left, type capped
  const cap = (v: number | undefined, wideMax: number, def: number) => (wide ? Math.min(v ?? wideMax, wideMax) : (v ?? def));

  // with a shot: measure the text block (and its title part) once the fonts are in
  const blockRef = useRef<HTMLDivElement>(null);
  const headRef = useRef<HTMLDivElement>(null);
  const [m, setM] = useState<{ block: number; head: number } | null>(null);
  const [handle] = useState(() => (shot ? delayRender("TitleCard: measure the text") : null));
  useLayoutEffect(() => {
    if (handle === null) return;
    document.fonts.ready.then(() => {
      const b = blockRef.current;
      const h = headRef.current;
      if (b && h) setM({ block: b.offsetHeight, head: h.offsetTop + h.offsetHeight });
      continueRender(handle);
    });
  }, [handle]);

  const t0 = beats.title ?? 0;
  const tShot = beats.shot ?? t0;
  const tMove = beats.shotMove ?? Math.max(beats.authors ?? t0 + 75, tShot + 90);
  // 9:16 with a sheet: it moves out of the way first, then the authors and claim appear where it was
  const after = (t: number, gap: number) => (shot && vertical ? Math.max(t, tMove + gap) : t);
  const pK = prog(f, Math.max(0, t0 - 12), 14, ease.out);
  const pT = prog(f, Math.max(0, t0 - 6), 20, ease.out);
  const pS = prog(f, t0 + 10, 18, ease.out);
  const pA = prog(f, after(beats.authors ?? t0 + 30, 14) - 6, 18, ease.out);
  const pC = prog(f, after(beats.claim ?? t0 + 90, 26) - 6, 18, ease.out);
  const left = vertical ? 120 : wide ? 150 : 160;
  const width = vertical ? 768 : wide ? 920 : W - 2 * left;
  const blockTop = top ?? (vertical ? 330 : H * (wide ? 0.18 : 0.22));
  const fit = shot && m ? Math.min(1, ((vertical ? FIT_BOTTOM.vertical : FIT_BOTTOM.wide) - blockTop) / m.block) : 1;

  // ---- the paper sheet: solid white, slightly tilted, its upper part only, lower edge fading out
  let page: React.ReactNode = null;
  if (shot) {
    const pIn = prog(f, tShot - 6, 40, ease.out);
    const pMove = vertical ? prog(f, tMove - 6, 30, ease.inOut) : 0;
    const drift = (shotDrift * Math.max(0, f - tShot)) / fps;
    const pw = shotWidth ?? (vertical ? 900 : 700);
    const px = shotLeft ?? (vertical ? (W - pw) / 2 : 1160);
    // 9:16: under the title block as measured (kicker, title, subtitle), but leave the sheet at least ~300 px
    const headBottom = blockTop + (m ? m.head * fit : 420);
    const py = shotTop ?? (vertical ? Math.min(Math.max(headBottom + 60, 560), SHEET_BOTTOM.vertical - 300) : 110);
    const fade = vertical ? 130 : 170;
    const wh = Math.max(fade + 60, (vertical ? SHEET_BOTTOM.vertical : SHEET_BOTTOM.wide) - py); // window height, fade included
    const cx = shotCrop.x ?? 0.08;
    const ct = shotCrop.top ?? 0.05;
    const tilt = shotTilt ?? (vertical ? -1.5 : 1.5);
    const pad = 70; // room for the shadow inside the masked box
    const y = interpolate(pMove, [0, 1], [py, PARK_TOP]) - drift + (1 - pIn) * (vertical ? 40 : 20);
    const x = px + (vertical ? 0 : (1 - pIn) * 50);
    const mask = `linear-gradient(180deg, black 0px, black ${pad + wh - fade}px, transparent ${pad + wh}px)`;
    page = (
      <div
        style={{
          position: "absolute",
          left: x - pad,
          top: y - pad,
          padding: pad,
          opacity: pIn,
          rotate: `${tilt * (1 - 0.3 * pMove)}deg`,
          maskImage: mask,
          WebkitMaskImage: mask,
        }}
      >
        <div
          style={{
            width: pw,
            height: wh,
            overflow: "hidden",
            borderRadius: 10,
            background: "#fff",
            outline: "1.5px solid rgba(255,255,255,0.35)",
            boxShadow: "0 28px 70px rgba(0,0,0,0.6), 0 4px 14px rgba(0,0,0,0.35)",
          }}
        >
          <Img
            src={staticFile(shot)}
            style={{ display: "block", width: pw / (1 - 2 * cx), maxWidth: "none", height: "auto", marginLeft: (-pw * cx) / (1 - 2 * cx), translate: `0px ${-ct * 100}%` }}
          />
        </div>
      </div>
    );
  }

  return (
    <AbsoluteFill>
      {bg ? (
        <AbsoluteFill style={{ opacity: 0.3 }}>
          <Img src={staticFile(bg)} style={{ width: W, height: H, objectFit: "cover", filter: "blur(70px) saturate(1.15)" }} />
        </AbsoluteFill>
      ) : null}
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 80% 70% at 40% 45%, rgba(11,14,19,0.35), rgba(11,14,19,0.9))" }} />
      {page}
      <div ref={blockRef} style={{ position: "absolute", left, width, top: blockTop, scale: fit < 1 ? `${fit}` : undefined, transformOrigin: "0 0" }}>
        <div ref={headRef}>
          {kicker ? (
            <div style={{ fontFamily: font.mono, fontSize: vertical ? 30 : wide ? 22 : 24, letterSpacing: "0.16em", textTransform: "uppercase", color: color.text2, ...appear(pK) }}>
              {kicker}
            </div>
          ) : null}
          <div
            style={{
              marginTop: vertical ? 30 : 26,
              fontFamily: serif ? font.serif : font.sans,
              fontWeight: serif ? 500 : 900,
              fontSize: cap(titleSize, WIDE.title, 150),
              lineHeight: 1.04,
              letterSpacing: "-0.02em",
              color: hot,
              textShadow: hot !== color.text ? `0 0 60px ${hot}55` : undefined,
              ...typo.block,
              ...appear(pT, 24),
            }}
          >
            <Words>{title}</Words>
          </div>
          {subtitle ? (
            <div style={{ marginTop: wide ? 18 : 22, fontFamily: font.serif, fontSize: cap(subtitleSize, WIDE.subtitle, vertical ? 52 : 46), lineHeight: 1.25, color: color.text2, maxWidth: vertical ? width : 1300, ...typo.block, ...appear(pS) }}>
              <Words>{subtitle}</Words>
            </div>
          ) : null}
        </div>
        <div style={{ marginTop: vertical ? 70 : wide ? 44 : 54, ...appear(pA) }}>
          <div style={{ fontFamily: font.sans, fontWeight: 600, fontSize: cap(authorsSize, WIDE.authors, vertical ? 62 : 44), lineHeight: 1.35, color: color.text, ...typo.block }}>{names(authors)}</div>
          {affiliation ? <div style={{ marginTop: 10, fontFamily: font.sans, fontSize: vertical ? 52 : wide ? 32 : 34, color: color.accent, ...typo.block }}><Words>{affiliation}</Words></div> : null}
        </div>
        {claim ? (
          <div style={{ marginTop: vertical ? 70 : wide ? 40 : 50, fontFamily: font.sans, fontSize: cap(claimSize, WIDE.claim, vertical ? 64 : 40), lineHeight: 1.35, color: color.text, ...typo.block, ...appear(pC) }}><Words>{claim}</Words></div>
        ) : null}
        {note ? (
          <div style={{ marginTop: vertical ? 50 : wide ? 30 : 36, fontFamily: font.mono, fontSize: vertical ? 30 : 19, letterSpacing: "0.12em", textTransform: "uppercase", color: color.text3, opacity: pA }}>
            {note}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
