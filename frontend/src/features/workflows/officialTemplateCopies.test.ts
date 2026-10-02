/**
 * 官方模板打开就是一张连好的图:画布的就绪检查里没有「未连接到流程」的节点。
 *
 * 查的是官网副本(website/public/workflows,由 scripts/sync-website-workflows.py 从后端真建出来的图导出,应用里
 * 建的是同一张)。
 *
 * 现场:「从主题到完整视频」的「可用的 3D 道具」一条连线都没有,画布上挂着黄色角标(disconnected),而引擎也真的
 * 不跑它(顶层只有开始节点是入口)—— 官方模板一打开就带着一个警告,布景师拿到的道具清单永远是空的。
 *
 * 跑的是画布自己的 analyzeWorkflow。节点目录在后端,这里给的是「每种节点都认得」的一份:字段级的检查(必填、
 * 失效引用、数据边的类型)由后端的 tests/test_official_templates_hold_together 按真目录查,这里守连线本身。
 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import type { WorkflowGraph } from "@/api/client";
import { analyzeWorkflow, type AnalyzeContext, type RegistryLike } from "@/features/workflows/analyze";

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单。
export const RATCHET = true;

const DIR = join(import.meta.dirname, "../../../../website/public/workflows");
const COPIES = readdirSync(DIR).filter((name) => name.endsWith(".mosael-workflow.json")).sort();

const EVERY_TYPE_KNOWN: RegistryLike = { get: () => ({ config: {} }) };
const NOTHING_LOADED: AnalyzeContext = {
  chatProfileIds: new Set(),
  chatProfilesLoaded: false,
  generationVendors: new Set(),
  generationModelsLoaded: false,
};

describe("官方模板的官网副本", () => {
  it("一份都没漏读", () => {
    // 中英各一份;目录读空了,下面那条就什么都没测。
    expect(COPIES.length).toBeGreaterThanOrEqual(2);
  });

  it.each(COPIES)("%s:每个节点都从开始节点连得到", (name) => {
    const graph = (JSON.parse(readFileSync(join(DIR, name), "utf8")) as { graph: WorkflowGraph }).graph;
    const { issues } = analyzeWorkflow(graph, EVERY_TYPE_KNOWN, NOTHING_LOADED);
    const unwired = issues.filter((issue) => issue.code === "disconnected" || issue.code === "missing-start");
    expect(unwired.map((issue) => `${issue.nodeName}(${issue.nodeId})`)).toEqual([]);
  });
});
