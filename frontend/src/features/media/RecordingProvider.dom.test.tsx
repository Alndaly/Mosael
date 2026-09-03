/** @vitest-environment jsdom */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/api/client", () => ({ importAsset: vi.fn() }));

import { RecordingProvider, useRecorder } from "./RecordingProvider";
import { importAsset } from "@/api/client";

class FakeMediaRecorder {
  state: RecordingState = "inactive";
  mimeType = "video/webm";
  ondataavailable: ((event: BlobEvent) => void) | null = null;
  onstop: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(_stream: MediaStream) {}

  start() {
    this.state = "recording";
  }

  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["x".repeat(4096)], { type: this.mimeType }) } as BlobEvent);
    this.onstop?.(new Event("stop"));
  }
}

function fakeStream({ audio = false }: { audio?: boolean } = {}) {
  const track = {
    addEventListener: vi.fn(),
    getSettings: () => ({ width: 1280, height: 720, frameRate: 30 }),
    stop: vi.fn(),
  };
  const audioTrack = { readyState: "live", stop: vi.fn() };
  return {
    getAudioTracks: () => (audio ? [audioTrack] : []),
    getTracks: () => (audio ? [track, audioTrack] : [track]),
    getVideoTracks: () => [track],
  } as unknown as MediaStream;
}

function WorkspaceHarness() {
  const { openRecorder } = useRecorder();
  const [page, setPage] = React.useState<"media" | "editor">("media");
  return page === "media" ? (
    <>
      <button type="button" onClick={() => openRecorder({ projectId: "project-1" })}>
        openRecorder
      </button>
      <button type="button" onClick={() => setPage("editor")}>
        openEditor
      </button>
    </>
  ) : (
    <p>editorPage</p>
  );
}

describe("RecordingProvider", () => {
  const enumerateDevices = vi.fn();
  const getUserMedia = vi.fn();
  const getDisplayMedia = vi.fn();

  beforeEach(() => {
    localStorage.clear();
    vi.mocked(importAsset).mockClear();
    enumerateDevices.mockReset().mockResolvedValue([]);
    getUserMedia.mockReset().mockResolvedValueOnce(fakeStream());
    getDisplayMedia.mockReset().mockResolvedValueOnce(fakeStream({ audio: true }));
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { enumerateDevices, getUserMedia, getDisplayMedia },
    });
    vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("keeps the recording controller alive while navigating between app pages", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <RecordingProvider workspaceId="workspace-1">
          <WorkspaceHarness />
        </RecordingProvider>
      </QueryClientProvider>,
    );

    await user.click(screen.getByRole("button", { name: "openRecorder" }));
    await user.click(screen.getByRole("button", { name: /recordStart/ }));
    await screen.findByRole("button", { name: /recordStop/ });
    await user.click(screen.getByRole("button", { name: "openEditor" }));

    expect(screen.getByText("editorPage")).toBeVisible();
    expect(screen.getByRole("button", { name: /recordStop/ })).toBeVisible();
  });

  it("imports the recording into the destination captured before navigation", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <RecordingProvider workspaceId="workspace-1">
          <WorkspaceHarness />
        </RecordingProvider>
      </QueryClientProvider>,
    );

    await user.click(screen.getByRole("button", { name: "openRecorder" }));
    await user.click(screen.getByRole("button", { name: /recordStart/ }));
    await user.click(screen.getByRole("button", { name: "openEditor" }));
    await user.click(await screen.findByRole("button", { name: /recordStop/ }));

    await waitFor(() =>
      expect(importAsset).toHaveBeenCalledWith(
        expect.objectContaining({ workspaceId: "workspace-1", projectId: "project-1", file: expect.any(File) }),
      ),
    );
  });
});
