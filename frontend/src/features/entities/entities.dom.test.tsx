/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Entity, EntitySummary } from "@/api/client";

/**
 * 资产库(ADR 0027)的页面:页签 + 封面卡片、详情里的参考图墙(换角度、设封面、排先后、移出、从素材库挂、
 * 拖文件进来导入再挂)、专有字段(真人 / 虚构与授权声明)、「在哪里用过」,以及素材详情里的「属于哪些资产」;
 * 和社区之间:分享(真人要再确认一次)、状态与新版本、从社区导入、导入的真人「授权待你确认」。
 *
 * 接口一律是假的(api/client 整个换掉):判的是**界面发出去的请求**和**拿回来之后画出来的东西**。
 */

const api = vi.hoisted(() => ({
  listEntities: vi.fn(),
  getEntity: vi.fn(),
  createEntity: vi.fn(),
  updateEntity: vi.fn(),
  deleteEntity: vi.fn(),
  createVariant: vi.fn(),
  dismissLostReferences: vi.fn(),
  addEntityReference: vi.fn(),
  setEntityReferenceRole: vi.fn(),
  removeEntityReference: vi.fn(),
  reorderEntityReferences: vi.fn(),
  getEntityUsage: vi.fn(),
  listAssetEntities: vi.fn(),
  getEntityCatalog: vi.fn(),
  importAsset: vi.fn(),
  listAssets: vi.fn(),
  listVoices: vi.fn(),
  listScenes: vi.fn(),
  listSceneModels: vi.fn(),
  getEntityCommunity: vi.fn(),
  getCommunityStatus: vi.fn(),
  publishEntityToCommunity: vi.fn(),
  browseCommunityAssets: vi.fn(),
  importEntityFromCommunity: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  ...api,
  ENTITY_KINDS: ["character", "location", "prop"],
  assetThumbnailUrl: (id: string) => `/thumb/${id}`,
  entityKeys: {
    all: (ws: string) => ["entities", ws],
    list: (ws: string, filters: Record<string, unknown> = {}) => ["entities", ws, "list", filters],
    detail: (ws: string, id: string) => ["entities", ws, "detail", id],
    usage: (ws: string, id: string) => ["entities", ws, "usage", id],
    ofAsset: (ws: string, id: string) => ["entities", ws, "asset", id],
    community: (ws: string, id: string) => ["entities", ws, "community", id],
    catalog: () => ["entity-catalog"],
  },
  entityReceipt: () => [],
  getJob: vi.fn(),
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh" }),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }));

import { EntitiesView } from "./EntitiesView";
import { AssetEntitiesList, SetAsReferenceDialog } from "./AssetEntities";

const CATALOG = {
  kinds: [
    { kind: "character", label: "人物" },
    { kind: "location", label: "场景" },
    { kind: "prop", label: "道具" },
  ],
  roles: [
    { role: "front", label: "正面" },
    { role: "side", label: "侧面" },
    { role: "turnaround", label: "三视图" },
    { role: "concept", label: "设定图" },
  ],
  consent_kinds: [
    { kind: "self", label: "这是我本人", help: "肖像是你自己的" },
    { kind: "authorized", label: "已取得本人同意", help: "取得了本人单独同意" },
    { kind: "fictional", label: "虚构人物", help: "不是任何真实存在的人" },
  ],
  attach_priority: ["turnaround", "front", "full_body"],
  attributes: { character: ["voice_id"], location: [], prop: [] },
};

function summary(over: Partial<EntitySummary> = {}): EntitySummary {
  return {
    id: "e1",
    kind: "character",
    parent_id: null,
    parent_name: "",
    name: "张三",
    cover_asset_id: "a-front",
    tags: ["主角"],
    reference_count: 2,
    variant_count: 1,
    updated_at: "2026-09-27T10:00:00",
    ...over,
  };
}

function entity(over: Partial<Entity> = {}): Entity {
  return {
    id: "e1",
    workspace_id: "ws",
    kind: "character",
    parent_id: null,
    parent_name: "",
    name: "张三",
    description: "主角",
    prompt: "黑色短发",
    cover_asset_id: null,
    display_cover_asset_id: "a-front",
    attributes: { real_person: false },
    tags: ["主角"],
    lost_references: [],
    references: [
      { asset_id: "a-front", role: "front", position: 1, asset_kind: "image", asset_name: "正面.png" },
      { asset_id: "a-side", role: "side", position: 2, asset_kind: "image", asset_name: "侧面.png" },
    ],
    variants: [],
    usable_for_digital_human: true,
    created_at: "2026-09-27T10:00:00",
    updated_at: "2026-09-27T10:00:00",
    ...over,
  };
}

function mount(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const WORKSPACE = { id: "ws", name: "W" } as never;

function communityState(over: Record<string, unknown> = {}) {
  return {
    published: null,
    source: null,
    latest_version: null,
    status: { configured: true, origin: "https://mosael.com", connected: true, handle: "me", display_name: "我" },
    ...over,
  };
}

beforeEach(() => {
  for (const one of Object.values(api)) one.mockReset();
  api.getEntityCatalog.mockResolvedValue(CATALOG);
  api.listAssets.mockResolvedValue([]);
  api.listVoices.mockResolvedValue([]);
  api.listScenes.mockResolvedValue([]);
  api.listSceneModels.mockResolvedValue([]);
  api.getEntityUsage.mockResolvedValue({ boards: [], generations: [], workflows: [] });
  api.getEntityCommunity.mockResolvedValue(communityState());
  api.getCommunityStatus.mockResolvedValue(communityState().status);
  window.location.hash = "#/entities";
  //: 页签记在 localStorage 里(usePersistentTab),上一条测试点过「场景」的话这一条会从场景开始。
  window.localStorage.clear();
  Element.prototype.scrollIntoView ??= () => {};
});
afterEach(cleanup);

describe("资产页", () => {
  it("按人物 / 场景 / 道具分页签,卡片是封面 + 名字 + 张数", async () => {
    api.listEntities.mockResolvedValue([
      summary(),
      summary({ id: "e2", kind: "location", name: "老街", cover_asset_id: null, tags: [], variant_count: 0 }),
    ]);
    mount(<EntitiesView workspace={WORKSPACE} />);
    const card = await screen.findByText("张三");
    const tile = card.closest("[data-entity-card]") as HTMLElement;
    expect(tile.querySelector("img")?.getAttribute("src")).toBe("/thumb/a-front");
    expect(within(tile).getByText(/entityRefCount/)).toBeTruthy();
    expect(screen.queryByText("老街")).toBeNull();

    const tabs = screen.getByRole("group", { name: "entitiesKinds" });
    fireEvent.click(within(tabs).getByRole("button", { name: /场景/ }));
    expect(await screen.findByText("老街")).toBeTruthy();
    expect(screen.queryByText("张三")).toBeNull();
  });

  it("新建一个就打开它的详情", async () => {
    api.listEntities.mockResolvedValue([]);
    api.createEntity.mockResolvedValue(entity({ id: "new", name: "李四", references: [] }));
    api.getEntity.mockResolvedValue(entity({ id: "new", name: "李四", references: [] }));
    mount(<EntitiesView workspace={WORKSPACE} />);
    fireEvent.click((await screen.findAllByRole("button", { name: /entitiesNew/ }))[0]);
    const dialog = await screen.findByRole("dialog");
    const input = within(dialog).getByRole("textbox");
    fireEvent.change(input, { target: { value: "李四" } });
    fireEvent.submit(input.closest("form")!);
    await waitFor(() =>
      expect(api.createEntity).toHaveBeenCalledWith({ workspace_id: "ws", kind: "character", name: "李四" }),
    );
    expect(await screen.findByRole("region", { name: "entityReferences" })).toBeTruthy();
  });
});

describe("资产页的操作", () => {
  const ROWS = [
    summary({ id: "e1", name: "张三", updated_at: "2026-09-27T10:00:00", variant_count: 1 }),
    summary({ id: "e2", name: "阿澄", updated_at: "2026-09-27T12:00:00", variant_count: 0, tags: ["配角"] }),
  ];

  it("右键一张卡片:重命名", async () => {
    api.listEntities.mockResolvedValue(ROWS);
    api.updateEntity.mockResolvedValue(entity());
    mount(<EntitiesView workspace={WORKSPACE} />);
    const card = (await screen.findByText("张三")).closest("[data-entity-tile]") as HTMLElement;
    fireEvent.contextMenu(card);
    fireEvent.click(await screen.findByRole("menuitem", { name: /rename/ }));
    const dialog = await screen.findByRole("dialog");
    const input = within(dialog).getByRole("textbox");
    fireEvent.change(input, { target: { value: "张三丰" } });
    fireEvent.submit(input.closest("form")!);
    await waitFor(() => expect(api.updateEntity).toHaveBeenCalledWith("e1", { name: "张三丰" }));
  });

  it("选择模式:点卡片是选中不是打开,批量删除连变体一起删", async () => {
    api.listEntities.mockResolvedValue(ROWS);
    api.deleteEntity.mockResolvedValue(undefined);
    mount(<EntitiesView workspace={WORKSPACE} />);
    await screen.findByText("张三");
    fireEvent.click(screen.getByRole("button", { name: /mediaSelectMode/ }));
    fireEvent.click(screen.getByText("张三").closest("button")!);
    fireEvent.click(screen.getByText("阿澄").closest("button")!);
    expect(api.getEntity).not.toHaveBeenCalled();
    expect(screen.getByText("mediaSelectedCount")).toBeTruthy();
    const bar = screen.getByRole("group", { name: "mediaSelectMode" });
    fireEvent.click(within(bar).getByRole("button", { name: /delete/ }));
    const dialog = await screen.findByRole("alertdialog").catch(() => screen.findByRole("dialog"));
    expect(dialog.textContent).toContain("entityDeleteWithVariants");
    fireEvent.click(within(dialog).getByRole("button", { name: "delete" }));
    await waitFor(() => expect(api.deleteEntity).toHaveBeenCalledTimes(2));
    expect(api.deleteEntity).toHaveBeenCalledWith("e1", true);
    expect(api.deleteEntity).toHaveBeenCalledWith("e2", false);
  });

  it("默认最近更新的在前", async () => {
    api.listEntities.mockResolvedValue(ROWS);
    mount(<EntitiesView workspace={WORKSPACE} />);
    await screen.findByText("张三");
    const names = [...document.querySelectorAll("[data-entity-tile] strong")].map((one) => one.textContent);
    expect(names).toEqual(["阿澄", "张三"]);
  });
});

describe("参考图墙", () => {
  async function openDetail(over: Partial<Entity> = {}) {
    window.location.hash = "#/entities?entity=e1";
    api.listEntities.mockResolvedValue([summary()]);
    api.getEntity.mockResolvedValue(entity(over));
    mount(<EntitiesView workspace={WORKSPACE} />);
    return screen.findByRole("region", { name: "entityReferences" });
  }

  it("每张标着角度,封面有角标", async () => {
    const wall = await openDetail();
    const front = wall.querySelector('[data-reference="a-front"]') as HTMLElement;
    expect(front.querySelector('[data-reference-role="front"]')?.textContent).toBe("正面");
    expect(within(front).getByText("entityCoverBadge")).toBeTruthy();
    expect(wall.querySelector('[data-reference="a-side"] [data-reference-role="side"]')?.textContent).toBe("侧面");
  });

  it("设封面、往后挪、移出 —— 各发各的请求", async () => {
    api.updateEntity.mockResolvedValue(entity({ cover_asset_id: "a-side", display_cover_asset_id: "a-side" }));
    api.reorderEntityReferences.mockResolvedValue(entity());
    api.removeEntityReference.mockResolvedValue(entity());
    const wall = await openDetail();

    fireEvent.click(within(wall).getByRole("button", { name: "studioActions: 侧面.png" }));
    fireEvent.click(await screen.findByRole("button", { name: "entitySetCover" }));
    await waitFor(() => expect(api.updateEntity).toHaveBeenCalledWith("e1", { cover_asset_id: "a-side" }));

    fireEvent.click(within(wall).getByRole("button", { name: "studioActions: 正面.png" }));
    fireEvent.click(await screen.findByRole("button", { name: "entityMoveLater" }));
    await waitFor(() => expect(api.reorderEntityReferences).toHaveBeenCalledWith("e1", ["a-side", "a-front"]));

    fireEvent.click(within(wall).getByRole("button", { name: "studioActions: 侧面.png" }));
    fireEvent.click(await screen.findByRole("button", { name: "entityRemoveReference" }));
    await waitFor(() => expect(api.removeEntityReference).toHaveBeenCalledWith("e1", "a-side"));
  });

  it("从素材库挑一张挂上;已经挂着的不给再挂", async () => {
    api.listAssets.mockResolvedValue([
      { id: "a-front", kind: "image", name: "正面.png" },
      { id: "a-new", kind: "image", name: "背面.png" },
      { id: "a-song", kind: "audio", name: "歌.mp3" },
    ]);
    api.addEntityReference.mockResolvedValue(entity());
    const wall = await openDetail();
    fireEvent.click(within(wall).getByRole("button", { name: "entityFromLibrary" }));
    const dialog = await screen.findByRole("dialog");
    const library = await within(dialog).findByRole("listbox", { name: "entityLibraryTitle" });
    //: 已经挂着的那张照样列出来,但标着「已挂上」、选不了;音频不是参考图,不列。
    const attached = within(library).getByRole("option", { name: "正面.png" }) as HTMLButtonElement;
    expect(attached.disabled).toBe(true);
    expect(within(attached).getByText("entityLibraryAttached")).toBeTruthy();
    expect(within(library).queryByRole("option", { name: "歌.mp3" })).toBeNull();
    const add = within(dialog).getByRole("button", { name: "entityLibraryAttach" }) as HTMLButtonElement;
    expect(add.disabled).toBe(true);
    fireEvent.click(within(library).getByRole("option", { name: "背面.png" }));
    expect(within(library).getByRole("option", { name: "背面.png" }).getAttribute("aria-selected")).toBe("true");
    fireEvent.click(within(dialog).getByRole("button", { name: "entityLibraryAdd" }));
    await waitFor(() => expect(api.addEntityReference).toHaveBeenCalledWith("e1", { asset_id: "a-new" }));
  });

  it("把图片文件拖到墙上:先导进素材库,再挂成参考图", async () => {
    api.importAsset.mockResolvedValue({ id: "a-dropped", kind: "image", name: "新.png" });
    api.addEntityReference.mockResolvedValue(entity());
    const wall = await openDetail();
    const target = wall.querySelector("[data-reference-drop]") as HTMLElement;
    const file = new File(["x"], "新.png", { type: "image/png" });
    const text = new File(["x"], "说明.pdf", { type: "application/pdf" });
    await act(async () => {
      fireEvent.drop(target, { dataTransfer: { types: ["Files"], files: [file, text], items: [] } });
    });
    await waitFor(() => expect(api.importAsset).toHaveBeenCalledWith({ workspaceId: "ws", file }));
    expect(api.importAsset).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(api.addEntityReference).toHaveBeenCalledWith("e1", { asset_id: "a-dropped" }));
  });

  it("素材删了之后说得出少了哪一张,看过能清掉", async () => {
    api.dismissLostReferences.mockResolvedValue(entity());
    await openDetail({ lost_references: [{ name: "正脸.png", role: "front", at: "2026-09-27T10:00:00+00:00" }] });
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("entityLostReferences");
    fireEvent.click(within(alert).getByRole("button", { name: "entityDismiss" }));
    await waitFor(() => expect(api.dismissLostReferences).toHaveBeenCalledWith("e1"));
  });
});

describe("真人 / 虚构与授权声明", () => {
  it("每个选项写着它是什么意思;选中发的是种类,不替服务端记是谁", async () => {
    window.location.hash = "#/entities?entity=e1";
    api.listEntities.mockResolvedValue([summary()]);
    api.getEntity.mockResolvedValue(entity({ attributes: { real_person: true }, usable_for_digital_human: false }));
    api.updateEntity.mockResolvedValue(entity());
    mount(<EntitiesView workspace={WORKSPACE} />);
    fireEvent.click(await screen.findByRole("button", { name: "entitySettings" }));
    const consent = await screen.findByRole("radiogroup", { name: "entityConsentTitle" });
    expect(consent.textContent).toContain("肖像是你自己的");
    expect(consent.textContent).toContain("取得了本人单独同意");
    expect(consent.textContent).not.toContain("虚构人物");
    expect(screen.getByText("entityDigitalHumanBlocked")).toBeTruthy();
    fireEvent.click(within(consent).getByRole("radio", { name: /这是我本人/ }));
    await waitFor(() =>
      expect(api.updateEntity).toHaveBeenCalledWith("e1", { attributes: { real_person: true, consent: { kind: "self" } } }),
    );
  });
});

describe("在哪里用过", () => {
  it("画板、生成记录、工作流各一行", async () => {
    window.location.hash = "#/entities?entity=e1";
    api.listEntities.mockResolvedValue([summary()]);
    api.getEntity.mockResolvedValue(entity());
    api.getEntityUsage.mockResolvedValue({
      boards: [{ id: "b1", name: "分镜板", how: "cell" }],
      generations: [{ id: "g1", session_id: null, kind: "image", model: "seedream", prompt: "街口", result_asset_id: null, created_at: "2026-09-27T10:00:00" }],
      workflows: [{ id: "w1", name: "出图流程" }],
    });
    mount(<EntitiesView workspace={WORKSPACE} />);
    fireEvent.click(await screen.findByRole("button", { name: "entityUsage" }));
    const usage = await screen.findByRole("region", { name: "entityUsage" });
    await within(usage).findByText("分镜板");
    expect(within(usage).getByText("entityUsageCell")).toBeTruthy();
    expect(within(usage).getByText("街口")).toBeTruthy();
    expect(within(usage).getByText("出图流程")).toBeTruthy();
  });
});

describe("素材这一侧", () => {
  it("素材详情里列出它属于哪些资产", async () => {
    api.listAssetEntities.mockResolvedValue([
      { id: "e1", kind: "character", name: "张三", parent_id: null, parent_name: "", role: "front" },
      { id: "e2", kind: "character", name: "冬装", parent_id: "e1", parent_name: "张三", role: "side" },
    ]);
    mount(<AssetEntitiesList asset={{ id: "a1", workspace_id: "ws" }} />);
    await screen.findByText("张三 · 冬装");
    expect(screen.getByText("正面")).toBeTruthy();
    fireEvent.click(screen.getByText("张三"));
    expect(window.location.hash).toBe("#/entities?entity=e1");
  });

  it("右键「设为某个资产的参考图…」:挑资产、挑角度、顺手设封面", async () => {
    api.listEntities.mockResolvedValue([summary(), summary({ id: "e2", kind: "location", name: "老街" })]);
    api.addEntityReference.mockResolvedValue(entity());
    const asset = { id: "a9", workspace_id: "ws", kind: "image", name: "侧脸.png" } as never;
    mount(<SetAsReferenceDialog asset={asset} onClose={() => {}} />);
    await waitFor(() => expect(api.listEntities).toHaveBeenCalled());
    const picker = await screen.findByRole("combobox", { name: "entityPickTitle" });
    await waitFor(() => expect(picker.hasAttribute("disabled")).toBe(false));
    fireEvent.keyDown(picker, { key: "Enter" });
    fireEvent.click(await screen.findByRole("option", { name: "人物 · 张三" }));
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "confirm" }));
    await waitFor(() =>
      expect(api.addEntityReference).toHaveBeenCalledWith("e1", { asset_id: "a9", role: "front", cover: true }),
    );
  });
});

