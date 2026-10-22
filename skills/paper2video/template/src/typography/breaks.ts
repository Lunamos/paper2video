// Line breaking for on-screen text (captions at 16:9 and 9:16, cards, headlines). Pure functions, no React and no
// imports, so the components and scripts/caption_layout.mjs (used by scripts/text_check.py and scripts/srt.py) run the
// very same code: what the checker reports is what renders. The rules (reference/visual-style.md "Typography"):
//   - break at clause punctuation first, else between words, never inside one: Chinese words come from jieba
//     (scripts/zh_breaks.py) or, without a table, Intl.Segmenter; Latin words, names, model names ("Llama 3") and
//     numbers with their units (「1000 步」「第 3」「7B」) stay whole;
//   - kinsoku: no line starts with closing punctuation (，。、；：！？）》」』”’…—), none ends with opening punctuation
//     (（《「『“‘);
//   - no orphan: the last line has ≥ 3 CJK characters and ≥ ~35 % of the line above;
//   - lines as even as possible (least squares), the top line equal or slightly longer;
//   - a line may run up to `slack` (10 %) over the measure — the renderer widens the box or shrinks the font ≤ 6 % —
//     instead of creating a near-empty line;
//   - captions: ≤ `rows` lines per page; what does not fit becomes the next page (its own timed caption), cut at a
//     clause boundary.

/** A caption word (vo JSON words, TimedWord) or a token of a string: `sp` = a space before it. */
export type Tok = { w: string; sp?: boolean | number };

/** May not start a line (closing punctuation; it sticks to the word before). */
export const CLOSING = "，。、；：！？）》」』〕】〉”’…—,.;:!?)]}%％";
/** May not end a line (opening punctuation; it sticks to the word after). */
export const OPENING = "（《「『〔【〈“‘([{";
const IDEO = /[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]/; // ideographs and kana
const FULLWIDTH = /[\u3000-\u303f\uff00-\uffef]/; // full-width punctuation and forms: one cell
const NUM_END = /[0-9０-９零〇一二两三四五六七八九十百千万亿第]$/;
const NUM_OR_UNIT_START = /^[0-9０-９零〇一二两三四五六七八九十百千万亿%％个位名次步倍层轮年月日天秒分种条篇张份项组块台句道题元度点页行列维岁代周届期集]/;

const RANGE = /^[到至~～\-–]/;
const RANGE_END = /[到至~～\-–]$/;

/** Punctuation dropped at the end of a Chinese caption line (and shown as a gap inside one): subtitle convention. */
export const ZH_DROP = /[，。、；：,.;:…]+$/u;

/** True for a string that contains CJK ideographs / kana. */
export const hasCjk = (s: string) => IDEO.test(s);

/** Width of a string in CJK cells: an ideograph or full-width mark = 1, anything else = `latin`. */
export const cellsOf = (s: string, latin: number) => {
  let n = 0;
  for (const ch of s) n += IDEO.test(ch) || FULLWIDTH.test(ch) ? 1 : latin;
  return n;
};

/** How a caption word is shown: Chinese drops its trailing ，。 etc. — at a line end entirely, inside a line as a gap. */
export const captionShown = (w: string, zh: boolean, lineEnd: boolean) => {
  if (!zh) return { text: w, gap: false };
  const text = w.replace(ZH_DROP, "");
  return { text, gap: text !== w && !lineEnd };
};

/** Width of one caption line as shown (trailing punctuation dropped, inner gaps, spaces): CJK cells for Chinese
 * (`latin` per Latin letter), characters for Latin captions. */
export const lineWidth = (toks: Tok[], zh: boolean, latin: number) =>
  toks.reduce((acc, t, i) => {
    const s = captionShown(t.w, zh, i === toks.length - 1);
    return acc + cellsOf(s.text, zh ? latin : 1) + (s.gap ? 0.3 : 0) + (i > 0 && t.sp ? (zh ? 0.3 : 1) : 0);
  }, 0);

/** Split a string into tokens the way scripts/vo.py does for captions: one token per CJK character, Latin words and
 * numbers whole, closing punctuation stuck to the token before, opening punctuation to the token after. */
