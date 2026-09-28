/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { BoardItem, EntitySummary, GenerationOption } from "@/api/client";

/**
 * 画板上的**资产格**(ADR 0027):封面、名字、种类角标;资产删了写明「资产已删除」、那一格照样在。
 * 它连进生成格时,面板把它排进 `@` 菜单的「连进来的」那一组;正文里 `@` 的资产随提交一起交出去
 * (连进来的资产格由服务端按连线并进去,见后端 boards/actions.upstream_entities)。
 */

const api = vi.hoisted(() => ({ getEntity: vi.fn(), listEntities: vi.fn(), listAssets: vi.fn(async () => []), listCapabilityModels: vi.fn() }));
vi.mock("@/api/client", async () => ({
  ...api,
  ApiError: (await import("@/api/transport")).ApiError,
  assetThumbnailUrl: (id: string) => `/thumb/${id}`,
  assetPreviewUrl: (id: string) => `/preview/${id}`,
  assetFileUrl: (id: string) => `/file/${id}`,
  getJob: vi.fn(),
  isNodeProducer: () => false,
  entityKeys: {
    detail: (ws: string, id: string) => ["entities", ws, "detail", id],
    list: (ws: string, filters: Record<string, unknown> = {}) => ["entities", ws, "list", filters],
    catalog: () => ["entity-catalog"],
  },
  getEntityCatalog: async () => ({
    kinds: [{ kind: "character", label: "人物" }, { kind: "location", label: "场景" }],
    roles: [],
    consent_kinds: [],
    attach_priority: [],
    attributes: {},
  }),
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "zh" }) }));
vi.mock("@xyflow/react", () => ({
  Handle: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  NodeResizer: () => null,
  NodeToolbar: ({ children }: { children: React.ReactNode }) => children,
  Position: { Left: "left", Right: "right", Bottom: "bottom" },
  useStore: (selector: (state: { transform: [number, number, number] }) => unknown) => selector({ transform: [0, 0, 1] }),
}));
vi.mock("@/components/app/asset-preview", () => ({ AssetInlinePreview: () => <div /> }));
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: vi.fn() }) }));
vi.mock("@/features/boards/BoardPlayer", () => ({ BoardAudio: () => <div />, BoardVideo: () => <div /> }));

const editorProps = vi.hoisted(() => ({ current: null as null | Record<string, unknown> }));
vi.mock("./PromptEditor", () => ({
  PromptEditor: (props: Record<string, unknown>) => {
    editorProps.current = props;
    return <div data-testid="prompt-editor" />;
  },
  restorePromptDocument: vi.fn(),
  textDocument: vi.fn(),
  collect: () => [],
}));

