#!/usr/bin/env node
// Caption pages of a cut, computed by the template's own code (src/typography/captions.ts, bundled in memory with the
// project's esbuild), so scripts/text_check.py and scripts/srt.py see exactly the burned-in captions.
//
// Usage: node scripts/caption_layout.mjs <cut> [--kind wide|vertical|both]
// Prints JSON: { cut, zh, layouts: { wide?: [line], vertical?: [line] } }, line = { key, words: [w], sp: [0|1], ms: [[start, end]],
//   pages: [[[a, b], ...], ...] (token ranges per page and line), widths: [[w, ...], ...] (each line as shown: CJK
//   cells for Chinese, characters for Latin), ok: [i] (allowed breaks), forced, per, latin }.
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const args = process.argv.slice(2);
const cut = args.find((a) => !a.startsWith("--")) ?? "zh";
const kindArg = args.includes("--kind") ? args[args.indexOf("--kind") + 1] : "both";
const here = path.dirname(new URL(import.meta.url).pathname);
const root = process.env.PAPER_VIDEO_ROOT
  ? path.resolve(process.env.PAPER_VIDEO_ROOT)
  : [process.cwd(), path.resolve(here, "..")].find((d) => fs.existsSync(path.join(d, "scenes.json"))) ?? process.cwd();
const entry = path.join(root, "src/typography/captions.ts");
if (!fs.existsSync(entry)) {
  console.error(`no ${entry}: this project predates the shared caption layout (copy template/src/typography from the skill)`);
  process.exit(2);
}
const voPath = path.join(root, `public/data/vo.${cut}.json`);
if (!fs.existsSync(voPath)) {
  console.error(`no ${voPath}`);
  process.exit(2);
}
let esbuild;
try {
  esbuild = await import(pathToFileURL(path.join(root, "node_modules/esbuild/lib/main.js")).href);
} catch {
  esbuild = await import("esbuild");
}
const out = await esbuild.build({
  entryPoints: [entry],
  bundle: true,
  write: false,
  format: "esm",
  platform: "node",
  logLevel: "error",
});
const mod = await import(`data:text/javascript;base64,${Buffer.from(out.outputFiles[0].text).toString("base64")}`);

const vo = JSON.parse(fs.readFileSync(voPath, "utf8"));
const lang = String(vo.meta?.textLang ?? vo.meta?.lang ?? cut);
const zh = ["zh", "ja"].includes(lang.split("-")[0].toLowerCase());
const kinds = kindArg === "both" ? ["wide", "vertical"] : [kindArg];
const layouts = {};
for (const kind of kinds) {
  layouts[kind] = [];
  for (const s of vo.scenes) {
    for (const l of s.lines) {
      const key = `${s.id}:${l.id}`;
      const words = l.words.map((w) => ({ w: w.w, sp: w.sp ?? 0, startMs: w.startMs, endMs: w.endMs }));
      if (!words.length) continue;
      const r = mod.captionPages(words, key, kind, zh);
      layouts[kind].push({
        key,
        words: r.toks.map((t) => t.w),
        sp: r.toks.map((t) => (t.sp ? 1 : 0)),
        ms: r.toks.map((t) => [t.startMs, t.endMs]),
        pages: r.pages,
        widths: r.pages.map((pg) => pg.map(([a, b]) => Math.round(mod.lineWidth(r.toks.slice(a, b), zh, r.latin) * 100) / 100)),
        ok: [...r.ok],
        forced: r.forced,
        per: r.per,
        latin: r.latin,
      });
    }
  }
}
process.stdout.write(JSON.stringify({ cut, zh, slack: mod.CAPTION.slack, closing: mod.CLOSING, opening: mod.OPENING, layouts }));
