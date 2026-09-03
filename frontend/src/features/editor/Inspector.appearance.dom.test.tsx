/** @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
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

describe("Inspector clip appearance", () => {
  it("persists circle mask and shadow through clip effects", async () => {
    const onSetEffects = vi.fn();
    const user = userEvent.setup();
    render(
      <Inspector
        sequence={sequence}
        workspaceId="w1"
        selectedClip={clip}
        assets={assets}
        onDeleteClip={vi.fn()}
        onSetEffects={onSetEffects}
      />,
    );

    await user.click(screen.getByRole("button", { name: "maskShapeCircle" }));
    expect(onSetEffects).toHaveBeenLastCalledWith("clip-1", expect.objectContaining({
      appearance: expect.objectContaining({ mask: { shape: "circle", radius: 0 } }),
    }));

    await user.click(screen.getByRole("button", { name: "clipShadowEnable" }));
    expect(onSetEffects).toHaveBeenLastCalledWith("clip-1", expect.objectContaining({
      appearance: expect.objectContaining({
        mask: { shape: "circle", radius: 0 },
        shadow: expect.objectContaining({ enabled: true }),
      }),
    }));
  });
});