import { ApiError } from "@/api/transport";
import { BOARD_NODE_TYPES } from "./boardNodes";
import { NodeComposer } from "./NodeComposer";
import { NoteComposer } from "./NoteComposer";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function mount(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function renderCell(item: BoardItem) {
  const Node = BOARD_NODE_TYPES.entity;
  const props = {
    id: item.id,
    selected: false,
    data: { item, workspaceId: "ws", onText: vi.fn(), onAspect: vi.fn() },
  } as unknown as React.ComponentProps<typeof Node>;
  return mount(<Node {...props} />);
}

describe("资产格", () => {
  it("封面、名字、种类角标", async () => {
    api.getEntity.mockResolvedValue({
      id: "e1", kind: "character", name: "张三", display_cover_asset_id: "cover-1",
    });
    const view = renderCell({ id: "cell", kind: "entity", x: 0, y: 0, entity_id: "e1" });
    await screen.findAllByText("张三");
    expect(api.getEntity).toHaveBeenCalledWith("e1");
    expect(view.container.querySelector("img")?.getAttribute("src")).toBe("/thumb/cover-1");
    await waitFor(() => expect(view.container.querySelector('[data-board-entity-kind="character"]')?.textContent).toContain("人物"));
    fireEvent.click(screen.getByRole("button", { name: "boardEntityOpen" }));
    expect(window.location.hash).toBe("#/entities?entity=e1");
  });

  it("资产删了(404):那一格还在,写明已删除;别的错说没能加载,不说删了", async () => {
    api.getEntity.mockRejectedValue(new ApiError("Not Found", 404, ""));
    const gone = renderCell({ id: "cell", kind: "entity", x: 0, y: 0, entity_id: "gone" });
    expect(await screen.findByText("boardEntityMissing")).toBeTruthy();
    gone.unmount();
    api.getEntity.mockRejectedValue(new ApiError("Internal Server Error", 500, ""));
    renderCell({ id: "cell", kind: "entity", x: 0, y: 0, entity_id: "flaky" });
    expect(await screen.findByText("boardEntityLoadFailed")).toBeTruthy();
    expect(screen.queryByText("boardEntityMissing")).toBeNull();
  });

  it("挂在它身上的能力(生成表情)在跑:外壳是在跑的样子,底边一条运行态带停止;跑挂了选中时说原因", async () => {
    api.getEntity.mockResolvedValue({ id: "e1", kind: "character", name: "张三", display_cover_asset_id: null });
    const onStop = vi.fn();
    const Node = BOARD_NODE_TYPES.entity;
    const running: BoardItem = { id: "cell", kind: "entity", x: 0, y: 0, entity_id: "e1", run: { status: "running", job_id: "j", ability: "node:entity_expressions" } };
    const view = mount(<Node {...({ id: "cell", selected: false, data: { item: running, workspaceId: "ws", onStop, abilityLabel: "生成表情" } } as unknown as React.ComponentProps<typeof Node>)} />);
    const shell = view.container.querySelector<HTMLElement>("[data-board-entity]")!;
    expect(shell.dataset.boardRunStatus).toBe("running");
    const strip = view.container.querySelector<HTMLElement>('[data-board-ability-run="running"]');
    expect(strip, "能力在跑有运行条").not.toBeNull();
    expect(strip!.textContent).toContain("生成表情");
    fireEvent.click(strip!.querySelector<HTMLElement>("[data-board-stop]")!);
    expect(onStop).toHaveBeenCalledWith("cell");
    view.unmount();

    const failed: BoardItem = { ...running, run: { status: "failed", error: "没有能画的连接", ability: "node:entity_expressions" } };
    const after = mount(<Node {...({ id: "cell", selected: true, data: { item: failed, workspaceId: "ws" } } as unknown as React.ComponentProps<typeof Node>)} />);
    expect(after.container.querySelector('[data-board-ability-run="failed"]')?.textContent).toContain("没有能画的连接");
  });
});

describe("生成格上的 @资产", () => {
  const model = {
    id: "m", provider_profile_id: "p", profile_name: "T", label: "L", adapter_available: true, is_default: true,
    capabilities_known: true, provider: "test", model: "img", kind: "image", capabilities: {},
  } as GenerationOption;

  it("连进来的资产格排进 @ 菜单的「连进来的」一组;正文里 @ 的资产随提交交出去", async () => {
    const zhang = { id: "e1", kind: "character", name: "张三", parent_name: "" } as EntitySummary;
    api.listEntities.mockResolvedValue([zhang]);
    const onSubmit = vi.fn();
    const onFormChange = vi.fn();
    mount(
      <NodeComposer
        item={{ id: "img", kind: "image", x: 0, y: 0 } as BoardItem}
        models={[model]}
        busy={false}
        workspaceId="ws"
        onPickAsset={vi.fn()}
        onFormChange={onFormChange}
        onSubmit={onSubmit}
        upstreamEntities={["e-street"]}
      />,
    );
    await waitFor(() => expect(editorProps.current).not.toBeNull());
    expect(editorProps.current!.linkedEntities).toEqual(["e-street"]);
    //: 候选随清单到货变 —— 每次取最新的那个回调。
    const candidates = () => editorProps.current!.entities as (query: string) => EntitySummary[];
    await waitFor(() => expect(candidates()("张").map((one) => one.id)).toEqual(["e1"]));

    const onChange = editorProps.current!.onChange as (text: string, assets: string[], doc: unknown, entities: string[]) => void;
    act(() => onChange("张三站在街口", [], { type: "doc", content: [] }, ["e1"]));
    await waitFor(() =>
      expect(onFormChange).toHaveBeenLastCalledWith(expect.objectContaining({ mentioned_entity_ids: ["e1"] })),
    );
    fireEvent.click(screen.getByRole("button", { name: "boardGenerate" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ entityIds: ["e1"] })));
  });

  it("连进来的资产在上面那一排摆出来 —— 连上了看得见,不是悄悄生效", async () => {
    const street = { id: "e-street", kind: "location", name: "竹林小径", parent_name: "", cover_asset_id: "c1" } as EntitySummary;
    api.listEntities.mockResolvedValue([street]);
    mount(
      <NodeComposer
        item={{ id: "img", kind: "image", x: 0, y: 0 } as BoardItem}
        models={[model]}
        busy={false}
        workspaceId="ws"
        onPickAsset={vi.fn()}
        onFormChange={vi.fn()}
        onSubmit={vi.fn()}
        upstreamEntities={["e-street"]}
      />,
    );
    const chip = await waitFor(() => {
      const found = document.querySelector('[data-linked-entity="e-street"]');
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });
    expect(chip.textContent).toContain("竹林小径");
    expect(chip.getAttribute("title")).toBe("boardLinkedEntityHint");
  });
});


