/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const listVoices = vi.fn();

vi.mock("@/api/client", () => ({
  deleteVoice: vi.fn(),
  listVoices: (...args: unknown[]) => listVoices(...args),
  recognizeReference: vi.fn(),
  updateVoice: vi.fn(),
  uploadVoice: vi.fn(),
  voiceSampleUrl: vi.fn(),
}));

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
}));

vi.mock("@/features/editor/useSamplePlayer", () => ({
  useSamplePlayer: () => ({ playingId: null, toggle: vi.fn() }),
}));

import { VoiceLibrarySection } from "./VoiceLibrarySection";

describe("VoiceLibrarySection", () => {
  beforeEach(() => listVoices.mockResolvedValue([]));

  it("opens voice creation in the shared modal instead of expanding an inline form", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <VoiceLibrarySection workspace={{ id: "workspace-1" } as never} />
      </QueryClientProvider>,
    );

    await user.click(screen.getByRole("button", { name: "voiceNewTitle" }));

    const dialog = screen.getByRole("dialog", { name: "voiceNewTitle" });
    expect(dialog).toBeInTheDocument();
    expect(dialog.querySelector('[data-slot="modal-footer"]')).not.toBeNull();
    expect(screen.getByRole("textbox", { name: "voiceName" })).toHaveFocus();
  });
});
