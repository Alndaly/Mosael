/** @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.stubGlobal("ResizeObserver", class {
  observe() {}
  unobserve() {}
  disconnect() {}
});

import { Inspector } from "./Inspector";

/** 检查器的「时长」说的是这一段在**时间线上**占多久 —— 变速片段的源长度不是它。 */
describe("检查器的时长", () => {
  it("2 倍速片段显示时间线时长,不显示源时长", () => {
    const clip = {
      id: "c1", asset_id: "a1", asset_kind: "video", timeline_start: 10, src_in: 0, src_out: 20, speed: 2,
      gain: 1, muted: false, effects: {}, transform: {},
    } as never;
    render(
      <Inspector workspaceId="w1" selectedClip={clip} assets={[{ id: "a1", name: "V", kind: "video" }] as never} onDeleteClip={vi.fn()} onSetEffects={vi.fn()} />,
    );
    const duration = screen.getByText("duration").nextElementSibling;
    expect(duration?.textContent).toBe("00:10.0");
  });
});
