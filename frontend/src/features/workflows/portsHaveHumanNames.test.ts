/**
 * 每个接点在中英文界面上都叫一个人话名字,同一个节点的同一侧不撞名。
 *
 * 现场:「商品图 → 模特上身图与短视频」里「把这一组动起来」的输入口读作 提示词 / aspect_ratio / resolution / 0,输出口是
 * 素材 / 素材 / 生成任务 —— 引用写在生成参数里的口取了路径的最后一段,写在输入素材第一行的口就叫 `0`;封面那一份和
 * 这次出的全部都叫「素材」。检查器里同一格叫「画面比例」「首帧」。
 *
 * 走一遍每种内置节点(按声明能接上游的每一格、声明的每个输出)和每份官方模板(中英两份、每一层体),按两种界面语言
 * 取名(portNames —— 画布、引用标签、「输出变量」用的同一个函数),红在:
 *
 * - 名字是一个裸的数字(列表的下标);
 * - 名字就是路径上的键,而那一格有人话名字(节点目录给了名字、生成参数 / 素材角色有名字);
 * - 缺翻译:空的、还是文案 key、中文界面上没有中文(JSON 这类术语除外)、英文界面上夹着中文;
 * - 同一个节点同一侧两个口同名。
 *
 * 用户自己起的名字(开始参数、具名输出的键、子流程的入参、插件工具的入参)原样显示,只查前后两条 ——
 * 检查器里那一格写的就是它。
 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import type { WorkflowGraph, WorkflowNodeType } from "@/api/client";
import { canTakeUpstream } from "@/features/nodeForms/fieldTypes";
import type { ConfigSpec } from "@/features/nodeForms/NodeConfigForm";
import { ENTRY_NAMES, workflowPortNamer } from "@/features/workflows/portNames";
import { declaredFieldNames } from "@/features/workflows/scope";
import { SOURCE_ROLE_ORDER } from "@/features/workflows/sourceAssetLines";
import { nodePorts } from "@/features/workflows/workflowPorts";
import { SNAPSHOT, builtinNodeCatalog, uiText, type CatalogLocale } from "@/test/nodeCatalog";

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单。
export const RATCHET = true;

const LOCALES: CatalogLocale[] = ["zh", "en"];
const CATALOGS = { zh: builtinNodeCatalog("zh"), en: builtinNodeCatalog("en") };
const NAMERS = Object.fromEntries(
  LOCALES.map((locale) => [locale, workflowPortNamer({ registry: CATALOGS[locale], t: uiText(locale) })]),
) as Record<CatalogLocale, ReturnType<typeof workflowPortNamer>>;

//: 每种语言里都写成这样的术语。
const TERMS = new Set(["JSON", "JSON Schema"]);
const CJK = /[㐀-鿿]/;
//: 没翻出来的文案 key:后端的 wfField_x / wfOut_x 这一类,前端的 wfGenX / genX。
const MESSAGE_KEY = /^(wf[A-Z][A-Za-z]*_|wf[A-Z]|gen[A-Z]|cap[A-Z])\w*$/;

type Node = WorkflowGraph["nodes"][number];
type Side = "inputs" | "outputs";

/** 这个口的名字是不是用户自己起的:开始参数这类通配展开的输出、具名输出这类按配置展开的口、键值映射里的键。 */
function userAuthored(meta: WorkflowNodeType | undefined, side: Side, key: string): boolean {
  const [root, entry] = key.split(".");
  if (side === "outputs") {
    if (meta?.output_labels?.[key]) return false;
    const mapped = Object.values(meta?.port_maps ?? {}).some((map) => map.output === root);
    return mapped || (meta?.outputs ?? []).some((output) => output.startsWith("*"));
  }
  const spec = meta?.config?.[root] as ConfigSpec | undefined;
  return entry !== undefined && spec?.type === "object" && !spec.entry_labels && !spec.fields;
}

/** 一个节点一侧的口叫什么、哪里不对。 */
function problems(where: string, locale: CatalogLocale, node: Node, side: Side, keys: readonly string[]): string[] {
  const meta = CATALOGS[locale].get(node.type);
  const namer = NAMERS[locale];
  const named = keys.map((key) => [key, side === "inputs" ? namer.input(node, key) : namer.output(node, key)] as const);
  const out: string[] = [];
  for (const [key, label] of named) {
    const say = (why: string) => out.push(`${where} [${locale}] ${side === "inputs" ? "入" : "出"} ${key} →「${label}」:${why}`);
    if (/^\d+$/.test(label)) say("裸的下标");
    if (!label.trim()) say("空的名字");
    if (MESSAGE_KEY.test(label)) say("文案 key 没翻");
    if (userAuthored(meta, side, key)) continue;
    if (label === key || label === key.split(".").at(-1)) say("路径上的键,而这一格有名字");
    if (locale === "zh" && !CJK.test(label) && !TERMS.has(label)) say("中文界面上没有中文");
    if (locale === "en" && CJK.test(label)) say("英文界面上夹着中文");
  }
  const seen = new Map<string, string>();
  for (const [key, label] of named) {
    const first = seen.get(label);
    if (first !== undefined) out.push(`${where} [${locale}] ${side === "inputs" ? "入" : "出"} ${first} 和 ${key} 都叫「${label}」`);
    else seen.set(label, key);
  }
  return out;
}

