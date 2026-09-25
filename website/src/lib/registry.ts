import fs from "node:fs";
import path from "node:path";

import { DEFAULT_LOCALE, type Locale } from "@/i18n/config";
import { toPlainText } from "@/lib/inline-markdown";

/**
 * 官方插件索引。
 *
 * **数据源是仓库里那些真的能装的 manifest**(`plugins/examples/<名字>/mosael.plugin.json`),
 * 以及随应用内置的那些(`plugins/bundled/<名字>/`,如 ComfyUI),构建期读进来 —— 不是在这里
 * 另抄一份。内置的也要列出来:访客会来这儿找「ComfyUI」,找不到就以为 Mosael 没有。
 * 和应用内市场的索引(scripts/sync-plugin-registry.py)是同一条规则。抄一份的下场是插件改了版本号、改了权限,官网还挂着
 * 半年前那版,而访客照着它去装。
 *
 * manifest 的完整字段见 docs/PLUGIN_MANIFEST.md;这里只取展示要用的那几项。
 */
export type PluginEntry = {
  id: string;
  name: string;
  version: string;
  /** 插件怎么跑:本地脚本,还是连一个现成的 MCP 服务。 */
  kind: "script" | "mcp";
  /** 声明式权限。空数组表示纯本地计算,什么都不要。 */
  permissions: string[];
  /**
   * 这个插件让智能体多会干什么 —— 取自 skills[0].description。
   *
   * **原样保留行内 markdown**(技能描述是写给智能体的,里面会有 `**强调**`):要格式的地方交给
   * InlineMarkdown,要纯文本的地方(卡片、meta、搜索)用 toPlainText。在这里剥掉,详情页就
   * 再也拿不回格式;只剥 `**` 的话 `` ` `` 和链接照样露出来。
   */
  summary: string;
  /** 仓库里的源码目录,相对仓库根。 */
  source: string;
  /** URL 里用的那一段 —— 就是插件的目录名(`baidu-pan`),不是那串带点的 id。 */
  slug: string;
  /** 它带来哪些工具。MCP 插件的清单在服务那边,这里是空的。说明同 summary,是行内 markdown。 */
  tools: { name: string; description: string }[];
  /** 谁写的、去哪儿找他(清单的 `author`)。社区里的插件不全是官方的,署名要看得见。 */
  author: { name: string; url: string };
  /** 插件背后那家服务的站点(清单的 `homepage`)。 */
  homepage: string;
  /** 用之前要填的凭据(按清单里的标签),装之前就该知道要准备什么。 */
  credentials: string[];
  /** 官方维护的:这份列表读的是仓库里 `plugins/` 下的插件,目前都是。 */
  official: boolean;
  /**
   * 随应用内置(`plugins/bundled/`):装好就在、跟着应用更新,不从市场装。页面据此标「随应用内置」,
   * 不给安装步骤。
   */
  bundled: boolean;
};

/**
 * 清单里一段给人看的文字。可以是普通字符串,也可以是按语言分的对象 ——
 * 与后端 `manifest.text_of` 同一套约定,见 docs/PLUGIN_MANIFEST.md。
 */
type Text = string | Record<string, string>;

function textOf(value: Text | undefined, locale: Locale): string {
  if (typeof value === "string") return value;
  if (!value) return "";
  // 退路是**给原文**,不是给空:插件只写了一种语言时,看到另一种语言总好过看到空白。
  return value[locale] || value[DEFAULT_LOCALE] || Object.values(value).find(Boolean) || "";
}

type Manifest = {
  id?: string;
  name?: Text;
  version?: string;
  homepage?: string;
  author?: { name?: Text; url?: string };
  instance?: { credentials?: { key?: string; label?: Text; required?: boolean }[] };
  runtime?: { kind?: string };
  permissions?: string[];
  skills?: { description?: Text }[];
  tools?: { declare?: { name?: string; description?: Text }[] };
};

const PLUGINS = path.join(process.cwd(), "..", "plugins");
/** 两个来源:要从市场装的示例插件,和随应用内置的第一方插件。 */
const SOURCES = [
  { dir: "examples", bundled: false },
  { dir: "bundled", bundled: true },
] as const;

/** 仓库里所有插件的目录(相对 plugins/)与它是不是内置的。目录名就是 slug。 */
function pluginDirs(): { slug: string; folder: string; bundled: boolean }[] {
  return SOURCES.flatMap(({ dir, bundled }) => {
    const root = path.join(PLUGINS, dir);
    if (!fs.existsSync(root)) return [];
    return fs
      .readdirSync(root)
      .filter((slug) => fs.existsSync(path.join(root, slug, "mosael.plugin.json")))
      .map((slug) => ({ slug, folder: path.join(dir, slug), bundled }));
  });
}

