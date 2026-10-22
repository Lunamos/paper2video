// Caption pages for the 16:9 film (Captions.tsx) and the 9:16 cut (VCaptions.tsx), shared with
// scripts/caption_layout.mjs → scripts/text_check.py / scripts/srt.py. No React here.
import zhBreaks from "../../public/data/zh_breaks.json";
import { CAP } from "../vertical/layout";
import { layoutCaption, type Tok } from "./breaks";

export { CLOSING, lineWidth, OPENING } from "./breaks"; // for scripts/caption_layout.mjs

/** Measures. 16:9: one line per page, ≤ 18 Chinese characters (common zh-Hans subtitle practice) or ≈ 58 Latin
 * characters (40 px Inter within 1480 px). 9:16: ≤ 2 lines × 9 Chinese / 18 Latin characters (vertical/layout.ts). */
export const CAPTION = {
  wide: { zh: { per: 18, rows: 1, latin: 0.55 }, en: { per: 58, rows: 1, latin: 1 } },
  // a Latin letter at 72 px bold is ≈ 0.68 of a Chinese character
  vertical: { zh: { per: CAP.perLine.zh, rows: 2, latin: 0.68 }, en: { per: CAP.perLine.en, rows: 2, latin: 1 } },
  slack: 0.1, // a line may run 10 % over the measure (font −6 % at most, then the box widens) instead of a near-empty line
} as const;

export type CaptionKind = keyof Omit<typeof CAPTION, "slack">;

/** jieba word boundaries of one caption line (scripts/zh_breaks.py), or null (then Intl.Segmenter decides). */
export const zhOffsets = (key: string): number[] | null => {
  const v = (zhBreaks as unknown as Record<string, unknown>)[key];
  return Array.isArray(v) ? (v as number[]) : null;
};

/** A timed "word" can hold several (a list "wait、however、suppose", or "Fast-dLLM。Google" when the script has no
 * space after the full stop): split it after full-width punctuation (on 9:16 also after "," and inside long
 * lower-case compounds, eight-billion-|parameter) into pieces with the same timing, so a caption line may break there
 * instead of overflowing (not inside 65,537, GPT-4o, Fast-dLLM). */
export const splitLists = <T extends Tok>(words: T[], commas: boolean): T[] =>
  words.flatMap((w) =>
    w.w
      .split(commas ? /(?<=[、，。！？；：])(?=.)|(?<=,)(?=\D)|(?<=[a-z]{3}-)(?=[a-z]{3})/u : /(?<=[、，。！？；：])(?=.)/u)
      .map((piece, k) => ({ ...w, w: piece, sp: k === 0 ? w.sp : false })),
  );

/** The words of one caption line, as the renderer uses them, and its pages of lines (token index ranges). */
export const captionPages = <T extends Tok>(words: T[], key: string, kind: CaptionKind, zh: boolean) => {
  const toks = splitLists(words, kind === "vertical");
  const m = CAPTION[kind][zh ? "zh" : "en"];
  // the jieba offsets index the line's words joined without spaces; splitting a list keeps the characters, so they hold
  const layout = layoutCaption(toks, { zh, per: m.per, rows: m.rows, latin: m.latin, slack: CAPTION.slack, offsets: zh ? zhOffsets(key) : null });
  return { toks, ...layout, per: m.per, latin: m.latin };
};
