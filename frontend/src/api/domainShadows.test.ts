import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * 棘轮:**`api/domains/*` 里不许再多一个"生成类型的影子"。**
 *
 * 生成类型这条路的全部价值是"接口一变,前端编译就知道"。而 `api/domains/*` 里同时存在两种
 * 约定:一半写 `type Asset = components["schemas"]["AssetOut"]`,另一半手写一个 interface ——
 * 实测有十四个手写接口和生成类型**字段集合 100% 重合**。
 *
 * 它们今天都是对的,理由和"两个数碰巧相等"一样。后端加一个字段:`schema.d.ts` 长出来,手写那份
 * 不会 —— 前端编译通过、测试全绿,只是那个选项在界面上**不存在**。反方向更糟:后端改窄一个
 * 枚举,前端照旧能构造出旧值,变成一个 422。只要还有第二条手写的路,那个保证就退化成
 * "看谁碰巧用了哪条"。
 *
 * 这次换掉了十个。剩下的每一个都要在 `KEPT_BY_HAND` 里写清**为什么生成类型不够用** ——
 * 多半是后端那一侧把返回声明成了裸 `dict`(没有 `response_model`),生成出来是
 * `{[key: string]: unknown}`,手写这一份是为了拿回类型。那是后端的账,记在这里等着还。
 *
 * 判据是"只减不增":数量上限就是现在这些。少一个要顺手把它从名单里删掉(下面第二条会提醒)。
 */

const DOMAINS = join(import.meta.dirname, "domains");

/** 手写的 `export interface X` → 为什么它不能换成生成类型。 */
const KEPT_BY_HAND: Record<string, string> = {
  "assets.ts:WaveformData": "波形是二进制端点(不是 JSON 出参),没有对应的 schema。",
  "boards.ts:Board":
    "生成的 BoardOut.canvas 是裸 dict(后端 schema 里就是 dict[str, Any]),换过去会把整张画布的" +
    "类型丢成 {} —— 实测换完 BoardsView/BoardCanvas 报出八处 any。要收口得先给 canvas 定 schema。",
  "boards.ts:BoardCanvas": "同上:它就是那个裸 dict 的形状,前端手写这一份是为了拿回类型。",
  "boards.ts:BoardItem": "同上:画布里的一项,它的形状住在那个裸 dict 里。",
  "boards.ts:BoardEdge": "同上:画布里的一条连线,形状同样住在那个裸 dict 里。",
  "boards.ts:BoardMarker": "同上:画布上的一枚标记,形状同样住在那个裸 dict 里。",
  "boards.ts:BoardRunForms":
    "BoardRun.form 是裸 dict:每个产出者的表单由它自己在后端领域里声明、校验(boards/producers.*Form)," +
    "接口不为每个产出者各开一个请求体 —— 产出者是注册表,ADR 0021 的 P2 起插件工具也是产出者。",
  "scenes.ts:SceneModel": "3D 场景的内容是裸 dict(scene.content),同 boards 的账。",
  "scenes.ts:ScenePreviewData": "同上:预览结构由场景内容那个裸 dict 决定。",
  "scenes.ts:PreviewObject": "同上:预览里的一个物体,形状由场景内容决定。",
  "speech.ts:F5Model":
    "对着的 `list_f5_models` 没有 response_model,生成出来是 {[key: string]: unknown}[]。" +
    "这十五个字段此刻和 f5_models.status() 一致,而这份一致**由两边的人手工维持** —— " +
    "补上 response_model 之后这一条就能撤掉。",
  "workflows.ts:WorkflowGraph": "工作流图也是裸 dict(graph),同 boards 的账。",
};

function domainFiles(): string[] {
  return readdirSync(DOMAINS)
    .filter((name) => name.endsWith(".ts") && !name.endsWith(".test.ts"))
    .sort();
}

/** 这些文件里手写的 `export interface` —— `"文件:名字"`。 */
function handwritten(): string[] {
  const found: string[] = [];
  for (const name of domainFiles()) {
    const source = readFileSync(join(DOMAINS, name), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    for (const match of source.matchAll(/^export interface (\w+)/gm)) {
      found.push(`${name}:${match[1]}`);
    }
  }
  return found.sort();
}

describe("api/domains 里的类型来源", () => {
  it("扫描面站得住 —— 确实读到了 domains 下的模块", () => {
    expect(domainFiles().length).toBeGreaterThanOrEqual(18);
  });

  it("手写接口只减不增,而且每个都说得出为什么生成类型不够用", () => {
    expect(
      handwritten(),
      "又多了一个手写接口。生成类型能表达的就用生成类型;真不能(后端返回裸 dict、" +
        "或者形状由外部服务决定),写进 KEPT_BY_HAND 并说明原因。",
    ).toEqual(Object.keys(KEPT_BY_HAND).sort());
  });

  it("名单里没有已经不存在的条目 —— 守一个不存在的约定会掩护下一个同名的", () => {
    const live = new Set(handwritten());
    expect(Object.keys(KEPT_BY_HAND).filter((entry) => !live.has(entry))).toEqual([]);
  });

  it("每条豁免都写了原因", () => {
    for (const [entry, why] of Object.entries(KEPT_BY_HAND)) {
      expect(why.trim().length, `${entry} 没写原因`).toBeGreaterThan(15);
    }
  });
});