/** 清单里的链接会直接变成页面上的 `<a href>`:只认 http(s),和应用里的规则一样。 */
function httpUrl(value: string | undefined): string {
  return typeof value === "string" && /^https?:\/\//.test(value) ? value : "";
}

export function listPlugins(locale: Locale = DEFAULT_LOCALE): PluginEntry[] {
  return pluginDirs()
    .map(({ slug, folder, bundled }): PluginEntry => {
      const manifest = JSON.parse(fs.readFileSync(path.join(PLUGINS, folder, "mosael.plugin.json"), "utf8")) as Manifest;
      const kind = manifest.runtime?.kind;
      return {
        id: manifest.id ?? "",
        // 名字、署名、凭据标签只当标签用,从来不显示格式 —— 读进来就收成纯文本。
        name: toPlainText(textOf(manifest.name, locale)),
        version: manifest.version ?? "",
        kind: kind === "mcp" ? "mcp" : "script",
        permissions: manifest.permissions ?? [],
        summary: textOf(manifest.skills?.[0]?.description, locale),
        source: `plugins/${folder.split(path.sep).join("/")}`,
        slug,
        tools: (manifest.tools?.declare ?? [])
          .filter((tool) => tool.name)
          .map((tool) => ({ name: tool.name ?? "", description: textOf(tool.description, locale) })),
        author: { name: toPlainText(textOf(manifest.author?.name, locale)), url: httpUrl(manifest.author?.url) },
        homepage: httpUrl(manifest.homepage),
        credentials: (manifest.instance?.credentials ?? [])
          .filter((credential) => credential.required !== false)
          .map((credential) => toPlainText(textOf(credential.label, locale)) || credential.key || "")
          .filter(Boolean),
        official: true,
        bundled,
      };
    })
    .sort((a, b) => a.name.localeCompare(b.name));
}

export function findPlugin(slug: string, locale: Locale = DEFAULT_LOCALE): PluginEntry | null {
  return listPlugins(locale).find((plugin) => plugin.slug === slug) ?? null;
}

/**
 * 插件自己的 README,原样读出来。
 *
 * **不是每个插件都有** —— text-toolkit 那种一句话说得清的就没写。没有时返回 null,
 * 详情页照样成立(清单里的信息已经够看了),而不是渲染一块空白。
 */
export function readPluginDoc(slug: string): string | null {
  const found = pluginDirs().find((one) => one.slug === slug);
  const file = found ? path.join(PLUGINS, found.folder, "README.md") : "";
  return file && fs.existsSync(file) ? fs.readFileSync(file, "utf8") : null;
}

/** Official downloadable templates, generated from the application's template factories. */
export type WorkflowEntry = {
  id: string;
  /** URL 里那一段:`/workflows/<slug>`。模板 id 用下划线,URL 用连字符。 */
  slug: string;
  name: string;
  /** 简介、步骤、准备项与插件的 summary 一样是行内 markdown,由页面决定渲染还是转纯文本。 */
  summary: string;
  nodes: number;
  requires: string[];
  stages: string[];
  author: string;
  version: number;
  graph: string;
};

type WorkflowRecord = Omit<WorkflowEntry, "slug" | "name" | "summary" | "requires" | "stages" | "graph"> & {
  name: Record<Locale, string>;
  summary: Record<Locale, string>;
  requires: Record<Locale, string[]>;
  stages: Record<Locale, string[]>;
  download: Record<Locale, string>;
};

export function listWorkflows(locale: Locale = DEFAULT_LOCALE): WorkflowEntry[] {
  const catalog = JSON.parse(fs.readFileSync(path.join(process.cwd(), "public/workflows/catalog.json"), "utf8")) as WorkflowRecord[];
  return catalog.map((entry) => ({
    id: entry.id, slug: entry.id.replaceAll("_", "-"), author: entry.author, version: entry.version, nodes: entry.nodes,
    name: toPlainText(entry.name[locale]), summary: entry.summary[locale], requires: entry.requires[locale],
    stages: entry.stages[locale], graph: entry.download[locale],
  }));
}

export function findWorkflow(slug: string, locale: Locale = DEFAULT_LOCALE): WorkflowEntry | null {
  return listWorkflows(locale).find((workflow) => workflow.slug === slug) ?? null;
}
