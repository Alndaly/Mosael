/**
 * 素材缓存的键:取数可以细,失效必须粗。
 *
 * React Query 按**前缀**匹配失效,所以「用哪种形状的键」不是风格问题:剪辑页按
 * `["assets", 工作区, 项目]` 取数,首页按 `["assets", 工作区]` 取数,而剪辑页失效时也写三段
 * —— 三段匹配不到两段,于是在剪辑页导入一段素材,首页的素材列表不会刷新,停在旧数据上。
 *
 * 这条测试盯两件事:键工厂的前缀关系成立,以及**没有人再写内联的 `["assets", …]`**
 * (写了就又绕过了这份约定,而且照样能过编译、能过测试)。
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { assetKeys } from "./queryKeys";

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

const SRC = join(import.meta.dirname, "..");

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(path) && !path.includes(".test.") ? [path] : [];
  });
}

describe("素材缓存的键", () => {
  it("失效用的键是取数用的键的前缀", () => {
    const all = assetKeys.all("ws");
    for (const key of [
      assetKeys.pages({ workspace_id: "ws" }),
      assetKeys.pages({ workspace_id: "ws", project_id: "project", kind: ["video"], q: "海边" }),
      assetKeys.facets("ws"),
      assetKeys.facets("ws", "project"),
      assetKeys.sequence("ws", "seq", "3:abc"),
    ]) {
      expect(key.slice(0, all.length), `${JSON.stringify(key)} 不以 ${JSON.stringify(all)} 开头`).toEqual([...all]);
    }
    // 反过来不成立,这正是问题所在:更长的键匹配不到别的取数形状。
    expect(assetKeys.pages({ workspace_id: "ws", project_id: "project" }).length).toBeGreaterThan(all.length);
  });

  it("不同工作区之间互不影响", () => {
    expect(assetKeys.all("a")).not.toEqual(assetKeys.all("b"));
  });

  it("失效一律用最短前缀 —— 没有人用取数的键去失效", () => {
    const offenders: string[] = [];
    for (const path of sources(SRC)) {
      const code = readFileSync(path, "utf8");
      for (const [line] of code.matchAll(/(?:invalidate|remove|cancel)Queries\(\{[^}]*assetKeys\.(?:pages|facets|sequence)\([^}]*\}/g)) {
        offenders.push(`${path.slice(SRC.length + 1)}: ${line.slice(0, 80)}`);
      }
    }
    expect(offenders, "失效要用 assetKeys.all():取数的键更长,匹配不到别的取数形状").toEqual([]);
  });

});

// 收进 queryKeys.ts 的每一族,都不许再有人内联手写 —— 写了就又绕过了这份约定,而且照样能过
// 编译、能过测试。工作区列表此前就是这样:键收了一半,另一半还在四个文件里各写各的。
// 既查 `queryKey: [...]`,也查 setQueryData / getQueryData 的第一个参数。
//
// **族名从 queryKeys.ts 里读**,不再手抄一份清单:此前这里只列了 assets / workspaces / voices 三族,而工厂里有二十多族,
// 画板、笔记详情就还有人内联手写。收进工厂的那一刻,它就自动受这条约束。
const INLINE = (family: string) => new RegExp(`(?:queryKey:\\s*|(?:set|get)QueryData(?:<[^>]*>)?\\()\\["${family}"`);
const FACTORY_FAMILIES = [...new Set([...readFileSync(join(SRC, "api", "queryKeys.ts"), "utf8").matchAll(/\[\s*"([a-z][\w-]*)"/g)].map((one) => one[1]))].sort();

describe("缓存键只在 queryKeys.ts 里拼", () => {
  it("扫得到工厂里的族 —— 别变成空转", () => {
    expect(FACTORY_FAMILIES).toEqual(expect.arrayContaining(["assets", "boards", "notes", "projects", "scenes", "voices", "workspaces"]));
  });

  it.each(FACTORY_FAMILIES)("没有人再写内联的 %s 键", (family) => {
    const offenders = sources(SRC)
      .filter((path) => !path.endsWith(join("api", "queryKeys.ts")))
      .filter((path) => INLINE(family).test(readFileSync(path, "utf8")))
      .map((path) => path.slice(SRC.length + 1));
    expect(offenders, `改用 queryKeys.ts 里的工厂 —— 内联写法正是当初几种形状各写各的起点`).toEqual([]);
  });

  // 并进别的族之后删掉的旧族名:再出现就是又分出了一份同样的数据。
  it.each([
    ["scene-picker", "sceneKeys.list —— 场景选择器和场景页读的是同一份"],
    ["tts-voices", "voiceKeys.engineVoices —— 带工作区时它含配音库的克隆音色,要跟着配音库一起失效"],
  ])("旧族 %s 不再出现", (family, instead) => {
    const offenders = sources(SRC)
      .filter((path) => readFileSync(path, "utf8").includes(`["${family}"`))
      .map((path) => path.slice(SRC.length + 1));
    expect(offenders, `改用 ${instead}`).toEqual([]);
  });
});

/**
 * **同一个取数函数不许挂在两个键族下。** 同一份数据分在两族,失效只会覆盖写失效的那个人记得的那一族:场景选择器
 * (`scene-picker`)和场景页(`scenes`)取的都是 `listScenes`,场景页新建 / 删除只失效 `scenes`,选择器一分钟内还是旧的;
 * 配音的嗓子列表(`tts-voices`)含配音库的克隆音色,配音库改了只失效 `voices`。
 *
 * 只看看得出族名的那些键:字面量数组的第一段,或者 `xxxKeys.yyy(…)` 记作 `xxxKeys` 一族;放在变量里的键看不出来,跳过。
 */