describe("AI 工作台的 @ 资产", () => {
  it("挑中的排成 chip,交出去的是资产;行和画板 @ 菜单同一种长相", async () => {
    const { EntityMentionPicker } = await import("./EntityMention");
    api.listEntities.mockResolvedValue([summary(), summary({ id: "e2", name: "老街", kind: "location" })]);
    const onChange = vi.fn();
    const view = mount(<EntityMentionPicker workspaceId="ws" value={[]} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "entityMention" }));
    fireEvent.click(await screen.findByText("老街"));
    expect(onChange).toHaveBeenCalledWith([expect.objectContaining({ id: "e2" })]);
    view.unmount();

    const removed = vi.fn();
    mount(<EntityMentionPicker workspaceId="ws" value={[summary()]} onChange={removed} />);
    expect(screen.getByText("@张三")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "entityMentionRemove" }));
    expect(removed).toHaveBeenCalledWith([]);
  });

  it("挂不全参考图时说清楚挂了几张、为什么;全挂上的不说", async () => {
    const { receiptLines } = await import("./entityMeta");
    const lines = receiptLines(
      [
        { id: "e1", name: "张三", kind: "character", attached: ["a", "b"], dropped: ["c"], notes: ["limit"] },
        { id: "e2", name: "老街", kind: "location", attached: ["d"], dropped: [], notes: [] },
      ],
      (key) => key,
    );
    expect(lines).toEqual(["entityReceiptLine —— entityNote_limit"]);
  });
});
