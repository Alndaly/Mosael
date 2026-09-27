/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import type { Editor } from "@tiptap/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Asset, EntitySummary } from "@/api/client";

/**
 * 提示词框的 `@` 菜单里**同时**有资产(ADR 0027)和素材:一个菜单、一套键盘和筛选。
 * 连进这一格的资产格排在「连进来的」那一组;挑一个资产落成资产 chip,交出去的是资产 id,
 * 正文里写的是它的名字(变体是「母体 · 变体」)。
 */

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/api/client", () => ({
  assetThumbnailUrl: (id: string) => `/thumb/${id}`,
  entityKeys: { catalog: () => ["entity-catalog"] },
  getEntityCatalog: async () => ({
    kinds: [{ kind: "character", label: "人物" }, { kind: "location", label: "场景" }],
    roles: [],
    consent_kinds: [],
    attach_priority: [],
    attributes: {},
  }),
}));
vi.mock("@floating-ui/dom", () => ({
  offset: vi.fn(),
  flip: vi.fn(),
  shift: vi.fn(),
  autoUpdate: (_reference: unknown, _element: unknown, update: () => void) => {
    update();
    return () => {};
  },
  computePosition: () => Promise.resolve({ x: 10, y: 10 }),
}));

import { PromptEditor, collectEntities } from "./PromptEditor";

afterEach(cleanup);

const ZHANG: EntitySummary = {
  id: "e-zhang", kind: "character", parent_id: null, parent_name: "", name: "张三", cover_asset_id: "cover-1",
  tags: [], reference_count: 3, variant_count: 1, updated_at: "2026-09-27T10:00:00",
};
const WINTER: EntitySummary = { ...ZHANG, id: "e-winter", parent_id: "e-zhang", parent_name: "张三", name: "冬装", variant_count: 0 };
const STREET: EntitySummary = { ...ZHANG, id: "e-street", kind: "location", name: "老街", cover_asset_id: null };
const PHOTO = { id: "a-photo", kind: "image", name: "海报.png", original_filename: "海报.png" } as Asset;

function mount(onChange = vi.fn(), linkedEntities: string[] = []) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <PromptEditor
        value=""
        onChange={onChange}
        placeholder="写点什么"
        candidates={(query) => [PHOTO].filter((one) => one.name.includes(query))}
        entities={(query) => [ZHANG, WINTER, STREET].filter((one) => `${one.parent_name}${one.name}`.includes(query))}
        linkedEntities={linkedEntities}
        onSubmit={vi.fn()}
        emptyHint={() => ""}
      />
    </QueryClientProvider>,
  );
  const dom = view.container.querySelector(".ProseMirror") as HTMLElement & { editor?: Editor };
  return { view, editor: dom.editor as Editor, onChange };
}

async function typeAt(editor: Editor, text: string) {
  await act(async () => {
    editor.commands.focus();
    editor.commands.insertContent(text);
  });
}

function menuRows(): HTMLElement[] {
  return [...document.querySelectorAll<HTMLElement>("[data-suggestion-menu] button[data-mention]")];
}

describe("@ 菜单里有资产", () => {
  it("资产和素材在同一个菜单里,资产库一组在素材库前面", async () => {
    const { editor } = mount();
    await typeAt(editor, "@");
    await waitFor(() => expect(menuRows().length).toBe(4));
    expect(menuRows().map((row) => row.dataset.mention)).toEqual(["entity", "entity", "entity", "asset"]);
    const menu = document.querySelector("[data-suggestion-menu]") as HTMLElement;
    expect(menu.textContent).toContain("boardPickEntitiesGroup");
    expect(menu.textContent).toContain("boardPickLibrary");
    //: 变体按「母体 · 变体」列出来;行尾标种类(词表里的名字)。
    expect(menu.textContent).toContain("张三 · 冬装");
    await waitFor(() => expect(menu.textContent).toContain("场景"));
  });

  it("连进来的资产格排在最前,单独一组", async () => {
    const { editor } = mount(vi.fn(), ["e-street"]);
    await typeAt(editor, "@");
    await waitFor(() => expect(menuRows().length).toBe(4));
    expect(menuRows()[0].textContent).toContain("老街");
    const heads = [...document.querySelectorAll("[data-suggestion-menu] .font-semibold")].map((one) => one.textContent);
    expect(heads).toEqual(["boardPickLinkedGroup", "boardPickEntitiesGroup", "boardPickLibrary"]);
  });

  it("挑一个资产:正文里是它的名字,交出去的是资产 id", async () => {
    const onChange = vi.fn();
    const { editor, view } = mount(onChange);
    await typeAt(editor, "@冬");
    await waitFor(() => expect(menuRows().length).toBe(1));
    fireEvent.click(menuRows()[0]);
    await waitFor(() => expect(view.container.querySelector('[data-entity-id="e-winter"]')).toBeTruthy());
    const [text, assets, document, entityIds] = onChange.mock.calls.at(-1)!;
    expect(text.trim()).toBe("张三 · 冬装");
    expect(assets).toEqual([]);
    expect(entityIds).toEqual(["e-winter"]);
    expect(collectEntities(document)).toEqual(["e-winter"]);
  });

  it("筛「资产」只剩资产", async () => {
    const { editor } = mount();
    await typeAt(editor, "@");
    await waitFor(() => expect(menuRows().length).toBe(4));
    const chip = [...document.querySelectorAll<HTMLButtonElement>("[data-suggestion-menu] button")].find(
      (one) => one.textContent === "boardPickEntities",
    )!;
    fireEvent.click(chip);
    await waitFor(() => expect(menuRows().map((row) => row.dataset.mention)).toEqual(["entity", "entity", "entity"]));
  });
});