describe("每种内置节点", () => {
  it("快照里有节点,两种语言都有名字", () => {
    expect(SNAPSHOT.length).toBeGreaterThan(40);
    expect(SNAPSHOT.find((one) => one.type === "ai_generate")?.config.prompt.label).toEqual({ zh: "提示词", en: "Prompt" });
  });

  it("字段声明的每一种 entry_labels,前端都知道怎么取名(否则名字悄悄退回键名)", () => {
    const declared = SNAPSHOT.flatMap((one) => Object.values(one.config).map((spec) => spec.entry_labels)).filter(Boolean);
    expect(declared.length).toBeGreaterThan(0);
    expect(declared.filter((source) => !Object.hasOwn(ENTRY_NAMES, String(source)))).toEqual([]);
  });

  it.each(LOCALES)("能接上游的每一格、声明的每个输出 [%s]", (locale) => {
    const found = [...CATALOGS[locale].values()].flatMap((meta) => {
      //: 开始节点的参数是用户起的名字;按角色一行一格的那一种,每个角色各挂一行、再多挂一行同角色的、一行不写角色的。
      const config: Record<string, unknown> = meta.type === "start" ? { params: { topic: "", style: "" } } : {};
      const inputs: string[] = [];
      for (const [field, raw] of Object.entries(meta.config)) {
        const spec = raw as ConfigSpec;
        if (meta.type !== "start" && canTakeUpstream(spec)) inputs.push(field);
        if (spec.entry_labels === "source_roles") {
          config[field] = [...SOURCE_ROLE_ORDER.map((role) => `{{up.asset_id}}:${role}`), "{{up.asset_ids}}:reference_image", "{{up.asset_ids}}"];
          inputs.push(...(config[field] as string[]).map((_, index) => `${field}.${index}`));
        }
      }
      const node = { id: meta.type, type: meta.type, config };
      const outputs = meta.type === "condition" ? [] : declaredFieldNames(meta.outputs, config);
      return [...problems(meta.type, locale, node, "inputs", inputs), ...problems(meta.type, locale, node, "outputs", outputs)];
    });
    expect(found).toEqual([]);
  });
});

const DIR = join(import.meta.dirname, "../../../../website/public/workflows");
const COPIES = readdirSync(DIR).filter((name) => name.endsWith(".mosael-workflow.json")).sort();

/** 一张图和它里面的每一层体(循环 / 子图)。 */
function layers(graph: WorkflowGraph, path: string[] = []): Array<{ path: string; graph: WorkflowGraph }> {
  return [
    { path: path.join(" / ") || "主流程", graph },
    ...graph.nodes.flatMap((node) =>
      Object.values(node.config ?? {})
        .filter((value): value is WorkflowGraph => Boolean(value && typeof value === "object" && Array.isArray((value as WorkflowGraph).nodes)))
        .flatMap((body) => layers(body, [...path, node.id])),
    ),
  ];
}

describe("官方模板", () => {
  it("中英两份一份都没漏读", () => {
    expect(COPIES.filter((name) => name.includes(".zh.")).length).toBeGreaterThan(5);
    expect(COPIES.filter((name) => name.includes(".en.")).length).toBe(COPIES.filter((name) => name.includes(".zh.")).length);
  });

  //: 每份副本在两种界面语言下各看一遍:中文版的模板放进英文界面,口的名字跟着界面走,不跟着模板走。
  it.each(COPIES.flatMap((name) => LOCALES.map((locale) => [name, locale] as const)))("%s 在 %s 界面上", (name, locale) => {
    const graph = (JSON.parse(readFileSync(join(DIR, name), "utf8")) as { graph: WorkflowGraph }).graph;
    const found = layers(graph).flatMap((layer) =>
      layer.graph.nodes.flatMap((node) => {
        const ports = nodePorts(node, CATALOGS[locale], layer.graph.edges);
        const where = `${layer.path} › ${node.name || node.id}`;
        return [...problems(where, locale, node, "inputs", ports.inputs), ...problems(where, locale, node, "outputs", ports.outputs)];
      }),
    );
    expect(found).toEqual([]);
  });
});
