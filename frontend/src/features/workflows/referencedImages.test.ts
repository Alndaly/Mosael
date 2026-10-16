import { describe, expect, it } from "vitest";

import type { WorkflowGraph } from "@/api/client";
import type { ConfigSpec } from "@/features/nodeForms/NodeConfigForm";
import { referencedImages } from "@/features/workflows/referencedImages";

/**
 * 「引用即发送」里**哪几处引用**会成为图片(界面那一半;拿哪几张图在后端 binding.with_referenced_assets)。
 * 和运行时同一条线:引用落在**不可能装素材**的输出上(`{{llm.text}}` / `{{q.count}}`)不算 ——
 * 那些引用本来就只是文字,把它们列出来只会让人以为模型会看到一张图。
 */

const SPECS: Record<string, ConfigSpec> = {
  prompt: { type: "template" },
  system: { type: "template" },
  image_asset_ids: { type: "template", media: ["image"], editor: "asset_grid", ref_assets_from: ["prompt", "system"] },
};

type Meta = { config?: Record<string, unknown>; outputs?: string[]; output_types?: Record<string, string> };

const register = (metas: Record<string, Meta>) => ({
  get: (type: string) => metas[type] as never,
});

const REGISTRY = register({
  llm: { output_types: { text: "text", json: "json" } },
  asset: { output_types: { asset_id: "asset", name: "text", kind: "any" } },
  ai_generate: { output_types: { asset_id: "asset" } },
  query: { output_types: { count: "number", ids: "json" } },
  //: `scene` 不在前端的软类型集合里(outputType 会把它归一成 any),但声明里就是它 —— 和 text 一样
  //: 不可能装素材,读**原样的声明值**才判得出来(两边同一个集合)。
  scene: { output_types: { scene_id: "scene" } },
  image_grid_split: { output_types: {} },
});

const graph = (...nodes: Array<[string, string, Record<string, unknown>]>) =>
  nodes.map(([id, type, config]) => ({ id, type, config, position: { x: 0, y: 0 } })) as unknown as readonly WorkflowGraph["nodes"][number][];

const nodes = graph(
  ["pic", "asset", { asset_id: "img-a" }],
  ["clip", "asset", { asset_id: "clip-v" }],
  ["shot", "ai_generate", {}],
  ["ask", "llm", {}],
  //: 注册表里没有它的类型(插件没在这个目录快照里):它的输出口是什么类型无从判断。
  ["plugin", "plugin.demo.tool", {}],
  ["sc", "scene", {}],
);

describe("哪几处引用会成为图片", () => {
  it("提示词里引用素材的输出 → 一处;静态知道是「素材」节点时连素材 id 一起给出来", () => {
    const found = referencedImages(SPECS, { prompt: "看图 {{pic.asset_id}}" }, REGISTRY, nodes);
    expect(found).toEqual({ image_asset_ids: [{ path: "pic.asset_id", assetId: "img-a" }] });
  });

  it("系统提示词里的引用也算,排在提示词那几处后面(和运行时的顺序一致)", () => {
    const found = referencedImages(
      SPECS,
      { prompt: "{{shot.asset_id}} 和 {{pic.asset_id}}", system: "再看 {{pic.asset_id}}" },
      REGISTRY,
      nodes,
    );
    expect(found.image_asset_ids.map((one) => one.path)).toEqual(["shot.asset_id", "pic.asset_id"]);
  });

  it("同一个引用写两遍只算一次", () => {
    const found = referencedImages(SPECS, { prompt: "{{pic.asset_id}} 与 {{pic.asset_id}}" }, REGISTRY, nodes);
    expect(found.image_asset_ids).toEqual([{ path: "pic.asset_id", assetId: "img-a" }]);
  });

  it("引用了文字 / 数字 / JSON / 场景输出:不算(它本来就只是文字或一张场景的名字)", () => {
    const found = referencedImages(
      SPECS,
      { prompt: "叫 {{pic.name}},一共 {{query.count}} 条,{{query.ids}}", system: "{{ask.text}} {{sc.scene_id}}" },
      REGISTRY,
      nodes,
    );
    expect(found).toEqual({});
  });

  it("输出没声明类型的(插件节点、认不出的输出)留着:值到运行时才判得了", () => {
    const found = referencedImages(SPECS, { prompt: "{{plugin.result}}" }, REGISTRY, nodes);
    expect(found.image_asset_ids).toEqual([{ path: "plugin.result", assetId: null }]);
  });

  it("引用了图里没有的节点:不算(运行时那是一段空)", () => {
    expect(referencedImages(SPECS, { prompt: "{{gone.asset_id}}" }, REGISTRY, nodes)).toEqual({});
  });

  it("没有引用的字段不出现;没声明 ref_assets_from 的字段也不出现", () => {
    expect(referencedImages(SPECS, { prompt: "随便写点什么" }, REGISTRY, nodes)).toEqual({});
    expect(referencedImages({ image_asset_ids: { type: "template" } }, { prompt: "{{pic.asset_id}}" }, REGISTRY, nodes)).toEqual({});
  });
});
