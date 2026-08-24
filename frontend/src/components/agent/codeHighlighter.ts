import type { BundledLanguage, CodeHighlighterPlugin, HighlightOptions, ThemeInput } from "streamdown";

/** Streamdown 没导出 HighlightResult(它只在内部声明),从插件接口的签名里取回来 ——
 *  自己照着抄一份形状,上游一改就静默对不上。 */
type HighlightResult = NonNullable<ReturnType<CodeHighlighterPlugin["highlight"]>>;

/**
 * 代码块的语法高亮 —— Streamdown 自己不带,得由我们喂一个。
 *
 * 它的 `plugins.code` 收一个高亮器接口(见 CodeHighlighterPlugin),没有就退回纯文本 ——
 * 这正是此前对话里代码块一片灰的原因:`语言标签` 都标出来了,却一个颜色都没有。
 *
 * 三个决定:
 *
 * ① **按需装语言,不用整包**。`shiki` 全量带几百种语法(数 MB)。这里只列智能体真会吐的那几种,
 *    每种一个动态 import,由打包器切成独立 chunk。要加语言就往 LANGS 里添一行。
 * ② **JS 正则引擎,不用 oniguruma 的 wasm**。少一个需要被正确伺服的 .wasm 资源 ——
 *    这个应用还要在 Electron 里跑,那边的资源路径是另一套,能不引就不引。
 * ③ **整个高亮器是懒加载的**。第一次真的遇到代码块才去拉;在它就绪之前 `highlight()` 返回
 *    null,Streamdown 先渲染纯文本,加载完再用回调把高亮补上(它的契约就是这么设计的)。
 */
const LANGS: Record<string, () => Promise<unknown>> = {
  python: () => import("shiki/langs/python.mjs"),
  javascript: () => import("shiki/langs/javascript.mjs"),
  typescript: () => import("shiki/langs/typescript.mjs"),
  tsx: () => import("shiki/langs/tsx.mjs"),
  json: () => import("shiki/langs/json.mjs"),
  bash: () => import("shiki/langs/bash.mjs"),
  sql: () => import("shiki/langs/sql.mjs"),
  yaml: () => import("shiki/langs/yaml.mjs"),
  markdown: () => import("shiki/langs/markdown.mjs"),
  html: () => import("shiki/langs/html.mjs"),
  css: () => import("shiki/langs/css.mjs"),
  diff: () => import("shiki/langs/diff.mjs"),
};

/** 常见别名 → 上面那张表里的名字。模型写 ```py 和 ```python 的次数各占一半。 */
const ALIASES: Record<string, string> = {
  py: "python",
  js: "javascript",
  ts: "typescript",
  jsx: "javascript",
  sh: "bash",
  shell: "bash",
  zsh: "bash",
  console: "bash",
  yml: "yaml",
  md: "markdown",
  patch: "diff",
};

function normalize(language: string): string | null {
  const key = (language || "").toLowerCase();
  const resolved = ALIASES[key] ?? key;
  return resolved in LANGS ? resolved : null;
}

type Highlighter = {
  codeToTokens: (code: string, options: Record<string, unknown>) => HighlightResult;
  getLoadedLanguages: () => string[];
  loadLanguage: (lang: unknown) => Promise<void>;
};

let loading: Promise<Highlighter> | null = null;
let ready: Highlighter | null = null;

function boot(): Promise<Highlighter> {
  loading ??= (async () => {
    const [{ createHighlighterCore }, { createJavaScriptRegexEngine }] = await Promise.all([
      import("shiki/core"),
      import("shiki/engine/javascript"),
    ]);
    const highlighter = (await createHighlighterCore({
      themes: [import("shiki/themes/github-light.mjs"), import("shiki/themes/github-dark.mjs")],
      // 语法按需加载,建的时候一个都不带 —— 首次用到哪种才拉哪种。
      langs: [],
      engine: createJavaScriptRegexEngine(),
    })) as unknown as Highlighter;
    ready = highlighter;
    return highlighter;
  })();
  return loading;
}

const THEMES: [ThemeInput, ThemeInput] = ["github-light", "github-dark"] as unknown as [ThemeInput, ThemeInput];

export const codeHighlighter: CodeHighlighterPlugin = {
  name: "shiki",
  type: "code-highlighter",
  getThemes: () => THEMES,
  getSupportedLanguages: () => Object.keys(LANGS) as BundledLanguage[],
  supportsLanguage: (language) => normalize(String(language)) !== null,
  highlight(options: HighlightOptions, callback?: (result: HighlightResult) => void): HighlightResult | null {
    const lang = normalize(String(options.language));
    if (!lang) return null; // 不认识的语言就让它当纯文本,别猜

    const render = (highlighter: Highlighter): HighlightResult =>
      highlighter.codeToTokens(options.code, {
        lang,
        themes: { light: "github-light", dark: "github-dark" },
        // **必须是 "light",不能是 false**。Streamdown 给每个 token 渲染的是
        // `text-[var(--sdm-c,inherit)] dark:text-[var(--shiki-dark,…)]` —— 亮色读的是
        // `--sdm-c`,而那个值来自 token 的 `color` 字段。传 false 时 shiki 只把两种颜色
        // 写进 htmlStyle(--shiki-light/--shiki-dark)、不设 color,于是暗色好好的、
        // 亮色整段落回 inherit(真机:亮色下量到的是前景色 rgb(44,42,51),不是 #D73A49)。
        defaultColor: "light",
      });

    // 已经就绪、语法也在手上 —— 同步给出结果,不闪一下纯文本。
    if (ready && ready.getLoadedLanguages().includes(lang)) return render(ready);

    void (async () => {
      const highlighter = await boot();
      if (!highlighter.getLoadedLanguages().includes(lang)) {
        await highlighter.loadLanguage(await LANGS[lang]());
      }
      callback?.(render(highlighter));
    })();
    return null;
  },
};
