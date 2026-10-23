/** @vitest-environment jsdom */
/**
 * **「一次挑一组素材」的字段,画出来都是那一个共用的格子控件。**
 *
 * 这条用的是**后端导出的真声明**(`@/test/nodeCatalog` 的 SNAPSHOT —— 由后端
 * `backend/scripts/export_openapi.py` 生成、后端测试守它的新鲜度),不是手抄的替身:谁给这种字段换回
 * 一个自绘的控件、或新加一个这种字段却忘了声明 `editor: "asset_grid"`,这里就红。
 *
 * 判据和后端那道棘轮(backend/tests/test_asset_group_fields_use_the_shared_grid.py)同一条:
 * 值是一串素材的(`asset_ids` / `image_asset_ids`)或一行一条 `素材id:角色` 的(`lines`)。
 * 单份素材(`asset_id`)不在内 —— 那是「挑一份」。
 *
 * 还钉住**声明决定的那几样**:值编码(逗号串 / 行的列表)、有没有角色角标、收哪几类素材
 * (`media`:要模型看的图片只收图,实体保存那格图片和视频都收,打标签 / 素材更新那两格什么都收)。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render } from "@testing-library/react";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  assetThumbnailUrl: (id: string) => `/thumb/${id}`,
}));

const uploadMock = vi.hoisted(() => ({
  state: { status: "idle" } as { status: "idle" },
  start: vi.fn(),
  reject: vi.fn(),
  retry: vi.fn(),
  cancel: vi.fn(),
  dismiss: vi.fn(),
}));
vi.mock("@/components/generation/assetUpload", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/generation/assetUpload")>()),
  useAssetUpload: () => uploadMock,
}));

vi.mock("@/lib/assetQueries", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/assetQueries")>()),
  useAssetDetails: () => ({ byId: new Map(), settled: true }),
  useAssetSearch: () => ({
    text: "", search: vi.fn(), items: [], isLoading: false, isError: false, error: null,
    hasNextPage: false, isFetchingNextPage: false, fetchNextPage: vi.fn(), refetch: vi.fn(),
  }),
}));

import type { WorkflowNodeType } from "@/api/client";
import {
  NodeConfigForm,
  type ConfigSpec,
  type FieldBinding,
  type NodeFieldOptions,
} from "@/features/nodeForms/NodeConfigForm";
import { SNAPSHOT, builtinNodeCatalog } from "@/test/nodeCatalog";

const CATALOG = builtinNodeCatalog("zh");

/** 「一次挑一组素材」的字段:名字以 `asset_ids` 结尾,或声明了 `lines`(判据见模块开头)。 */
const GROUP_FIELDS = SNAPSHOT.flatMap((node) =>
  Object.entries(node.config)
    .filter(([key, spec]) => key.endsWith("asset_ids") || Boolean(spec.lines))
    .map(([key, spec]) => ({ node: node.type, key, spec })),
);

const FIELD_OPTIONS: NodeFieldOptions = {
  dynamicOptions: () => null,
  whyEmpty: () => ({ kind: "none" }),
  assets: [],
};

const BINDING: FieldBinding = { isBound: () => false, setBound: () => {}, renderBound: () => null };

function renderField(nodeType: string, key: string, value: unknown, onChange = vi.fn(), binding?: FieldBinding) {
  const meta = CATALOG.get(nodeType) as WorkflowNodeType;
  const spec = meta.config[key] as ConfigSpec;
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <NodeConfigForm
        fields={[[key, spec]]}
        config={{ [key]: value }}
        workspaceId="w1"
        variables={[]}
        fieldOptions={FIELD_OPTIONS}
        onSetConfig={onChange}
        onTypeConfig={onChange}
        onPatchConfig={vi.fn()}
        assetGridModels={{ source_assets: { accepted: ["reference_image"], limits: { reference_image: 9 } } }}
        binding={binding}
        references
      />
    </QueryClientProvider>,
  );
  return { onChange };
}

beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

