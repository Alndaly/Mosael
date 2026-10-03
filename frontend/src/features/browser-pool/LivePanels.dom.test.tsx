// @vitest-environment jsdom
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { LivePanels } from "./LivePanels";

describe("LivePanels audio", () => {
  let publishPanels: ((cards: LivePanelCard[]) => void) | null;
  const setPanelMuted = vi.fn(async () => undefined);

  beforeEach(() => {
    publishPanels = null;
    setPanelMuted.mockClear();
    Object.defineProperty(window, "mosaelPublish", {
      configurable: true,
      value: {
        onPanels: (callback: (cards: LivePanelCard[]) => void) => {
          publishPanels = callback;
          return () => undefined;
        },
        setPanelMuted,
      },
    });
  });

  it("uses the main-process mute state and toggles the top embedded browser", () => {
    render(<LivePanels />);
    act(() => publishPanels?.([{ id: "browser-1", x: 20, y: 20, width: 384, height: 244, header: 26, radius: 12, muted: true }]));

    const button = screen.getByRole("button", { name: "livePanelUnmute" });
    expect(button.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(button);
    expect(setPanelMuted).toHaveBeenCalledWith("browser-1", false);
  });
});