describe("便签、文档格的「让 AI 写」认资产", () => {
  const chat = [{ provider_profile_id: "p", model: "k3", display_name: "K3" }];

  it("连进来的资产摆在上面那一排;正文里 @ 的资产随提交交出去", async () => {
    const zhang = { id: "e1", kind: "character", name: "小美", parent_name: "", cover_asset_id: "c1" } as EntitySummary;
    const street = { id: "e2", kind: "location", name: "竹林小径", parent_name: "", cover_asset_id: null } as EntitySummary;
    api.listEntities.mockResolvedValue([zhang, street]);
    api.listCapabilityModels.mockResolvedValue(chat);
    const onWrite = vi.fn(async () => undefined);
    mount(
      <NoteComposer
        item={{ id: "n1", kind: "note", x: 0, y: 0 } as BoardItem}
        busy={false}
        workspaceId="ws"
        upstreamEntities={["e1"]}
        onWrite={onWrite}
        onFormChange={vi.fn()}
      />,
    );
    const chip = await waitFor(() => {
      const found = document.querySelector('[data-linked-entity="e1"]');
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });
    expect(chip.textContent).toContain("小美");
    await waitFor(() => expect(editorProps.current!.linkedEntities).toEqual(["e1"]));
    const onChange = editorProps.current!.onChange as (text: string, assets: string[], doc: unknown, entities: string[]) => void;
    act(() => onChange("写一段她们在竹林里的对话", [], { type: "doc", content: [] }, ["e2"]));
    await waitFor(() => expect(document.querySelector('[data-linked-entity="e2"]')).not.toBeNull());
    fireEvent.click(await screen.findByRole("button", { name: "boardWrite" }));
    await waitFor(() => expect(onWrite).toHaveBeenCalledWith(expect.objectContaining({ entityIds: ["e2"] })));
  });

  it("文档格:没引用笔记是「写一篇」,引用着的是「改这篇」", async () => {
    api.listEntities.mockResolvedValue([]);
    api.listCapabilityModels.mockResolvedValue(chat);
    const props = { busy: false, workspaceId: "ws", onWrite: vi.fn(async () => undefined), onFormChange: vi.fn() };
    mount(<NoteComposer {...props} item={{ id: "d1", kind: "document", x: 0, y: 0 } as BoardItem} />);
    await waitFor(() => expect(editorProps.current!.placeholder).toBe("boardWriteDocumentPlaceholder"));
    cleanup();
    mount(<NoteComposer {...props} item={{ id: "d2", kind: "document", x: 0, y: 0, note_id: "n", note_revision: 2 } as BoardItem} />);
    await waitFor(() => expect(editorProps.current!.placeholder).toBe("boardRewriteDocumentPlaceholder"));
  });
});
