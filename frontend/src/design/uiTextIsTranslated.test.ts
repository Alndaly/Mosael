/**
 * 棘轮:界面上给人看的字**走文案表**(`app/messages.ts` 的中英两份),不在组件里写死中文。
 *
 * 写死的中文在英文界面里原样出现 —— 3D 场景页的「已选 N 个场景」「删除所选」、Blender 取回的
 * 提示、桌面壳的菜单和托盘,切成英文后还是中文。
 *
 * 扫的是代码行里的中文字符(跳过注释)。`LEFT` 是存量,**只减不增**:哪个文件翻完了就把它
 * 删掉或改小。`EXEMPT` 是**本来就该是中文**的文件,每一条写清为什么(匹配平台页面上的中文按钮、
 * 发给模型的提示词、古诗……);不许拿它当垃圾桶。
 *
 * 看不见的:拼在模板里、从后端来的字。后端那一半见 backend/tests/test_user_facing_errors_are_translated.py。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { expect, it } from "vitest";

const REPO = join(import.meta.dirname, "..", "..", "..");
const ROOTS = ["frontend/src", "electron", "browser-extension/src"];
const CJK = /[一-鿿]/;
const SKIP_FILE = /(\.test\.|\.d\.ts$|\.bundle\.cjs$|\/generated\/|app\/messages\.ts$)/;

function* files(dir: string): Generator<string> {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name === "dist") continue;
    const path = join(dir, name);
    if (statSync(path).isDirectory()) yield* files(path);
    else if (/\.(tsx?|cjs|mjs|js)$/.test(name)) yield path;
  }
}

export function count(): Map<string, number> {
  const found = new Map<string, number>();
  for (const root of ROOTS) {
    for (const path of files(join(REPO, root))) {
      const key = relative(REPO, path);
      if (SKIP_FILE.test(key)) continue;
      let n = 0;
      //: 跨行的块注释要记住「还在注释里」:`{/* 第一行` 之后的续行不以 `*` 开头,只看行首会把
      //: 它们当成代码 —— 界面文字全翻完的文件,光靠注释续行就能数出几十行。
      //: 只认**行首**开的块注释:行中间的 `/*` 可能在字符串里(`accept="image/*"`),
      //: 从那里吞到下一个 `*/` 会把真代码一起藏掉。
      let inBlock = false;
      for (const raw of readFileSync(path, "utf8").split("\n")) {
        let line = raw.trim();
        if (inBlock) {
          const end = line.indexOf("*/");
          if (end < 0) continue;
          inBlock = false;
          line = line.slice(end + 2).replace(/^\}/, "").trim();
        }
        if (/^(\/\*|\{\/\*)/.test(line) && !line.includes("*/")) {
          inBlock = true;
          continue;
        }
        if (/^(\/\/|\*|\/\*|\{\/\*)/.test(line)) continue;
        const code = line.replace(/\/\/.*$/, "").replace(/\{\/\*.*?\*\/\}/g, "").replace(/\/\*.*?\*\//g, "");
        if (CJK.test(code)) n += 1;
      }
      if (n) found.set(key, n);
    }
  }
  return found;
}

/** 本来就该是中文的文件。每条写清理由。 */
const EXEMPT = new Map<string, string>([
  ["electron/i18n.cjs", "桌面壳(主进程)的文案表本身:每个 key 的 zh 那一半就是中文,en 成对写在旁边(electron/i18n.test.ts 查齐)"],
  ["electron/publish/selectors.ts", "发布适配器拿去匹配抖音/小红书/视频号/B 站真实页面上中文按钮与提示的文字,翻译了就点不中"],
  ["browser-extension/src/i18n.ts", "扩展自己的中英文案表(侧栏按浏览器语言或用户选择取一份)"],
  ["browser-extension/src/platforms/labels.ts", "剥掉 B 站页面标题里「哔哩哔哩」后缀的解析正则"],
  ["frontend/src/domain/timeline/transcriptProjection.ts", "识别中文口语语气词(呃、嗯、那个……)的词表"],
  ["frontend/src/features/agent/spokenChoice.ts", "解析用户中文语音里「第几个」的序号词表"],
  ["frontend/src/features/agent/userMessage.tsx", "发给模型、再从正文里拆回来的附件标记格式 `[附件 asset_id=… 名称=… 类型=…]`"],
  ["frontend/src/features/auth/legal.tsx", "用户协议 / 隐私政策的中英两份原文,按界面语言整段选用"],
  ["frontend/src/features/home/poems.ts", "首页每日一句的古诗词原文(断网兜底),是内容不是界面文字"],
  ["frontend/src/features/notes/strings.ts", "笔记自己的中英文案表(含编辑器节点文案)"],
  ["frontend/src/features/notes/useNoteAttachments.tsx", "发给模型的笔记引用说明,界面上不显示"],
]);

/** 还没翻完的:文件 → 还剩几行。**只减不增。** */
const LEFT = new Map<string, number>([
  //: 剩下 2 行是第二语言下拉里语言的自称(中文、日本語),各用各的文字写。
  ["browser-extension/src/sidepanel.tsx", 2],
  ["electron/publish/adapters/bilibili.ts", 9],
  ["electron/publish/adapters/shared.ts", 2],
  ["electron/publish/adapters/weixinChannels.ts", 1],
  ["electron/publish/adapters/xiaohongshu.ts", 4],
  ["electron/publish/clickChain.ts", 1],
  ["electron/publish/platforms.ts", 7],
  //: 剩下 1 行是剥掉报错前缀「失败 ·」的解析正则,不是界面文字。
  ["frontend/src/features/ai-studio/AiStudio.tsx", 1],
  ["frontend/src/features/scenes/SceneAxisGizmo.tsx", 1],
  ["frontend/src/features/scenes/SceneBlender.tsx", 41],
  ["frontend/src/features/scenes/SceneBlenderPull.tsx", 15],
  ["frontend/src/features/scenes/SceneCameraPanel.tsx", 29],
  ["frontend/src/features/scenes/SceneHistory.tsx", 4],
  ["frontend/src/features/scenes/SceneInspector.tsx", 50],
  ["frontend/src/features/scenes/SceneList.tsx", 26],
  ["frontend/src/features/scenes/SceneStudio.tsx", 155],
  ["frontend/src/features/scenes/SceneViewport.tsx", 14],
  ["frontend/src/features/scenes/axisGizmo.ts", 3],
  ["frontend/src/features/scenes/blockoutPrompt.ts", 7],
  ["frontend/src/features/scenes/encodeVideo.ts", 3],
  ["frontend/src/features/scenes/lighting.ts", 55],
  ["frontend/src/features/scenes/sceneGraph.ts", 19],
]);

it("没有新的写死中文的界面文字", () => {
  const grown = [...count()].filter(([file, n]) => !EXEMPT.has(file) && n > (LEFT.get(file) ?? 0));
  expect(grown.map(([f, n]) => `${f}: ${LEFT.get(f) ?? 0} → ${n}`), "界面文字走 app/messages.ts(中英两份)").toEqual([]);
});

it("存量只减不增", () => {
  const now = count();
  const stale = [...LEFT].filter(([file, n]) => (now.get(file) ?? 0) < n);
  expect(stale.map(([f, n]) => `${f}: ${n} → ${now.get(f) ?? 0}`), "翻掉了一些:把 LEFT 里的数字改小(0 就删掉)").toEqual([]);
});

it("豁免的文件真的存在,且不和存量重复", () => {
  const now = count();
  for (const file of EXEMPT.keys()) {
    expect(now.has(file), `${file} 已经没有中文了,从 EXEMPT 里删掉`).toBe(true);
    expect(LEFT.has(file), `${file} 同时在 EXEMPT 和 LEFT 里`).toBe(false);
  }
});