const SAME_FETCHER_ALLOWED: Record<string, string> = {
  //: 一个按 `options_from` 取候选的通用入口:不同的族取的是不同来源的候选(工作流节点、资产的嗓子、画图参数),不是同一份数据。
  fetchWorkflowFieldOptions: "参数化的通用取数,各族取的不是同一份数据",
  //: 单个任务各自每秒轮询到结束,不靠失效刷新;工作台那份挂在 jobs 下是为了新任务事件时一起重取。
  getJob: "各自轮询到结束,不靠失效",
};

describe("同一个取数函数只在一个键族下", () => {
  const PAIR = /queryKey:\s*(\[\s*"([a-z][\w-]*)"[^\]]*\]|(\w+Keys)\.\w+\([^)]*\))\s*,\s*queryFn:\s*(?:async\s*)?(?:\([^)]*\)\s*=>\s*)?(?:await\s+)?(\w+)/g;
  const families = new Map<string, Map<string, string>>();
  for (const path of sources(SRC)) {
    for (const match of readFileSync(path, "utf8").matchAll(PAIR)) {
      const family = match[2] ?? match[3];
      const fetcher = match[4];
      if (!family || ["api", "Promise", "fetch"].includes(fetcher)) continue;
      const seen = families.get(fetcher) ?? new Map<string, string>();
      if (!seen.has(family)) seen.set(family, path.slice(SRC.length + 1));
      families.set(fetcher, seen);
    }
  }

  it("没有一份数据分在两族", () => {
    const split = [...families]
      .filter(([fetcher, seen]) => seen.size > 1 && !(fetcher in SAME_FETCHER_ALLOWED))
      .map(([fetcher, seen]) => `${fetcher}: ${[...seen].map(([family, path]) => `${family}(${path})`).join("、")}`);
    expect(split, "同一份数据挂在两个键族下,失效只会覆盖其中一族 —— 并成一族(收进 queryKeys.ts)").toEqual([]);
  });

  it("扫得到东西,允许清单里没有过期的条目", () => {
    expect(families.size).toBeGreaterThan(50);
    expect(families.get("listScenes")?.size, "场景列表应当只剩 sceneKeys 一族").toBe(1);
    for (const fetcher of Object.keys(SAME_FETCHER_ALLOWED)) {
      expect(families.get(fetcher)?.size ?? 0, `${fetcher} 已经不分族了 —— 从 SAME_FETCHER_ALLOWED 里删掉`).toBeGreaterThan(1);
    }
  });
});
