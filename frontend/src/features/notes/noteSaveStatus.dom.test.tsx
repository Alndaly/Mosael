/** @vitest-environment jsdom */
/**
 * 保存状态只有一个图标位:**图形**随状态换(不只是颜色),颜色只是第二层。
 *
 * 此前是「图标 + 已保存 / 保存中… / 草稿待保存 / 保存失败…」一段字:位置被文字撑到 88px,
 * 最窄的一档才把字收起来。现在文字只留两份 —— 悬停说明(说清状态,失败时说能重试)和读屏那份
 * (`role="status"` 的活区里一颗 `sr-only` 的字),看得见的只有图标。
 */
import React from "react";
import { cleanup, render } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { hoverHint } from "@/test/hint";
import type { NoteStatus } from "./NoteSaveStatus";

const locale = vi.hoisted(() => ({ value: "zh-CN" }));
vi.mock("@/app/preferences", () => ({
  usePreferences: () => ({ locale: locale.value }),
  useI18n: () => (key: string) => key,
}));

const { NoteSaveStatus } = await import("./NoteSaveStatus");

afterEach(() => { cleanup(); locale.value = "zh-CN"; });

const STATUSES: NoteStatus[] = ["saved", "saving", "draft", "error"];

/** 每种状态的 Hint —— 说的就是那个状态本身;失败那一条还点明能重试(保存失败的提示带里就有「重试保存」)。 */
const HINTS = {
  "zh-CN": {
    saved: "已保存",
    saving: "保存中…",
    draft: "有改动，还没保存",
    error: "保存失败，可以重试",
  },
  "en-US": {
    saved: "Saved",
    saving: "Saving…",
    draft: "Changed, not saved yet",
    error: "Save failed. You can retry.",
  },
} as const;

/** 四种状态四颗图形:对勾 / 转圈 / 铅笔 / 警示。(lucide 1.x 里是规范名 + 别名两个 class。) */
const ICONS = {
  saved: "lucide-check",
  saving: "lucide-loader-circle",
  draft: "lucide-pen-line",
  error: "lucide-circle-alert",
} as const;

function mount(status: NoteStatus): HTMLElement {
  const { container } = render(<NoteSaveStatus status={status} />);
  return container.querySelector("[data-slot='save-status']") as HTMLElement;
}

it("四种状态对应四颗不同的图标,不是同一个对勾换颜色", () => {
  const classes = STATUSES.map((status) => {
    const node = mount(status);
    const svg = node.querySelector("svg");
    expect(svg, status).not.toBeNull();
    expect(svg!.getAttribute("class"), status).toContain(ICONS[status]);
    cleanup();
    return svg!.getAttribute("class")!;
  });
  expect(new Set(classes).size).toBe(STATUSES.length);
});

it("只有图标:里面没有一段看得见的文字", () => {
  for (const status of STATUSES) {
    const node = mount(status);
    expect(node.querySelector(".note-status-label"), status).toBeNull();
    const visible = [...node.querySelectorAll("span")].filter((span) => !span.classList.contains("sr-only"));
    expect(visible.map((span) => span.textContent), status).toEqual([]);
    cleanup();
  }
});

it("保存中在转,别的状态不转", () => {
  for (const status of STATUSES) {
    const svg = mount(status).querySelector("svg")!;
    expect(svg.classList.contains("animate-mosael-spin"), status).toBe(status === "saving");
    cleanup();
  }
});

it("是 role=status 的活区,读屏那份字在 sr-only 里(图标本身不念)", () => {
  for (const status of STATUSES) {
    const node = mount(status);
    expect(node).toHaveAttribute("role", "status");
    expect(node).toHaveAttribute("aria-live", "polite");
    expect(node.querySelector("svg")!.getAttribute("aria-hidden")).toBe("true");
    expect(node.querySelector(".sr-only")!.textContent).toBe(HINTS["zh-CN"][status]);
    cleanup();
  }
});

it("每一种状态都有一颗 Hint,说的就是那个状态(中文)", async () => {
  for (const status of STATUSES) {
    expect(await hoverHint(mount(status)), status).toBe(HINTS["zh-CN"][status]);
    cleanup();
  }
});

it("每一种状态都有一颗 Hint,说的就是那个状态(英文)", async () => {
  locale.value = "en-US";
  for (const status of STATUSES) {
    expect(await hoverHint(mount(status)), status).toBe(HINTS["en-US"][status]);
    cleanup();
  }
});
