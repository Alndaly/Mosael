import fs from "node:fs";
import path from "node:path";

/**
 * 官方插件索引。
 *
 * **数据源是仓库里那些真的能装的 manifest**(`plugins/examples/<名字>/open-studio.plugin.json`),
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

type Manifest = {
  id?: string;
  name?: string;
  version?: string;
  kind?: string;
  entry?: string;
  runtime?: { kind?: string };
  permissions?: string[];
  skills?: { description?: string }[];
  tools?: { declare?: { name?: string; description?: string }[] };
};

const EXAMPLES = path.join(process.cwd(), "..", "plugins", "examples");

export function listPlugins(): PluginEntry[] {
  if (!fs.existsSync(EXAMPLES)) return [];
  return fs
    .readdirSync(EXAMPLES)
    .map((dir) => path.join(EXAMPLES, dir, "open-studio.plugin.json"))
    .filter((file) => fs.existsSync(file))
    .map((file): PluginEntry => {
      const manifest = JSON.parse(fs.readFileSync(file, "utf8")) as Manifest;
      // kind 在 manifest 里有两种写法(顶层 `kind` 与 `runtime.kind`),都认;
      // 两处都没有就是带 entry 的本地脚本。
      const kind = manifest.kind ?? manifest.runtime?.kind;
      return {
        id: manifest.id ?? "",
        name: manifest.name ?? "",
        version: manifest.version ?? "",
        kind: kind === "mcp" ? "mcp" : "script",
        permissions: manifest.permissions ?? [],
        summary: manifest.skills?.[0]?.description ?? "",
        source: `plugins/examples/${path.basename(path.dirname(file))}`,
        slug: path.basename(path.dirname(file)),
        tools: (manifest.tools?.declare ?? [])
          .filter((tool) => tool.name)
          .map((tool) => ({ name: tool.name ?? "", description: tool.description ?? "" })),
      };
    })
    .sort((a, b) => a.name.localeCompare(b.name));
}

export function findPlugin(slug: string): PluginEntry | null {
  return listPlugins().find((plugin) => plugin.slug === slug) ?? null;
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

/**
 * 社区工作流的条目形状。
 *
 * 先把形状定下来,内容后补 —— 定义在这里而不是等到有第一条投稿再拍脑袋,是因为形状会
 * 反过来决定投稿要交什么。`graph` 就是 `/api/workflows` 那份图,存下来能直接导入。
 */
export type WorkflowEntry = {
  id: string;
  name: string;
  summary: string;
  /** 图里有多少个节点 —— 一眼看出这条工作流多复杂。 */
  nodes: number;
  /** 跑起来需要先配好哪些能力(AI 对话 / 文生图 / 转写 …)。 */
  requires: string[];
  author: string;
  /** 可导入的图,相对站点根的 URL。 */
  graph: string;
};

/** 还没有收录的工作流。空数组在页面上会渲染成"征集中",不是一个坏掉的画廊。 */
export function listWorkflows(): WorkflowEntry[] {
  return [];
}
