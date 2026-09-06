import fs from "node:fs";
import path from "node:path";

import { DEFAULT_LOCALE, type Locale } from "@/i18n/config";

/**
 * 官方插件索引。
 *
 * **数据源是仓库里那些真的能装的 manifest**(`plugins/examples/<名字>/mosael.plugin.json`),
 * 构建期读进来 —— 不是在这里另抄一份。抄一份的下场是插件改了版本号、改了权限,官网还挂着
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
  /** 这个插件让智能体多会干什么 —— 取自 skills[0].description。 */
  summary: string;
  /** 仓库里的源码目录,相对仓库根。 */
  source: string;
  /** URL 里用的那一段 —— 就是插件的目录名(`baidu-pan`),不是那串带点的 id。 */
  slug: string;
  /** 它带来哪些工具。MCP 插件的清单在服务那边,这里是空的。 */
  tools: { name: string; description: string }[];
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
  runtime?: { kind?: string };
  permissions?: string[];
  skills?: { description?: Text }[];
  tools?: { declare?: { name?: string; description?: Text }[] };
};

const EXAMPLES = path.join(process.cwd(), "..", "plugins", "examples");

export function listPlugins(locale: Locale = DEFAULT_LOCALE): PluginEntry[] {
  if (!fs.existsSync(EXAMPLES)) return [];
  return fs
    .readdirSync(EXAMPLES)
    .map((dir) => path.join(EXAMPLES, dir, "mosael.plugin.json"))
    .filter((file) => fs.existsSync(file))
    .map((file): PluginEntry => {
      const manifest = JSON.parse(fs.readFileSync(file, "utf8")) as Manifest;
      const kind = manifest.runtime?.kind;
      return {
        id: manifest.id ?? "",
        name: textOf(manifest.name, locale),
        version: manifest.version ?? "",
        kind: kind === "mcp" ? "mcp" : "script",
        permissions: manifest.permissions ?? [],
        summary: textOf(manifest.skills?.[0]?.description, locale),
        source: `plugins/examples/${path.basename(path.dirname(file))}`,
        slug: path.basename(path.dirname(file)),
        tools: (manifest.tools?.declare ?? [])
          .filter((tool) => tool.name)
          .map((tool) => ({ name: tool.name ?? "", description: textOf(tool.description, locale) })),
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
  const file = path.join(EXAMPLES, slug, "README.md");
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8") : null;
}

/** Official downloadable templates, generated from the application's template factories. */
export type WorkflowEntry = {
  id: string;
  name: string;
  summary: string;
  nodes: number;
  requires: string[];
  stages: string[];
  author: string;
  version: number;
  graph: string;
};

type WorkflowRecord = Omit<WorkflowEntry, "name" | "summary" | "requires" | "stages" | "graph"> & {
  name: Record<Locale, string>;
  summary: Record<Locale, string>;
  requires: Record<Locale, string[]>;
  stages: Record<Locale, string[]>;
  download: Record<Locale, string>;
};

export function listWorkflows(locale: Locale = DEFAULT_LOCALE): WorkflowEntry[] {
  const catalog = JSON.parse(fs.readFileSync(path.join(process.cwd(), "public/workflows/catalog.json"), "utf8")) as WorkflowRecord[];
  return catalog.map((entry) => ({
    id: entry.id, author: entry.author, version: entry.version, nodes: entry.nodes,
    name: entry.name[locale], summary: entry.summary[locale], requires: entry.requires[locale],
    stages: entry.stages[locale], graph: entry.download[locale],
  }));
}
