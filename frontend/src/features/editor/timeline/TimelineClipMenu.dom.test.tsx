/** @vitest-environment jsdom */
/**
 * 时间线片段的右键菜单。
 *
 * - 删除 / 波纹删除和工具栏、Delete 键同一条路径:右键的那段在选区里,删的是**整个选区**。
 *   此前多选后右键删除只删被点的那一段。
 * - 「分离音频」按素材类型给:视频轨上的图片没有声音。它是片段级的(把这一段的声音摘到音频轨);
 *   「分离人声与背景音」「降噪」处理整份素材、产出进素材库,所以不在片段菜单里,在素材的菜单里。
 * - 文字、字幕、脱机片段没有素材可复制:菜单里不给「复制片段」,工具栏上的那颗灰掉。
 */
import { DndContext } from "@dnd-kit/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import type { Asset, Sequence } from "@/api/client";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Timeline } from "@/features/editor/timeline/Timeline";
import { useEditorStore } from "@/stores/editorStore";

const clip = (id: string, kind: string, start: number, extra: Record<string, unknown> = {}) => ({
  id, track_id: "", asset_id: `asset-${id}`, asset_kind: kind, timeline_start: start, src_in: 0, src_out: 2, speed: 1,
  gain: 1, muted: false, text_override: null, effects: {}, transform: {}, ...extra,
});

const tracks = [
  {
    id: "V1", kind: "video", name: "V1", position: 0, muted: false, locked: false, solo: false, duck: false,
    clips: [
      clip("film", "video", 0),
      clip("still", "image", 3),
      clip("title", "", 6, { asset_id: null, text_override: "Hello" }),
    ],
  },
  {
    id: "A1", kind: "audio", name: "A1", position: 1, muted: false, locked: false, solo: false, duck: false,
    clips: [clip("voice", "audio", 0)],
  },
];
const assets = ["film", "still", "voice"].map((id) => ({ id: `asset-${id}`, name: id, kind: "video", media_info: {} })) as unknown as Asset[];

function renderTimeline() {
  const handlers = {
    onDeleteClips: vi.fn(),
    onRippleDeleteClips: vi.fn(),
    onDuplicateClip: vi.fn(),
    onDetachAudio: vi.fn(),
  };
  const sequence = { id: "s", name: "S", width: 1920, height: 1080, fps: 30, tracks } as unknown as Sequence;
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <TooltipProvider>
        <DndContext>
          <Timeline sequence={sequence} assets={assets} onInsertClip={vi.fn()} onMoveClip={vi.fn()} onTrimClip={vi.fn()} {...handlers} />
        </DndContext>
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return handlers;
}

function openMenu(name: string) {
  fireEvent.contextMenu(screen.getByRole("button", { name }), { button: 2, clientX: 20, clientY: 20 });
}
const menuItems = () => screen.getAllByRole("menuitem").map((item) => item.textContent?.trim());

beforeEach(() => useEditorStore.getState().selectClips([]));

describe("片段右键:删除作用在选区上", () => {
  it("右键的那段在选区里:删除 / 波纹删除删整组,和工具栏同一条路径", async () => {
    const handlers = renderTimeline();
    useEditorStore.getState().selectClips(["film", "voice"]);

    openMenu("film");
    await userEvent.click(await screen.findByRole("menuitem", { name: "deleteClip" }));
    expect(handlers.onDeleteClips).toHaveBeenCalledWith(["film", "voice"]);

    openMenu("voice");
    await userEvent.click(await screen.findByRole("menuitem", { name: "rippleDelete" }));
    expect(handlers.onRippleDeleteClips).toHaveBeenCalledWith(["film", "voice"]);

    await userEvent.click(screen.getByRole("button", { name: "deleteClip" }));
    expect(handlers.onDeleteClips).toHaveBeenLastCalledWith(["film", "voice"]);
  });

  it("右键的那段不在选区里:选区换成它,只删它", async () => {
    const handlers = renderTimeline();
    useEditorStore.getState().selectClips(["film", "voice"]);

    openMenu("still");
    await userEvent.click(await screen.findByRole("menuitem", { name: "deleteClip" }));
    expect(handlers.onDeleteClips).toHaveBeenCalledWith(["still"]);
    expect(useEditorStore.getState().selectedClipIds).toEqual(["still"]);
  });
});

describe("片段右键:声音相关的动作", () => {
  it("视频:有「分离音频」", async () => {
    const handlers = renderTimeline();
    openMenu("film");
    await userEvent.click(await screen.findByRole("menuitem", { name: "detachAudio" }));
    expect(handlers.onDetachAudio).toHaveBeenCalledWith("film");
  });

  it("视频轨上的图片、音频:没有「分离音频」", async () => {
    renderTimeline();
    for (const name of ["still", "voice"]) {
      openMenu(name);
      await screen.findByRole("menuitem", { name: "deleteClip" });
      expect(menuItems()).not.toContain("detachAudio");
      await userEvent.keyboard("{Escape}");
    }
  });

  it("人声分离和降噪处理的是整份素材,不在任何片段的菜单里", async () => {
    renderTimeline();
    for (const name of ["film", "voice"]) {
      openMenu(name);
      await screen.findByRole("menuitem", { name: "deleteClip" });
      expect(menuItems()).not.toContain("separateAudio");
      expect(menuItems()).not.toContain("denoiseAction");
      await userEvent.keyboard("{Escape}");
    }
  });
});

describe("复制片段只给有素材的片段", () => {
  it("文字片段:菜单里没有,工具栏上的灰掉", async () => {
    const handlers = renderTimeline();
    openMenu("Hello");
    await screen.findByRole("menuitem", { name: "deleteClip" });
    expect(menuItems()).not.toContain("duplicateClip");
    await userEvent.keyboard("{Escape}");
    expect(await screen.findByRole("button", { name: "duplicateClip" })).toBeDisabled();
    expect(handlers.onDuplicateClip).not.toHaveBeenCalled();
  });

  it("素材片段:菜单和工具栏都能用", async () => {
    const handlers = renderTimeline();
    openMenu("film");
    await userEvent.click(await screen.findByRole("menuitem", { name: "duplicateClip" }));
    expect(handlers.onDuplicateClip).toHaveBeenCalledWith("film");
    const toolbar = screen.getByRole("button", { name: "duplicateClip" });
    expect(toolbar).toBeEnabled();
    await userEvent.click(toolbar);
    expect(handlers.onDuplicateClip).toHaveBeenLastCalledWith("film");
  });
});
