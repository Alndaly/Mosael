/** @vitest-environment jsdom */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { Recorder } from "./Recorder";

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

function fakeStream() {
  let onEnded: EventListener | null = null;
  const track = {
    stop: vi.fn(),
    addEventListener: vi.fn((type: string, listener: EventListenerOrEventListenerObject) => {
      if (type === "ended") {
        onEnded = typeof listener === "function" ? listener : (event) => listener.handleEvent(event);
      }
    }),
  };
  return {
    stream: {
      getTracks: () => [track],
      getVideoTracks: () => [track],
      getAudioTracks: () => [],
    } as unknown as MediaStream,
    track,
    end: () => onEnded?.(new Event("ended")),
  };
}

describe("Recorder", () => {
  const enumerateDevices = vi.fn();
  const getUserMedia = vi.fn();
  const getDisplayMedia = vi.fn();

  beforeEach(() => {
    enumerateDevices.mockReset().mockResolvedValue([]);
    getUserMedia.mockReset();
    getDisplayMedia.mockReset();
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

  it("records the screen and camera as two separate files", async () => {
    const probe = fakeStream();
    const screenCapture = fakeStream();
    const cameraCapture = fakeStream();
    getUserMedia.mockResolvedValueOnce(probe.stream).mockResolvedValueOnce(cameraCapture.stream);
    getDisplayMedia.mockResolvedValueOnce(screenCapture.stream);
    const onRecorded = vi.fn();
    const user = userEvent.setup();

    render(<Recorder open onOpenChange={vi.fn()} onRecorded={onRecorded} />);

    await user.click(screen.getByRole("button", { name: "record_screenCamera" }));
    await user.click(screen.getByRole("button", { name: /recordStart/ }));
    await user.click(await screen.findByRole("button", { name: /recordStop/ }));

    await waitFor(() => expect(onRecorded).toHaveBeenCalledOnce());
    const files = onRecorded.mock.calls[0][0] as File[];
    expect(files).toHaveLength(2);
    expect(files.map((file) => file.name)).toEqual([
      expect.stringMatching(/^record_screen_file-\d+\.webm$/),
      expect.stringMatching(/^record_camera_file-\d+\.webm$/),
    ]);
    expect(getDisplayMedia).toHaveBeenCalledWith({ video: true, audio: true });
    expect(getUserMedia).toHaveBeenLastCalledWith({ video: true, audio: true });
    expect(screenCapture.track.stop).toHaveBeenCalledOnce();
    expect(cameraCapture.track.stop).toHaveBeenCalledOnce();
  });

  it("stops both captures when screen sharing ends from the operating system", async () => {
    const probe = fakeStream();
    const screenCapture = fakeStream();
    const cameraCapture = fakeStream();
    getUserMedia.mockResolvedValueOnce(probe.stream).mockResolvedValueOnce(cameraCapture.stream);
    getDisplayMedia.mockResolvedValueOnce(screenCapture.stream);
    const onRecorded = vi.fn();
    const user = userEvent.setup();

    render(<Recorder open onOpenChange={vi.fn()} onRecorded={onRecorded} />);
    await user.click(screen.getByRole("button", { name: "record_screenCamera" }));
    await user.click(screen.getByRole("button", { name: /recordStart/ }));
    await screen.findByRole("button", { name: /recordStop/ });

    screenCapture.end();

    await waitFor(() => expect(onRecorded).toHaveBeenCalledOnce());
    expect(onRecorded.mock.calls[0][0]).toHaveLength(2);
    expect(screenCapture.track.stop).toHaveBeenCalledOnce();
    expect(cameraCapture.track.stop).toHaveBeenCalledOnce();
  });

  it("releases an acquired screen if camera permission is denied", async () => {
    const probe = fakeStream();
    const screenCapture = fakeStream();
    getUserMedia.mockResolvedValueOnce(probe.stream).mockRejectedValueOnce(new Error("denied"));
    getDisplayMedia.mockResolvedValueOnce(screenCapture.stream);
    const onRecorded = vi.fn();
    const user = userEvent.setup();

    render(<Recorder open onOpenChange={vi.fn()} onRecorded={onRecorded} />);
    await waitFor(() => expect(enumerateDevices).toHaveBeenCalledOnce());
    await user.click(screen.getByRole("button", { name: "record_screenCamera" }));
    await user.click(screen.getByRole("button", { name: /recordStart/ }));

    await waitFor(() => expect(screenCapture.track.stop).toHaveBeenCalledOnce());
    expect(onRecorded).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /recordStart/ })).toBeEnabled();
  });
});