export const tokenize = (text: string): Tok[] => {
  const out: Tok[] = [];
  let cur: Tok | null = null;
  let pending = "";
  let space = false;
  const close = () => {
    if (cur) out.push(cur);
    cur = null;
  };
  const chars = Array.from(text);
  chars.forEach((ch, i) => {
    const numSep = ".,:".includes(ch) && /\d/.test(chars[i - 1] ?? "") && /\d/.test(chars[i + 1] ?? "");
    if (/\s/.test(ch)) {
      close();
      space = true;
    } else if (IDEO.test(ch)) {
      close();
      out.push({ w: pending + ch, sp: space });
      pending = "";
      space = false;
    } else if (/[\p{L}\p{N}'’\-%]/u.test(ch) || numSep) {
      if (cur) cur.w += ch;
      else {
        cur = { w: pending + ch, sp: space };
        pending = "";
        space = false;
      }
    } else if (OPENING.includes(ch)) {
      close();
      pending += ch;
    } else if (cur) {
      (cur as Tok).w += ch;
    } else if (out.length) {
      out[out.length - 1].w += ch;
    } else {
      pending += ch;
    }
  });
  close();
  if (pending) out.push({ w: pending, sp: space });
  return out;
};

const isLatin = (c: string) => /[A-Za-z0-9]/.test(c);

type SegmenterCtor = new (l: string, o: object) => { segment: (s: string) => Iterable<{ index: number }> };

/** Indices i (1..n-1) before which a line may break. `offsets`: character offsets of word boundaries in the joined
 * text (the jieba table of scripts/zh_breaks.py). mode "both" (default): a boundary must be one for jieba AND for
 * Intl.Segmenter (ICU), which catches each one's slips (jieba 很|久, ICU 金门|大|桥); "table": the offsets alone;
 * without offsets Intl.Segmenter alone. A space or a Latin/CJK transition is always a word boundary; kinsoku and the
 * glue rules (numbers + units, "Llama 3") remove candidates. */
export const breakable = (toks: Tok[], offsets?: number[] | null, mode: "both" | "table" = "both"): Set<number> => {
  const joined = toks.map((t) => t.w).join("");
  const Seg = (Intl as unknown as { Segmenter?: SegmenterCtor }).Segmenter;
  const icu: Set<number> | null =
    Seg && (!offsets || mode === "both") ? new Set(Array.from(new Seg("zh", { granularity: "word" }).segment(joined), (s) => s.index)) : null;
  let bounds: Set<number>;
  if (offsets) bounds = icu ? new Set(offsets.filter((o) => icu.has(o))) : new Set(offsets);
  else bounds = icu ?? new Set(Array.from({ length: joined.length }, (_, i) => i));
  const ok = new Set<number>();
  let off = 0;
  toks.forEach((t, i) => {
    if (i > 0) {
      const prev = toks[i - 1].w;
      const word =
        bounds.has(off) ||
        Boolean(t.sp) ||
        isLatin(t.w[0] ?? "") !== isLatin(prev[prev.length - 1] ?? "") ||
        (/(^|[^A-Za-z])[a-z]{3,}-$/.test(prev) && /^[a-z]{3,}/.test(t.w)); // eight-billion-|parameter, not GPT-4o / Fast-dLLM
      const kinsoku = CLOSING.includes(t.w[0] ?? "") || OPENING.includes(prev[prev.length - 1] ?? "");
      const number =
        (NUM_END.test(prev) && (NUM_OR_UNIT_START.test(t.w) || RANGE.test(t.w))) || (RANGE_END.test(prev) && NUM_OR_UNIT_START.test(t.w)); // 1000 步, 一千到一万
      const model = /(^|[^A-Za-z])([A-Z][A-Za-z]*|[A-Za-z]*\d[\w.]*)$/.test(prev) && /^[0-9]/.test(t.w); // Llama 3, GPT 4, Figure 1 (not "between 0.07")
      const unit = /[0-9]$/.test(prev) && /^[A-Za-z%]{1,3}$/.test(t.w); // 7 B, 100 ms
      if (word && !kinsoku && !number && !model && !unit) ok.add(i);
    }
    off += t.w.length;
  });
  return ok;
};

/** Penalty class of a break after `prev`: 0 sentence end, 1 clause, 2 list comma, 3 plain word boundary. */
const breakClass = (prev: string) => (/[。！？!?；;]$/.test(prev) ? 0 : /[，,：:…—]$/.test(prev) ? 1 : /[、]$/.test(prev) ? 2 : 3);
/** A plain word break that leaves a particle at a line start (的 了 着 …) or, at a line end, a word that leans on the
 * next one (prepositions and conjunctions 在 和 把 …, adverbs 更 也 就 才 …, 到 of "A 到 B") reads badly: a soft
 * penalty, so the break moves when a better one is near. */
const PARTICLE_START = /^[的地得了着过们吗呢吧啊么嘛]/;
const LINK_END = /[和与及或在把被对从向给为跟让将而更最很太不没也都就才还又再到至]$/;
const awkward = (prev: string, next: string) => (PARTICLE_START.test(next) ? 1 : 0) + (LINK_END.test(prev) ? 1 : 0);

type Level = {
  per: number; // measure, in CJK cells
  slack: number; // a line may run this fraction over `per`
  wBal: number; // weight of (length - mean)^2
  wOver: number; // per cell over `per`
  wCount: number; // per line / page (fewer is better)
  wTop: number; // per cell the line above is shorter than the one below
  wShort: number; // a line shorter than minLen (in a block of several)
  wRagged: number; // last line < 35 % of the one above
  cut: [number, number, number, number]; // by breakClass
  soft: number; // per `awkward` point of a plain word break
  minLen: number; // cells
};

type Solved = { cost: number; starts: number[] };

/** Minimum-cost split of [lo, hi) into exactly k lines. fits: whether [a, b) fits on a line at all (monotone in b),
 * seg: cost of a line (Infinity if impossible), cut: cost of a break before i (Infinity if not allowed), pair: cost of
 * a line given the one above. */
const solve = (
  lo: number,
  hi: number,
  k: number,
  fits: (a: number, b: number) => boolean,
  seg: (a: number, b: number) => number,
  cut: (i: number) => number,
  pair: (p: number, a: number, b: number) => number,
): Solved | null => {
  const n = hi - lo;
  if (k < 1 || k > n) return null;
  if (k === 1) {
    const c = fits(lo, hi) ? seg(lo, hi) : Infinity;
    return c < Infinity ? { cost: c, starts: [lo] } : null;
  }
  const N = n + 1;
  const ix = (a: number, b: number) => (a - lo) * N + (b - lo);
  let cur = new Float64Array(N * N).fill(Infinity);
  for (let b = lo + 1; b <= hi && fits(lo, b); b++) cur[ix(lo, b)] = seg(lo, b);
  const back: Int32Array[] = [];
  for (let j = 2; j <= k; j++) {
    const nxt = new Float64Array(N * N).fill(Infinity);
    const bp = new Int32Array(N * N).fill(-1);
    for (let a = lo + 1; a < hi; a++) {
      const ca = cut(a);
      if (ca === Infinity) continue;
      const prev: number[] = [];
      for (let p = lo; p < a; p++) if (cur[ix(p, a)] < Infinity) prev.push(p);
      if (!prev.length) continue;
      for (let b = j === k ? hi : a + 1; b <= hi && fits(a, b); b++) {
        const s = seg(a, b);
        if (s === Infinity) continue;
        let best = Infinity;
        let arg = -1;
        for (const p of prev) {
          const v = cur[ix(p, a)] + pair(p, a, b);
          if (v < best) {
            best = v;
            arg = p;
          }
        }
        nxt[ix(a, b)] = best + ca + s;
        bp[ix(a, b)] = arg;
      }
    }
    cur = nxt;
    back.push(bp);
  }
  let best = Infinity;
  let a = -1;
  for (let p = lo; p < hi; p++) {
    if (cur[ix(p, hi)] < best) {
      best = cur[ix(p, hi)];
      a = p;
    }
  }
  if (a < 0) return null;
  const starts = [a];
  let b = hi;
  for (let j = k; j >= 2; j--) {
    const p = back[j - 2][ix(a, b)];
    b = a;
    a = p;
    starts.unshift(a);
  }
  return { cost: best, starts };
};

export type CaptionOpts = {
  zh: boolean;
  per: number; // characters per line (CJK cells; Latin: characters)
  rows: number; // lines per page: 1 (16:9) or 2 (9:16)
  latin: number; // width of a Latin letter in CJK cells (zh); ignored for Latin captions
  slack?: number; // default 0.1
  offsets?: number[] | null; // jieba word boundaries (scripts/zh_breaks.py) for this line
};

/** A line broken into pages of lines: pages[p][r] = [start, end) token indices. `forced` = no layout obeyed every rule
 * (a word had to be split or a line overflows): rewrite or split that caption line in scenes.json. */
export type CaptionLayout = { pages: [number, number][][]; forced: boolean; ok: Set<number> };

/** Pages and lines of one caption line (`toks` = its words, in order). */
export const layoutCaption = (toks: Tok[], o: CaptionOpts): CaptionLayout => {
  const n = toks.length;
  const slack = o.slack ?? 0.1;
  const zh = o.zh;
  // Latin captions are measured in characters; their costs run on half a character (≈ one CJK cell of the same
  // font size) so that the weights below mean the same in both scripts
  const latin = zh ? o.latin : 0.5;
  const GAP = zh ? 0.3 : 0.5; // a gap (dropped punctuation) or a space
  const per = zh ? o.per : o.per * 0.5;
  const starts: number[] = []; // character offset of every token boundary in the joined text
  toks.reduce((off, t) => (starts.push(off), off + t.w.length), 0);
  // Latin: every word boundary; Chinese: jieba ∩ ICU, falling back to jieba alone if nothing fits
  const ok = zh ? breakable(toks, o.offsets) : breakable(toks, starts, "table");
  const okTable = zh && o.offsets ? breakable(toks, o.offsets, "table") : ok;
  if (n === 0) return { pages: [], forced: false, ok };
  // width of tokens [a, b) as one line: leading spaces inside, trailing punctuation dropped at the end (zh)
  const mid = toks.map((t) => {
    const s = captionShown(t.w, zh, false);
    return cellsOf(s.text, latin) + (s.gap ? GAP : 0);
  });
  const end = toks.map((t) => cellsOf(captionShown(t.w, zh, true).text, latin));
  const lead = toks.map((t, i) => (i > 0 && t.sp ? GAP : 0));
  const pm = [0];
  const pl = [0];
  for (let i = 0; i < n; i++) {
    pm.push(pm[i] + mid[i]);
    pl.push(pl[i] + lead[i]);
  }
  const L = (a: number, b: number) => pm[b - 1] - pm[a] + end[b - 1] + (pl[b] - pl[a + 1]);
  const minLen = 3; // cells: 3 CJK characters, ~6 Latin characters

  const run = (allowed: (i: number) => boolean, capScale: number): CaptionLayout | null => {
    const mk = (lv: Level, segLen: (a: number, b: number) => number, extra?: (a: number, b: number) => number) => {
      const best = (lo: number, hi: number, kMin: number, kMax: number): Solved | null => {
        let out: Solved | null = null;
        const total = segLen(lo, hi);
        for (let k = kMin; k <= kMax; k++) {
          const mean = total / k;
          const seg = (a: number, b: number) => {
            const len = segLen(a, b);
            const x = extra ? extra(a, b) : 0;
            if (x === Infinity) return Infinity;
            return (
              x +
              lv.wBal * (len - mean) ** 2 +
              (len > lv.per ? lv.wOver * (len - lv.per) : 0) +
              (k > 1 && len < lv.minLen ? lv.wShort : 0)
            );
          };
          const cut = (i: number) => {
            if (!allowed(i)) return Infinity;
            const c = breakClass(toks[i - 1].w);
            return lv.cut[c] + (c === 3 ? lv.soft * awkward(toks[i - 1].w, toks[i].w) : 0);
          };
          const pair = (p: number, a: number, b: number) => {
            const up = segLen(p, a);
            const me = segLen(a, b);
            return (up < me ? lv.wTop * (me - up) : 0) + (b === hi && me < 0.35 * up ? lv.wRagged : 0);
          };
          const fits = (a: number, b: number) => segLen(a, b) <= lv.per * (1 + lv.slack) * capScale;
          const s = solve(lo, hi, k, fits, seg, cut, pair);
          if (s && (!out || s.cost + lv.wCount * k < out.cost)) out = { cost: s.cost + lv.wCount * k, starts: s.starts };
        }
        return out;
      };
      return best;
    };
    const rowLevel: Level = {
      per,
      slack,
      wBal: 1,
      wOver: 6,
      wCount: 4,
      wTop: 0.6,
      wShort: 40,
      wRagged: 15,
      cut: [0, 0.5, 1.5, 8],
      soft: 3,
      minLen,
    };
    const toRanges = (starts: number[], hi: number) => starts.map((s, i): [number, number] => [s, i + 1 < starts.length ? starts[i + 1] : hi]);
    if (o.rows <= 1) {
      // one line per page (16:9): the pages are the lines
      // pages are separate captions: a short last page is no orphan (only a flash under 3 characters is), but a
      // page break inside a clause costs more than an extra page
      const pageLevel: Level = { ...rowLevel, wBal: 0.08, wOver: 12, wCount: 12, wTop: 0, wShort: 30, wRagged: 0, cut: [0, 2, 6, 30], soft: 4 };
      const kMin = Math.max(1, Math.ceil(L(0, n) / (per * (1 + slack) * capScale)));
      const s = mk(pageLevel, L)(0, n, kMin, Math.min(n, kMin + 2));
      return s ? { pages: toRanges(s.starts, n).map((r) => [r]), forced: false, ok } : null;
    }
    // several lines per page (9:16): a page costs its best split into ≤ rows lines
    const rows = mk(rowLevel, L);
    const memo = new Map<number, Solved | null>();
    const inner = (a: number, b: number) => {
      const key = a * (n + 1) + b;
      if (!memo.has(key)) memo.set(key, L(a, b) > per * o.rows * (1 + slack) * capScale ? null : rows(a, b, 1, Math.min(o.rows, b - a)));
      return memo.get(key) ?? null;
    };
    const pageLevel: Level = {
      per: per * o.rows,
      slack,
      wBal: 0.08,
      wOver: 0,
      wCount: 6, // a second page at a clause beats a word break inside a page
      wTop: 0,
      wShort: 30,
      wRagged: 0,
      cut: [0, 2, 6, 30],
      soft: 4,
      minLen,
    };
    const kMin = Math.max(1, Math.ceil(L(0, n) / (per * o.rows * (1 + slack) * capScale)));
    const s = mk(pageLevel, L, (a, b) => inner(a, b)?.cost ?? Infinity)(0, n, kMin, Math.min(n, kMin + 2));
    if (!s) return null;
    return {
      pages: toRanges(s.starts, n).map(([a, b]) => toRanges((inner(a, b) as Solved).starts, b)),
      forced: false,
      ok,
    };
  };

  // `ok` of the result: the breaks the rules allowed for it (jieba ∩ ICU, else jieba alone), so a break outside it
  // is a rule broken (scripts/text_check.py reports it)
  const strict = run((i) => ok.has(i), 1);
  if (strict) return strict;
  const table = run((i) => okTable.has(i), 1);
  if (table) return { ...table, ok: okTable };
  // no layout keeps every rule: first let only the line holding the widest word overflow (words stay whole), then
  // allow any boundary except kinsoku, then anything
  let wMax = 0;
  for (let i = 0; i < n; i++) wMax = Math.max(wMax, L(i, i + 1));
  const over = Math.max(1, wMax / (per * (1 + slack))) + 1e-6;
  const loose = breakable(toks, starts, "table");
  const r =
    run((i) => okTable.has(i), over) ?? run((i) => loose.has(i), 1) ?? run((i) => loose.has(i), over) ?? run(() => true, 1) ?? run(() => true, 100);
  return { ...(r ?? { pages: [[[0, n]]] }), forced: true, ok: okTable };
};
