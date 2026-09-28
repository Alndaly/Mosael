// @vitest-environment jsdom

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => ({ generationConfigureModel: "配置生成模型" })[key] ?? key,
}));

vi.mock("@/lib/deepLink", () => ({ gotoSettings: vi.fn() }));

import { gotoSettings } from "@/lib/deepLink";
import { GenerationModelGate } from "@/features/ai-studio/GenerationModelGate";

describe("GenerationModelGate", () => {
  it("offers the settings route of the capability it is given when no model is available", () => {
    render(<GenerationModelGate hasModel={false} loading={false} section="providers:video" />);

    fireEvent.click(screen.getByRole("button", { name: "配置生成模型" }));
    expect(gotoSettings).toHaveBeenCalledWith("providers:video");
  });

  it("stays out of the composer while models are loading or available", () => {
    const { rerender } = render(<GenerationModelGate hasModel={false} loading section="providers:image" />);
    expect(screen.queryByRole("button", { name: "配置生成模型" })).toBeNull();

    rerender(<GenerationModelGate hasModel loading={false} section="providers:image" />);
    expect(screen.queryByRole("button", { name: "配置生成模型" })).toBeNull();
  });
});
