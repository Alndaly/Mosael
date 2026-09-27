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

vi.mock("@/lib/useSamplePlayer", () => ({
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
    expect(screen.getByRole("button", { name: "voiceRecord" })).toBeInTheDocument();
    //: 建克隆音色要说这把嗓子是谁的(ADR 0028 §5):三项必选一项,不替他默认选。
    const consent = await screen.findByRole("radiogroup", { name: "voiceConsentTitle" });
    expect(consent.querySelectorAll('input[type="radio"]')).toHaveLength(3);
    expect(consent.querySelector("input:checked")).toBeNull();
  });

  it("升级前建的音色没声明:一行里写明,点了去补", async () => {
    const user = userEvent.setup();
    listVoices.mockResolvedValue([{ id: "v1", name: "老王", reference_text: "", source: "upload", has_reference: true,
                                    consent_kind: "undeclared", consent_at: null, created_at: "2026-09-01" }]);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <VoiceLibrarySection workspace={{ id: "workspace-1" } as never} />
      </QueryClientProvider>,
    );
    const missing = await screen.findByText("voiceConsentMissing");
    await user.click(missing);
    expect(await screen.findByRole("radiogroup", { name: "voiceConsentTitle" })).toBeInTheDocument();
  });
});
