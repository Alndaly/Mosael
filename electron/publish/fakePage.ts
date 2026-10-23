/**
 * **假页面**:把"平台页面长什么样"做成一个可断言的模型,给契约与判定原语做管道测试用。
 *
 * 它不解析 DOM,只提供原语真正用到的那几件事:地址、文字、某个选择器在不在、编辑器里有什么。
 * 写它的理由是 2026-10-23 那一整天的失败:**契约里的地址 / 文案 / 选择器写错了,或者成功信号
 * 定错了,只有真机发布才看得出来**。有了这层,「每个平台 × 每种形状都能从入口走到成功」在 CI 里
 * 就能跑,平台改版导致契约失配时会先在这里红。
 *
 * 边界:它测的是**契约数据与判定口径**,不是平台真实 DOM;真实页面的细节仍要真机核对。
 */
import type { PageDriver } from "./pageDriver";
import { DEEP_TEXT_EXPR } from "./verify";

export interface FakePage {
  /** 页面地址。 */
  url: string;
  /** 当前可见的整页文字(含"shadow 里那些" —— 模型里就是一份清单)。 */
  texts: Set<string>;
  /** 选择器 → 它在不在(顺带记 enable 状态)。 */
  elements: Map<string, { visible: boolean; enabled: boolean }>;
  /** 编辑器里的字(原语读它)。 */
  editor: string;
  /** 平台自己的字数计数(「35 / 1000」那类),没有就空。 */
  counter: string;
  /** 点过的文案(断言"点对了按钮")。 */
  clicked: string[];
  /** 上传过来的文件(断言"交对了文件")。 */
  files: string[];
  /** 点某句文案之后,页面上哪几句话会消失(平台行为由测试按规则登记)。 */
  clickEffects: Map<string, string[]>;
}

export function fakePage(init: Partial<FakePage> = {}): FakePage {
  return {
    url: "https://example.test/creator",
    texts: new Set(init.texts ?? []),
    elements: new Map(init.elements ?? []),
    editor: init.editor ?? "",
    counter: init.counter ?? "",
    clicked: [],
    files: [],
    clickEffects: new Map(init.clickEffects ?? []),
  };
}

/** 给假页面套一层驱动。**只实现契约与判定原语用得到的方法**,其余调用会抛 ——
 *  刻意如此:管道测试要覆盖的正是这些原语,多给方法等于把没测到的路静默放行。 */
export function fakeDriver(page: FakePage): PageDriver {
  const visible = (selector: string) => page.elements.get(selector)?.visible ?? false;
  return {
    url: () => page.url,
    async goto(url: string) {
      page.url = url;
    },
    async cssVisible(selector: string) {
      return visible(selector);
    },
    async cssAttached(selector: string) {
      return page.elements.has(selector);
    },
    async hasText(text: string) {
      return page.texts.has(text);
    },
    async hasTextDeep(text: string) {
      return [...page.texts].some((one) => one.includes(text));
    },
    async clickCss(selector: string) {
      if (!page.elements.has(selector)) throw new Error(`no such element: ${selector}`);
      page.clicked.push(selector);
    },
    async clickByText(text: string) {
      page.clicked.push(text);
      for (const gone of page.clickEffects.get(text) ?? [text]) page.texts.delete(gone);
    },
    async pressKey(key: string) {
      if (key === "Escape") {
        //: Esc 关掉"按选择器认"的浮层。
        for (const [selector, state] of page.elements) {
          if (/shepherd/.test(selector)) state.visible = false;
        }
      }
    },
    async setFiles(selector: string, paths: string | string[]) {
      if (!page.elements.has(selector)) throw new Error(`no file input: ${selector}`);
      page.files.push(...(Array.isArray(paths) ? paths : [paths]));
    },
    async evaluate<T>(expression: string): Promise<T> {
      if (expression === DEEP_TEXT_EXPR) return [...page.texts].join("\n") as T;
      if (expression.includes("querySelectorAll")) return page.editor as T;
      const counted = page.counter.match(/(\d+)\s*\/\s*\d+/);
      if (expression.includes("match(")) return (counted ? counted[1] : "") as T;
      throw new Error(`fake driver cannot evaluate: ${expression.slice(0, 80)}`);
    },
  } as unknown as PageDriver;
}
