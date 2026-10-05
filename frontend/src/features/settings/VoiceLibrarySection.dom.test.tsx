/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const listVoices = vi.fn();
const deleteVoice = vi.fn();

vi.mock("@/api/client", () => ({
  copyVoiceToEngine: vi.fn(),
  deleteVoice: (...args: unknown[]) => deleteVoice(...args),
  //: 这台机器没配能复刻的引擎 —— 配音库里就不摆「复刻到百炼」。
  listTtsEngines: async () => [],
  listVoices: (...args: unknown[]) => listVoices(...args),
  remoteConsentRequest: () => null,
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

  // 列表和剪辑页共用 VoiceList:删之前问一句,没有参考音频的试听键灰掉。
  it("删音色先确认,确认了才删;没有参考音频的试听键灰掉", async () => {
    const user = userEvent.setup();
    deleteVoice.mockResolvedValue(undefined);
    listVoices.mockResolvedValue([{ id: "v1", name: "老王", reference_text: "你好", source: "upload", has_reference: false,
                                    consent_kind: "self", consent_at: "2026-09-01", created_at: "2026-09-01" }]);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <VoiceLibrarySection workspace={{ id: "workspace-1" } as never} />
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("button", { name: "voicePlay" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "delete" }));
    const dialog = await screen.findByRole("alertdialog", { name: "voiceDeleteTitle" });
    expect(deleteVoice).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "confirm" }));
    await waitFor(() => expect(deleteVoice).toHaveBeenCalledWith("v1"));
  });
});
