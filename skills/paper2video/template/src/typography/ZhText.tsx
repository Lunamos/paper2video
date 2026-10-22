// Typography for on-screen text blocks: headlines, sub-lines, title cards, claims, any label longer than a few words.
// The rules are in typography/breaks.ts (reference/visual-style.md "Typography"); here they meet the browser:
//   <div style={{ ...typo.block }}><Words>{text}</Words></div>
// - `Words` puts every word of each string in a no-break span, so a CJK line breaks only between words (jieba table
//   of scripts/zh_breaks.py for that string, else Intl.Segmenter) and never between a number and its unit or before
//   closing punctuation; it drops a trailing ，。、；： (centred text: no hanging punctuation in Chrome).
// - `typo.block`: balanced lines (`text-wrap: balance` = the narrowest box with even lines, so no orphan), strict
//   kinsoku, and a thin space between CJK and Latin / digits (`text-autospace`, off by default in Chrome).
// - `useNearFit`: a block that would fit on one line with ≤ 10 % more width stays on one line (font −6 % at most,
//   then the box widens) instead of wrapping one or two characters.
import React, { useLayoutEffect, useRef, useState } from "react";
import { continueRender, delayRender } from "remotion";
import zhBreaks from "../../public/data/zh_breaks.json";
import { breakable, hasCjk, tokenize } from "./breaks";

export const typo = {
  /** Any CJK text (captions included): strict kinsoku, CJK–Latin spacing. */
  cjk: { lineBreak: "strict", textAutospace: "normal" } as React.CSSProperties,
  /** A block that may wrap: the above plus balanced lines. */
  block: { lineBreak: "strict", textAutospace: "normal", textWrap: "balance", wordBreak: "normal", overflowWrap: "normal" } as React.CSSProperties,
};

const TRIM = /[，。、；：,;:]+$/u;

const words = (text: string, trim: boolean): React.ReactNode => {
  const t = trim ? text.replace(TRIM, "") : text;
  if (!hasCjk(t)) return t; // Latin text: the browser already breaks only at spaces
  const toks = tokenize(t);
  const table = (zhBreaks as unknown as Record<string, unknown>)[`t:${t.replace(/\s+/g, "")}`]; // scripts/zh_breaks.py
  const ok = breakable(toks, Array.isArray(table) ? (table as number[]) : null);
  const out: React.ReactNode[] = [];
  let chunk = "";
  const flush = () => {
    if (chunk) out.push(<span key={out.length} style={{ whiteSpace: "nowrap" }}>{chunk}</span>);
    chunk = "";
  };
  toks.forEach((tok, i) => {
    if (i > 0 && ok.has(i)) {
      flush();
      if (tok.sp) out.push(" ");
      chunk = tok.w;
    } else chunk += (tok.sp && (i > 0 || /^\s/.test(t)) ? " " : "") + tok.w;
  });
  flush();
  if (/\s$/.test(t)) out.push(" ");
  return out;
};

const walk = (node: React.ReactNode, trim: boolean): React.ReactNode => {
  const arr = React.Children.toArray(node);
  return arr.map((c, i) => {
    const last = trim && i === arr.length - 1;
    if (typeof c === "string") return <React.Fragment key={i}>{words(c, last)}</React.Fragment>;
    if (React.isValidElement<{ children?: React.ReactNode }>(c) && c.props.children !== undefined) {
      return React.cloneElement(c, undefined, walk(c.props.children, last));
    }
    return c;
  });
};

/** Words of every string in `children` kept whole (see the top of this file). trim: drop a trailing ，。 (default). */
export const Words: React.FC<{ children: React.ReactNode; trim?: boolean }> = ({ children, trim = true }) => <>{walk(children, trim)}</>;

/** The plain text of a React node (for measuring keys and checks). */
export const textOf = (node: React.ReactNode): string =>
  React.Children.toArray(node)
    .map((c) => (typeof c === "string" || typeof c === "number" ? String(c) : React.isValidElement<{ children?: React.ReactNode }>(c) ? textOf(c.props.children) : ""))
    .join("");

/** Near fit: if the block's text overflows one line by ≤ `slack`, keep one line — font × scale (≥ 1 − shrink), box
 * widened by `widen` px — instead of wrapping a character or two. Re-measured when `text` changes, once fonts are in.
 * Use: fontSize × scale, width + widen (centred: left − widen / 2), whiteSpace "nowrap" when `one`. */
export const useNearFit = (ref: React.RefObject<HTMLElement | null>, text: string, slack = 0.1, shrink = 0.06) => {
  const [fit, setFit] = useState({ scale: 1, widen: 0, one: false });
  const cur = useRef(fit);
  cur.current = fit;
  useLayoutEffect(() => {
    const handle = delayRender("useNearFit: measure the text");
    let live = true;
    document.fonts.ready.then(() => {
      const el = ref.current;
      if (live && el) {
        const { scale, widen } = cur.current;
        const box = el.clientWidth - widen;
        const ws = el.style.whiteSpace;
        el.style.whiteSpace = "nowrap";
        const natural = el.scrollWidth / scale;
        el.style.whiteSpace = ws;
        const next =
          natural > box + 1 && natural <= box * (1 + slack)
            ? { scale: Math.max(1 - shrink, box / natural), widen: 0, one: true }
            : { scale: 1, widen: 0, one: false };
        if (next.one) next.widen = Math.max(0, Math.ceil(natural * next.scale - box));
        if (next.scale !== scale || next.widen !== widen || next.one !== cur.current.one) setFit(next);
      }
      continueRender(handle);
    });
    return () => {
      live = false;
    };
  }, [ref, text, slack, shrink]);
  return fit;
};
