/**
 * 界面里不用原生 `<select>`,也不用浏览器自带的媒体控件条(`<audio controls>` / `<video controls>`)。
 *
 * 原生下拉的弹层由**系统**绘制:配色、圆角、字号、滚动条都不受应用样式约束,深色模式下尤其突兀,
 * 而它旁边就是应用自己的 Combobox —— 同一个表单里两种长相。应用已经有 Combobox / Select 组件,
 * 没有理由再混一个。
 *
 * 这条拦的是「顺手写一个 `<select>`」:它在 diff 里只有一行,和周围的 JSX 混在一起,靠人眼复查
 * 很难注意到,而一旦混进去,后面每个人都会照着抄。
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { openTags, readSource, tsxSources } from "./jsxSource";

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单。
export const RATCHET = true;

const SRC = join(import.meta.dirname, "..");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return entry.name.endsWith(".tsx") ? [full] : [];
  });
}

/** 去掉注释,免得「注释里提到 <select>」被当成用了它。 */
const stripComments = (code: string): string =>
  code.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

describe("原生控件", () => {
  it("没有任何地方直接用 <select>(用 Combobox / Select 组件)", () => {
    const offenders = sourceFiles(SRC).filter((file) =>
      /<select[\s>]/.test(stripComments(readFileSync(file, "utf8"))),
    );
    expect(offenders.map((f) => f.slice(SRC.length + 1))).toEqual([]);
  });
});

/**
 * 媒体控件条同理:浏览器画的那一条(Chrome 一套、Safari 一套)不吃主题、不跟圆角,深色界面里压进来一条亮条,高度还由浏览器
 * 说了算 —— 维护者看着 AI 工作台的音频结果说「太丑了」。全站有自己的一套(components/app/media-playback:VideoPlayer、
 * AudioPlayerBar、波形进度条,素材预览的 MediaPreviewPlayer),要放一段声音或视频就用它们。
 *
 * 拦的是 `<audio>` / `<video>` 上写了 `controls`:不带 controls、由我们自己的控件驱动的媒体元素照常可以用。
 */
describe("原生媒体控件", () => {
  it("没有任何 <audio> / <video> 带 controls(用 media-playback 里的播放器)", () => {
    const offenders = tsxSources().flatMap((file) =>
      openTags(readSource(file))
        .filter((tag) => (tag.tag === "audio" || tag.tag === "video") && tag.attrs.has("controls"))
        .map((tag) => `${file}:${tag.line} <${tag.tag} controls>`),
    );
    expect(offenders).toEqual([]);
  });

  it("扫描面没有空转:media-playback 里确实有 <audio> 和 <video>", () => {
    const tags = openTags(readSource("components/app/media-playback.tsx")).map((tag) => tag.tag);
    expect(tags).toContain("audio");
    expect(tags).toContain("video");
  });
});
