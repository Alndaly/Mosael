/** @vitest-environment jsdom */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { Recorder } from "./Recorder";

const originalCanvasCaptureStream = Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, "captureStream");

class FakeMediaRecorder {
  static streams: MediaStream[] = [];
  state: RecordingState = "inactive";
  mimeType = "video/webm";
  ondataavailable: ((event: BlobEvent) => void) | null = null;
  onstop: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(stream: MediaStream) {
    FakeMediaRecorder.streams.push(stream);
  }

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
    getSettings: () => ({ width: 1280, height: 720, frameRate: 30 }),
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
    localStorage.clear();
    FakeMediaRecorder.streams = [];
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
    if (originalCanvasCaptureStream) {
      Object.defineProperty(HTMLCanvasElement.prototype, "captureStream", originalCanvasCaptureStream);
    } else {
      Reflect.deleteProperty(HTMLCanvasElement.prototype, "captureStream");
    }
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("lets the user mirror the camera preview and remembers the choice", async () => {
    const probe = fakeStream();
    getUserMedia.mockResolvedValueOnce(probe.stream);
    const user = userEvent.setup();

    render(<Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "record_camera" }));
    const mirror = screen.getByRole("switch", { name: "recordCameraMirror" });
    await user.click(mirror);

    expect(mirror).toBeChecked();
    expect(document.querySelector("video")).toHaveClass("-scale-x-100");
    expect(localStorage.getItem("mosael.recorder.cameraMirror")).toBe("true");
  });

  it("keeps the app interactive while a recording is running", async () => {
    const probe = fakeStream();
    const screenCapture = fakeStream();
    getUserMedia.mockResolvedValueOnce(probe.stream);
    getDisplayMedia.mockResolvedValueOnce(screenCapture.stream);
    const onWorkspaceAction = vi.fn();
    const user = userEvent.setup();

    render(
      <>
        <button type="button" onClick={onWorkspaceAction}>
          workspaceAction
        </button>
        <Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />
      </>,
    );

    await user.click(screen.getByRole("button", { name: /recordStart/ }));
    await screen.findByRole("button", { name: /recordStop/ });
    await user.click(await screen.findByRole("button", { name: "workspaceAction" }));

    expect(onWorkspaceAction).toHaveBeenCalledOnce();
  });

  it("collapses configuration into a compact recording controller after start", async () => {
    const probe = fakeStream();
    const screenCapture = fakeStream();
    getUserMedia.mockResolvedValueOnce(probe.stream);
    getDisplayMedia.mockResolvedValueOnce(screenCapture.stream);
    const user = userEvent.setup();

    render(<Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /recordStart/ }));
    await screen.findByRole("button", { name: /recordStop/ });

    expect(screen.queryByRole("group", { name: "recordTitle" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /recordStop/ })).toBeVisible();
  });

  it("keeps both live previews attached after the recorder becomes a floating controller", async () => {
    const probe = fakeStream();
    const screenCapture = fakeStream();
    const cameraCapture = fakeStream();
    getUserMedia.mockResolvedValueOnce(probe.stream).mockResolvedValueOnce(cameraCapture.stream);
    getDisplayMedia.mockResolvedValueOnce(screenCapture.stream);
    const user = userEvent.setup();

    render(<Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "record_screenCamera" }));
    await user.click(screen.getByRole("button", { name: /recordStart/ }));
    await screen.findByRole("button", { name: /recordStop/ });

    const previews = [...document.querySelectorAll("video")];
    expect(previews).toHaveLength(2);
    expect(previews[0].srcObject).toBe(screenCapture.stream);
    expect(previews[1].srcObject).toBe(cameraCapture.stream);
  });

  it("lets the user opt out of device audio when recording the screen", async () => {
    const probe = fakeStream();
    const screenCapture = fakeStream();
    getUserMedia.mockResolvedValueOnce(probe.stream);
    getDisplayMedia.mockResolvedValueOnce(screenCapture.stream);
    const user = userEvent.setup();

    render(<Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />);

    const deviceAudio = screen.getByRole("switch", { name: "recordSystemAudio" });
    expect(deviceAudio).toBeChecked();
    await user.click(deviceAudio);
    await user.click(screen.getByRole("button", { name: /recordStart/ }));

    expect(getDisplayMedia).toHaveBeenCalledWith({ video: true, audio: false });
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

  it("records mirrored camera frames without transforming the screen asset", async () => {
    const probe = fakeStream();
    const screenCapture = fakeStream();
    const cameraCapture = fakeStream();
    const mirroredCapture = fakeStream();
    Object.assign(mirroredCapture.stream, { addTrack: vi.fn() });
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      clearRect: vi.fn(),
      drawImage: vi.fn(),
      restore: vi.fn(),
      save: vi.fn(),
      scale: vi.fn(),
      translate: vi.fn(),
    } as unknown as CanvasRenderingContext2D);
    Object.defineProperty(HTMLCanvasElement.prototype, "captureStream", {
      configurable: true,
      value: vi.fn(() => mirroredCapture.stream),
    });
    getUserMedia.mockResolvedValueOnce(probe.stream).mockResolvedValueOnce(cameraCapture.stream);
    getDisplayMedia.mockResolvedValueOnce(screenCapture.stream);
    localStorage.setItem("mosael.recorder.cameraMirror", "true");
    const onRecorded = vi.fn();
    const user = userEvent.setup();

    render(<Recorder open onOpenChange={vi.fn()} onRecorded={onRecorded} />);

    await user.click(screen.getByRole("button", { name: "record_screenCamera" }));
    await user.click(screen.getByRole("button", { name: /recordStart/ }));
    await screen.findByRole("button", { name: /recordStop/ });

    expect(FakeMediaRecorder.streams).toEqual([screenCapture.stream, mirroredCapture.stream]);

    await user.click(screen.getByRole("button", { name: /recordStop/ }));
    await waitFor(() => expect(onRecorded).toHaveBeenCalledOnce());
    expect(onRecorded.mock.calls[0][0]).toHaveLength(2);
    expect(screenCapture.track.stop).toHaveBeenCalledOnce();
    expect(cameraCapture.track.stop).toHaveBeenCalledOnce();
    expect(mirroredCapture.track.stop).toHaveBeenCalledOnce();
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