describe("「一次挑一组素材」的字段都走共用的格子控件(真声明)", () => {
  it("判据找得到那几个字段(空转的棘轮等于没有)", () => {
    expect(GROUP_FIELDS.map((one) => `${one.node}.${one.key}`)).toEqual([
      "ai_generate.source_assets",
      "asset_tag.asset_ids",
      "asset_update.asset_ids",
      "entity_save.asset_ids",
      "llm.image_asset_ids",
      //: 发布节点的图文 / 文章素材(ADR 0076):同一组图片、同一个格子、顺序就是发出去的顺序。
      "publish.asset_ids",
    ]);
  });

  it.each(GROUP_FIELDS.map((one) => [`${one.node}.${one.key}`, one.node, one.key, one.spec] as const))(
    "%s 画的是共用的格子(不是自绘的下拉 / 文本框)",
    (_label, nodeType, key, spec) => {
      renderField(nodeType, key, spec.lines ? ["img-a:reference_image"] : "img-a");
      const field = document.querySelector("[data-asset-grid]");
      expect(field).not.toBeNull();
      //: 值编码照声明:`lines` 的是一行一条 `素材id:角色`,其余是逗号分隔的素材 id 串。
      expect(field!.getAttribute("data-asset-grid-mode")).toBe(spec.lines ? "lines" : "ids");
      //: 角色角标只在声明了角色词表的那一格里出现(生成节点的「输入素材」)。
      const badged = field!.querySelector("[data-role-badge]");
      expect(Boolean(badged)).toBe(spec.entry_labels === "source_roles");
    },
  );
});

describe("收哪几类素材:声明说了算", () => {
  const chooser = () => document.querySelector<HTMLInputElement>("[data-asset-grid-chooser]")!;

  it("「要模型看的图片」只收图片", () => {
    renderField("llm", "image_asset_ids", "");
    expect(chooser().accept).toBe("image/*");
  });

  it("实体保存的「素材列表」图片和视频都收(挂成参考图的那一格)", () => {
    renderField("entity_save", "asset_ids", "");
    expect(chooser().accept).toBe("image/*,video/*");
  });

  it("打标签 / 素材更新那两格没声明 media:图片、视频、音频都收", () => {
    renderField("asset_tag", "asset_ids", "");
    expect(chooser().accept).toBe("image/*,video/*,audio/*");
    cleanup();
    renderField("asset_update", "asset_ids", "");
    expect(chooser().accept).toBe("image/*,video/*,audio/*");
  });
});

describe("值编码:同一份声明两处消费", () => {
  it("大模型那一格写回逗号分隔的素材 id 串", () => {
    const { onChange } = renderField("llm", "image_asset_ids", "img-a");
    fireEvent.click(document.querySelector("[data-upload-tile]")!);
    const file = new File(["x"], "new.png", { type: "image/png" });
    fireEvent.change(chooser(), { target: { files: [file] } });
    const done = uploadMock.start.mock.calls[0][1] as (asset: { id: string; kind: string }) => void;
    done({ id: "fresh-1", kind: "image" });
    expect(onChange).toHaveBeenCalledWith("image_asset_ids", "img-a,fresh-1");
  });

  it("生成节点那一格写回的是**行的列表**,新挑的一份带上角色(默认「参考图」)", () => {
    const { onChange } = renderField("ai_generate", "source_assets", ["img-a:first_frame"]);
    const file = new File(["x"], "new.png", { type: "image/png" });
    fireEvent.change(chooser(), { target: { files: [file] } });
    const done = uploadMock.start.mock.calls[0][1] as (asset: { id: string; kind: string }) => void;
    done({ id: "fresh-1", kind: "image" });
    expect(onChange).toHaveBeenCalledWith("source_assets", ["img-a:first_frame", "fresh-1:reference_image"]);
  });

  function chooser(): HTMLInputElement {
    return document.querySelector<HTMLInputElement>("[data-asset-grid-chooser]")!;
  }
});

describe("接了上游的那一半还在", () => {
  it("整格能接上游(数据边):「连接 / 手动」那个开关照样在", () => {
    renderField("ai_generate", "source_assets", ["img-a:reference_image"], vi.fn(), BINDING);
    expect(document.querySelector("[data-asset-grid]")).not.toBeNull();
    expect(document.querySelector("[data-input-mode]")).not.toBeNull();
  });
});
