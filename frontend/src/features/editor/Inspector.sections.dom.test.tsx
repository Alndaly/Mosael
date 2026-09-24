/** @vitest-environment jsdom */
/**
 * 检查器的分隔线只由节画、只画在节的上边。
 *
 * 调色页此前在「作用于 …」那行底下自带一道 border-b,紧跟着「风格预设」那一节的 border-t:
 * 两道线夹出一条空带。属性页没有这个毛病 —— 两页各写各的分隔,节奏就对不上。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  listLuts: vi.fn(async () => []),
}));
vi.stubGlobal("ResizeObserver", class {
  observe() {}
  unobserve() {}
  disconnect() {}
});

import { Inspector } from "./Inspector";

const clip = {
  id: "clip-1", asset_id: "asset-1", timeline_start: 0, src_in: 0, src_out: 5, speed: 1,
  gain: 1, muted: false, effects: {}, transform: {},
} as never;
const sequence = { id: "seq-1", name: "Sequence", revision: 1, width: 1920, height: 1080, fps: 30 } as never;
const assets = [{ id: "asset-1", name: "Video", kind: "video" }] as never;

function renderInspector() {
  const { container } = render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <Inspector
        sequence={sequence}
        workspaceId="w1"
        selectedClip={clip}
        assets={assets}
        onDeleteClip={vi.fn()}
        onSetEffects={vi.fn()}
        onSetSpeed={vi.fn()}
        onSetGain={vi.fn()}
        onSetTransform={vi.fn()}
      />
    </QueryClientProvider>,
  );
  return container;
}

/** 面板正文(面板头之后那一块)里,谁画了分隔线。 */
function dividers(container: HTMLElement) {
  const body = container.querySelector("section.editor-pane > :nth-child(2)") as HTMLElement;
  const drawn = [...body.querySelectorAll<HTMLElement>("*")].filter((el) => /(^|\s)border-[tb](\s|$)/.test(el.className));
  return { body, drawn };
}

describe("检查器的分隔线", () => {
  for (const tab of ["inspectorProps", "colorGrade"] as const) {
    it(`${tab}:只有节画线、只画上边,第一行不带线`, async () => {
      const container = renderInspector();
      await userEvent.click(screen.getByRole("tab", { name: tab }));
      const { body, drawn } = dividers(container);
      expect(drawn.length).toBeGreaterThan(1);
      for (const el of drawn) {
        expect(el.tagName, el.className).toBe("SECTION");
        expect(el.className).toMatch(/(^|\s)border-t(\s|$)/);
        expect(el.className).not.toMatch(/(^|\s)border-b(\s|$)/);
      }
      expect(drawn).not.toContain(body.firstElementChild);
    });
  }
});
