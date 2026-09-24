/** @vitest-environment jsdom */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

import { Recorder } from "./Recorder";
import { toast } from "sonner";
import { FakeAudioContext } from "@/test/fakeAudioContext";

const originalCanvasCaptureStream = Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, "captureStream");

beforeAll(() => {
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => {},
    releasePointerCapture: () => {},
    scrollIntoView: () => {},
  });
});

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

function fakeStream({ audio = false }: { audio?: boolean } = {}) {
  let onEnded: EventListener | null = null;
  const track = {
    stop: vi.fn(),
    getSettings: () => ({ width: 1280, height: 720, frameRate: 30 }),
    addEventListener: vi.fn((type: string, listener: EventListenerOrEventListenerObject) => {
      if (type === "ended") {
        onEnded = typeof listener === "function" ? listener : (event) => listener.handleEvent(event);
      }
    }),
    removeEventListener: vi.fn((type: string) => {
      if (type === "ended") onEnded = null;
    }),
  };
  const audioTrack = {
    stop: vi.fn(),
    readyState: "live" as MediaStreamTrackState,
  };
  return {
    stream: {
      getTracks: () => (audio ? [track, audioTrack] : [track]),
      getVideoTracks: () => [track],
      getAudioTracks: () => (audio ? [audioTrack] : []),
    } as unknown as MediaStream,
    track,
    audioTrack,
    end: () => onEnded?.(new Event("ended")),
  };
}

/** A microphone-only stream, as the mic source opens it. */
function fakeMicrophone() {
  const audioTrack = { stop: vi.fn(), readyState: "live" as MediaStreamTrackState };
  return {
    stream: {
      getTracks: () => [audioTrack],
      getVideoTracks: () => [],
      getAudioTracks: () => [audioTrack],
    } as unknown as MediaStream,
    audioTrack,
  };
}

/** Grants camera and microphone through the desktop bridge, so the recorder may open them. */
function grantInputs() {
  Object.defineProperty(window, "mosaelDesktop", {
    configurable: true,
    value: { platform: "darwin", recordingPermissions: { getStatus: vi.fn().mockResolvedValue("granted") } },
  });
}

function levelMeter() {
  return screen.queryByRole("meter", { name: "recordLevel" });
}

function fakeDevice(kind: MediaDeviceKind, deviceId: string, label: string): MediaDeviceInfo {
  return { kind, deviceId, label, groupId: "group", toJSON: () => ({}) };
}

describe("Recorder", () => {
  const enumerateDevices = vi.fn();
  const getUserMedia = vi.fn();
  const getDisplayMedia = vi.fn();

  beforeEach(() => {
    localStorage.clear();
    FakeMediaRecorder.streams = [];
    enumerateDevices.mockReset().mockResolvedValue([]);
    // A camera that never answers unless a test says otherwise, as when the recorder stays open
    // after a recording and reopens its preview.
    getUserMedia.mockReset().mockReturnValue(new Promise<MediaStream>(() => {}));
    getDisplayMedia.mockReset();
    vi.mocked(toast.error).mockReset();
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { enumerateDevices, getUserMedia, getDisplayMedia },
    });
    vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
    FakeAudioContext.reset();
    vi.stubGlobal("AudioContext", FakeAudioContext);
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    Reflect.deleteProperty(window, "mosaelDesktop");
  });

  afterEach(() => {
    if (originalCanvasCaptureStream) {
      Object.defineProperty(HTMLCanvasElement.prototype, "captureStream", originalCanvasCaptureStream);
    } else {
      Reflect.deleteProperty(HTMLCanvasElement.prototype, "captureStream");
    }
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    Reflect.deleteProperty(window, "mosaelDesktop");
  });

  it("does not request camera or microphone access merely by opening the recorder", async () => {
    render(<Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />);

    await waitFor(() => expect(enumerateDevices).toHaveBeenCalledOnce());
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it("shows one synthetic system-default option instead of the browser default alias", async () => {
    enumerateDevices.mockResolvedValue([
      fakeDevice("audioinput", "default", "Default - MacBook Pro Microphone (Built-in)"),
      fakeDevice("audioinput", "built-in-mic", "MacBook Pro Microphone (Built-in)"),
    ]);
    const user = userEvent.setup();

    render(<Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />);

    await waitFor(() => expect(enumerateDevices).toHaveBeenCalledOnce());
    await user.click(screen.getByRole("button", { name: "record_mic" }));
    await user.click(screen.getByRole("combobox", { name: "recordMic" }));

    expect(screen.queryByText("Default - MacBook Pro Microphone (Built-in)")).not.toBeInTheDocument();
    expect(screen.getByText("MacBook Pro Microphone (Built-in)")).toBeVisible();
  });

  it("lets the user explicitly request camera and microphone permissions", async () => {
    const request = vi.fn().mockResolvedValue(true);
    Object.defineProperty(window, "mosaelDesktop", {
      configurable: true,
      value: { platform: "darwin", recordingPermissions: { request } },
    });
    const user = userEvent.setup();

    render(<Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "record_screenCamera" }));
    await user.click(screen.getByRole("button", { name: "recordRequestPermissions" }));

    expect(request.mock.calls).toEqual([["camera"], ["microphone"]]);
  });

  it("offers native settings after camera permission has been denied", async () => {
    const request = vi.fn().mockResolvedValue(false);
    const openSettings = vi.fn().mockResolvedValue(true);
    Object.defineProperty(window, "mosaelDesktop", {
      configurable: true,
      value: { platform: "darwin", recordingPermissions: { request, openSettings } },
    });
    const user = userEvent.setup();

    render(<Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "record_camera" }));
    await user.click(screen.getByRole("button", { name: "recordRequestPermissions" }));
    await user.click(await screen.findByRole("button", { name: "recordOpenCameraSettings" }));

    expect(openSettings).toHaveBeenCalledWith("camera");
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
    const screenCapture = fakeStream({ audio: true });
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
    const screenCapture = fakeStream({ audio: true });
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
    const screenCapture = fakeStream({ audio: true });
    const cameraCapture = fakeStream();
    getUserMedia.mockResolvedValueOnce(cameraCapture.stream);
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

  it("does not silently create a mute recording when requested system audio was not granted", async () => {
    const probe = fakeStream();
    const screenCapture = fakeStream();
    getUserMedia.mockResolvedValueOnce(probe.stream);
    getDisplayMedia.mockResolvedValueOnce(screenCapture.stream);
    const user = userEvent.setup();

    render(<Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /recordStart/ }));

    await waitFor(() => expect(screenCapture.track.stop).toHaveBeenCalledOnce());
    expect(screen.queryByRole("button", { name: /recordStop/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /recordStart/ })).toBeEnabled();
    expect(toast.error).toHaveBeenCalledWith("recordSystemAudioMissing");
    expect(screen.getByRole("alert")).toHaveTextContent("recordSystemAudioPermissionTitle");
  });

  it("opens the operating system settings from the system-audio recovery state", async () => {
    const openSettings = vi.fn().mockResolvedValue(true);
    Object.defineProperty(window, "mosaelDesktop", {
      configurable: true,
      value: { platform: "darwin", recordingPermissions: { openSettings } },
    });
    const screenCapture = fakeStream();
    getDisplayMedia.mockResolvedValueOnce(screenCapture.stream);
    const user = userEvent.setup();

    render(<Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /recordStart/ }));
    await user.click(await screen.findByRole("button", { name: "recordOpenSystemSettings" }));

    expect(openSettings).toHaveBeenCalledWith("screen");
  });

  it("records the screen and camera as two separate files", async () => {
    const screenCapture = fakeStream({ audio: true });
    const cameraCapture = fakeStream();
    getUserMedia.mockResolvedValueOnce(cameraCapture.stream);
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
    const screenCapture = fakeStream({ audio: true });
    const cameraCapture = fakeStream();
    const mirroredCapture = fakeStream();
    const requestFrame = vi.fn();
    Object.assign(mirroredCapture.track, { requestFrame });
    Object.assign(mirroredCapture.stream, { addTrack: vi.fn() });
    const drawImage = vi.fn();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      drawImage,
      setTransform: vi.fn(),
    } as unknown as CanvasRenderingContext2D);
    Object.defineProperty(HTMLCanvasElement.prototype, "captureStream", {
      configurable: true,
      value: vi.fn(() => mirroredCapture.stream),
    });
    let cameraFrames!: ReadableStreamDefaultController<VideoFrame>;
    const processedTracks: unknown[] = [];
    vi.stubGlobal(
      "MediaStreamTrackProcessor",
      class {
        readonly readable = new ReadableStream<VideoFrame>({
          start: (controller) => {
            cameraFrames = controller;
          },
        });
        constructor({ track }: { track: MediaStreamTrack }) {
          processedTracks.push(track);
        }
      },
    );
    getUserMedia.mockResolvedValueOnce(cameraCapture.stream);
    getDisplayMedia.mockResolvedValueOnce(screenCapture.stream);
    localStorage.setItem("mosael.recorder.cameraMirror", "true");
    const onRecorded = vi.fn();
    const user = userEvent.setup();

    render(<Recorder open onOpenChange={vi.fn()} onRecorded={onRecorded} />);

    await user.click(screen.getByRole("button", { name: "record_screenCamera" }));
    await user.click(screen.getByRole("button", { name: /recordStart/ }));
    await screen.findByRole("button", { name: /recordStop/ });

    expect(FakeMediaRecorder.streams).toEqual([screenCapture.stream, mirroredCapture.stream]);
    expect(processedTracks).toEqual([cameraCapture.track]);

    // Starting swaps the dialog content, replacing (and so pausing) the setup preview element.
    // Camera frames that arrive afterwards must still reach the recording.
    const frame = { displayWidth: 1280, displayHeight: 720, close: vi.fn() } as unknown as VideoFrame;
    cameraFrames.enqueue(frame);
    await waitFor(() => expect(requestFrame).toHaveBeenCalledOnce());
    expect(drawImage).toHaveBeenCalledWith(frame, 0, 0, 1280, 720);

    await user.click(screen.getByRole("button", { name: /recordStop/ }));
    await waitFor(() => expect(onRecorded).toHaveBeenCalledOnce());
    expect(onRecorded.mock.calls[0][0]).toHaveLength(2);
    expect(screenCapture.track.stop).toHaveBeenCalledOnce();
    expect(cameraCapture.track.stop).toHaveBeenCalledOnce();
    expect(mirroredCapture.track.stop).toHaveBeenCalledOnce();
  });

  it("stops both captures when screen sharing ends from the operating system", async () => {
    const screenCapture = fakeStream({ audio: true });
    const cameraCapture = fakeStream();
    getUserMedia.mockResolvedValueOnce(cameraCapture.stream);
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
    const screenCapture = fakeStream({ audio: true });
    getUserMedia.mockRejectedValueOnce(new Error("denied"));
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

  describe("camera preview before recording", () => {
    function ClosingRecorder({ onRecorded }: { onRecorded: (files: File[]) => void }) {
      const [open, setOpen] = React.useState(true);
      return <Recorder open={open} onOpenChange={setOpen} onRecorded={onRecorded} />;
    }

    function previewVideo() {
      const videos = [...document.querySelectorAll("video")];
      return videos[videos.length - 1];
    }

    it("shows the live camera once access is granted, mirrored when the user asks for it", async () => {
      grantInputs();
      const camera = fakeStream({ audio: true });
      getUserMedia.mockResolvedValueOnce(camera.stream);
      const user = userEvent.setup();

      render(<Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />);
      await user.click(screen.getByRole("button", { name: "record_camera" }));

      await waitFor(() => expect(previewVideo().srcObject).toBe(camera.stream));
      expect(getUserMedia).toHaveBeenCalledWith({ video: true, audio: true });
      expect(screen.queryByText("record_camera_placeholder")).not.toBeInTheDocument();
      expect(previewVideo()).not.toHaveClass("-scale-x-100");

      await user.click(screen.getByRole("switch", { name: "recordCameraMirror" }));
      expect(previewVideo()).toHaveClass("-scale-x-100");
      expect(camera.track.stop).not.toHaveBeenCalled();
    });

    it("records the previewed camera instead of opening it again when recording starts", async () => {
      grantInputs();
      const camera = fakeStream({ audio: true });
      getUserMedia.mockResolvedValueOnce(camera.stream);
      const onRecorded = vi.fn();
      const user = userEvent.setup();

      render(<ClosingRecorder onRecorded={onRecorded} />);
      await user.click(screen.getByRole("button", { name: "record_camera" }));
      await waitFor(() => expect(previewVideo().srcObject).toBe(camera.stream));
      await user.click(screen.getByRole("button", { name: /recordStart/ }));
      await screen.findByRole("button", { name: /recordStop/ });

      expect(getUserMedia).toHaveBeenCalledOnce();
      expect(FakeMediaRecorder.streams).toEqual([camera.stream]);
      expect(previewVideo().srcObject).toBe(camera.stream);
      expect(camera.track.stop).not.toHaveBeenCalled();

      await user.click(screen.getByRole("button", { name: /recordStop/ }));
      await waitFor(() => expect(onRecorded).toHaveBeenCalledOnce());
      expect(getUserMedia).toHaveBeenCalledOnce();
      expect(camera.track.stop).toHaveBeenCalledOnce();
      expect(camera.audioTrack.stop).toHaveBeenCalledOnce();
    });

    it("keeps the previewed camera for the screen and camera session until the screen is picked", async () => {
      grantInputs();
      const camera = fakeStream({ audio: true });
      const screenCapture = fakeStream({ audio: true });
      getUserMedia.mockResolvedValueOnce(camera.stream);
      getDisplayMedia.mockResolvedValueOnce(screenCapture.stream);
      const user = userEvent.setup();

      render(<Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />);
      await user.click(screen.getByRole("button", { name: "record_screenCamera" }));
      await waitFor(() => expect(previewVideo().srcObject).toBe(camera.stream));
      expect(screen.getByText("record_screen_placeholder")).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: /recordStart/ }));
      await screen.findByRole("button", { name: /recordStop/ });

      expect(getUserMedia).toHaveBeenCalledOnce();
      expect(FakeMediaRecorder.streams).toEqual([screenCapture.stream, camera.stream]);
    });

    it("releases the camera when switching to a source without camera or microphone", async () => {
      grantInputs();
      const camera = fakeStream({ audio: true });
      getUserMedia.mockResolvedValueOnce(camera.stream);
      const user = userEvent.setup();

      render(<Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />);
      await user.click(screen.getByRole("button", { name: "record_camera" }));
      await waitFor(() => expect(previewVideo().srcObject).toBe(camera.stream));
      await user.click(screen.getByRole("button", { name: "record_screen" }));

      expect(camera.track.stop).toHaveBeenCalledOnce();
      expect(camera.audioTrack.stop).toHaveBeenCalledOnce();
      expect(getUserMedia).toHaveBeenCalledOnce();
    });

    it("releases the camera and keeps only the microphone when switching to the mic source", async () => {
      grantInputs();
      const camera = fakeStream({ audio: true });
      const microphone = fakeMicrophone();
      getUserMedia.mockResolvedValueOnce(camera.stream).mockResolvedValueOnce(microphone.stream);
      const user = userEvent.setup();

      render(<Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />);
      await user.click(screen.getByRole("button", { name: "record_camera" }));
      await waitFor(() => expect(previewVideo().srcObject).toBe(camera.stream));
      await user.click(screen.getByRole("button", { name: "record_mic" }));

      expect(camera.track.stop).toHaveBeenCalledOnce();
      expect(camera.audioTrack.stop).toHaveBeenCalledOnce();
      expect(getUserMedia).toHaveBeenLastCalledWith({ audio: true });
      expect(document.querySelector("video")).toBeNull();
    });

    it("releases the camera when the recorder closes or unmounts", async () => {
      grantInputs();
      const first = fakeStream({ audio: true });
      const second = fakeStream({ audio: true });
      getUserMedia.mockResolvedValueOnce(first.stream).mockResolvedValueOnce(second.stream);
      const user = userEvent.setup();

      const view = render(<Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />);
      await user.click(screen.getByRole("button", { name: "record_camera" }));
      await waitFor(() => expect(previewVideo().srcObject).toBe(first.stream));

      view.rerender(<Recorder open={false} onOpenChange={vi.fn()} onRecorded={vi.fn()} />);
      expect(first.track.stop).toHaveBeenCalledOnce();

      view.rerender(<Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />);
      await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(2));
      await waitFor(() => expect(previewVideo().srcObject).toBe(second.stream));
      view.unmount();
      expect(second.track.stop).toHaveBeenCalledOnce();
    });

    it("reopens the camera with the newly selected device", async () => {
      grantInputs();
      enumerateDevices.mockResolvedValue([fakeDevice("videoinput", "camera-2", "Desk Camera")]);
      const first = fakeStream({ audio: true });
      const second = fakeStream({ audio: true });
      getUserMedia.mockResolvedValueOnce(first.stream).mockResolvedValueOnce(second.stream);
      const user = userEvent.setup();

      render(<Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />);
      await user.click(screen.getByRole("button", { name: "record_camera" }));
      await waitFor(() => expect(previewVideo().srcObject).toBe(first.stream));
      await user.click(screen.getByRole("combobox", { name: "recordCamera" }));
      await user.click(await screen.findByRole("option", { name: "Desk Camera" }));

      await waitFor(() => expect(previewVideo().srcObject).toBe(second.stream));
      expect(first.track.stop).toHaveBeenCalledOnce();
      expect(second.track.stop).not.toHaveBeenCalled();
      expect(getUserMedia).toHaveBeenLastCalledWith({
        video: { deviceId: { exact: "camera-2" } },
        audio: true,
      });
    });

    it("keeps the preview when the screen picker fails, and never leaks a camera the recording took", async () => {
      grantInputs();
      const camera = fakeStream({ audio: true });
      const reopened = fakeStream({ audio: true });
      const mute = fakeStream();
      const screenCapture = fakeStream({ audio: true });
      getUserMedia.mockResolvedValueOnce(camera.stream).mockResolvedValueOnce(reopened.stream);
      getDisplayMedia.mockResolvedValueOnce(mute.stream).mockResolvedValueOnce(screenCapture.stream);
      const user = userEvent.setup();

      render(<Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />);
      await user.click(screen.getByRole("button", { name: "record_screenCamera" }));
      await waitFor(() => expect(previewVideo().srcObject).toBe(camera.stream));

      // Requested device audio is missing: the screen fails before the camera is taken.
      await user.click(screen.getByRole("button", { name: /recordStart/ }));
      await waitFor(() => expect(mute.track.stop).toHaveBeenCalledOnce());
      expect(camera.track.stop).not.toHaveBeenCalled();
      expect(previewVideo().srcObject).toBe(camera.stream);

      // The recorder cannot be created after the camera was taken: the session releases it and
      // the dialog opens a fresh preview.
      vi.stubGlobal(
        "MediaRecorder",
        class {
          constructor() {
            throw new Error("unsupported");
          }
        },
      );
      await user.click(screen.getByRole("button", { name: /recordStart/ }));
      await waitFor(() => expect(camera.track.stop).toHaveBeenCalledOnce());
      expect(camera.audioTrack.stop).toHaveBeenCalledOnce();
      expect(screenCapture.track.stop).toHaveBeenCalledOnce();
      await waitFor(() => expect(previewVideo().srcObject).toBe(reopened.stream));
      expect(getUserMedia).toHaveBeenCalledTimes(2);
      expect(screen.getByRole("button", { name: /recordStart/ })).toBeEnabled();
    });

    it("releases the camera when the recorder closes while the screen picker is open", async () => {
      grantInputs();
      const camera = fakeStream({ audio: true });
      getUserMedia.mockResolvedValueOnce(camera.stream);
      getDisplayMedia.mockReturnValueOnce(new Promise<MediaStream>(() => {}));
      const user = userEvent.setup();

      const view = render(<Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />);
      await user.click(screen.getByRole("button", { name: "record_screenCamera" }));
      await waitFor(() => expect(previewVideo().srcObject).toBe(camera.stream));
      await user.click(screen.getByRole("button", { name: /recordStart/ }));
      view.rerender(<Recorder open={false} onOpenChange={vi.fn()} onRecorded={vi.fn()} />);

      expect(camera.track.stop).toHaveBeenCalledOnce();
      expect(getUserMedia).toHaveBeenCalledOnce();
    });

    it("surfaces a camera that cannot be opened through the permission recovery state", async () => {
      grantInputs();
      const camera = fakeStream({ audio: true });
      getUserMedia
        .mockRejectedValueOnce(new DOMException("in use", "NotReadableError"))
        .mockResolvedValueOnce(camera.stream);
      const user = userEvent.setup();

      render(<Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />);
      await user.click(screen.getByRole("button", { name: "record_camera" }));

      expect(await screen.findByRole("alert")).toHaveTextContent("recordInputPermissionTitle");
      await user.click(screen.getByRole("button", { name: "recordRetry" }));

      await waitFor(() => expect(previewVideo().srcObject).toBe(camera.stream));
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(FakeMediaRecorder.streams).toEqual([]);
    });
  });

  describe("microphone level", () => {
    function currentAudioGraph() {
      return FakeAudioContext.instances[FakeAudioContext.instances.length - 1];
    }

    function openAudioGraphs() {
      return FakeAudioContext.instances.filter((context) => !context.closed);
    }

    it("shows the level of the previewed camera's microphone before and while recording", async () => {
      grantInputs();
      const camera = fakeStream({ audio: true });
      getUserMedia.mockResolvedValueOnce(camera.stream);
      const onRecorded = vi.fn();
      const user = userEvent.setup();

      render(<Recorder open onOpenChange={vi.fn()} onRecorded={onRecorded} />);
      expect(levelMeter()).not.toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "record_camera" }));

      await waitFor(() => expect(levelMeter()).toBeInTheDocument());
      expect(currentAudioGraph().stream).toBe(camera.stream);
      expect(openAudioGraphs()).toHaveLength(1);

      await user.click(screen.getByRole("button", { name: /recordStart/ }));
      await screen.findByRole("button", { name: /recordStop/ });
      // The floating controller measures the very stream the recording took over.
      expect(levelMeter()).toBeInTheDocument();
      expect(currentAudioGraph().stream).toBe(camera.stream);
      expect(openAudioGraphs()).toHaveLength(1);

      await user.click(screen.getByRole("button", { name: /recordStop/ }));
      await waitFor(() => expect(onRecorded).toHaveBeenCalledOnce());
      expect(openAudioGraphs()).toHaveLength(0);
    });

    it("shows the level for the screen and camera session from the camera's microphone", async () => {
      grantInputs();
      const camera = fakeStream({ audio: true });
      const screenCapture = fakeStream({ audio: true });
      getUserMedia.mockResolvedValueOnce(camera.stream);
      getDisplayMedia.mockResolvedValueOnce(screenCapture.stream);
      const user = userEvent.setup();

      render(<Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />);
      await user.click(screen.getByRole("button", { name: "record_screenCamera" }));
      await waitFor(() => expect(levelMeter()).toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: /recordStart/ }));
      await screen.findByRole("button", { name: /recordStop/ });

      expect(levelMeter()).toBeInTheDocument();
      expect(currentAudioGraph().stream).toBe(camera.stream);
      expect(openAudioGraphs()).toHaveLength(1);
    });

    it("shows no level when the open stream carries no microphone", async () => {
      grantInputs();
      const camera = fakeStream();
      getUserMedia.mockResolvedValueOnce(camera.stream);
      const user = userEvent.setup();

      render(<Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />);
      await user.click(screen.getByRole("button", { name: "record_camera" }));
      await waitFor(() => expect(document.querySelector("video")?.srcObject).toBe(camera.stream));

      expect(levelMeter()).not.toBeInTheDocument();
      expect(FakeAudioContext.instances).toHaveLength(0);
    });

    it("shows no microphone level while recording the screen alone, even with device audio", async () => {
      const screenCapture = fakeStream({ audio: true });
      getDisplayMedia.mockResolvedValueOnce(screenCapture.stream);
      const user = userEvent.setup();

      render(<Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />);
      await user.click(screen.getByRole("button", { name: /recordStart/ }));
      await screen.findByRole("button", { name: /recordStop/ });

      expect(levelMeter()).not.toBeInTheDocument();
      expect(FakeAudioContext.instances).toHaveLength(0);
    });

    it("does not open the microphone for the mic source before access is granted", async () => {
      const user = userEvent.setup();

      render(<Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />);
      await waitFor(() => expect(enumerateDevices).toHaveBeenCalledOnce());
      await user.click(screen.getByRole("button", { name: "record_mic" }));

      expect(getUserMedia).not.toHaveBeenCalled();
      expect(levelMeter()).not.toBeInTheDocument();
    });

    it("opens the microphone alone for the mic source and records that same stream", async () => {
      grantInputs();
      const microphone = fakeMicrophone();
      getUserMedia.mockResolvedValueOnce(microphone.stream);
      const onRecorded = vi.fn();
      const user = userEvent.setup();

      render(<Recorder open onOpenChange={vi.fn()} onRecorded={onRecorded} />);
      await user.click(screen.getByRole("button", { name: "record_mic" }));

      await waitFor(() => expect(levelMeter()).toBeInTheDocument());
      expect(getUserMedia).toHaveBeenCalledWith({ audio: true });
      expect(currentAudioGraph().stream).toBe(microphone.stream);

      await user.click(screen.getByRole("button", { name: /recordStart/ }));
      await screen.findByRole("button", { name: /recordStop/ });
      expect(getUserMedia).toHaveBeenCalledOnce();
      expect(FakeMediaRecorder.streams).toEqual([microphone.stream]);
      expect(microphone.audioTrack.stop).not.toHaveBeenCalled();
      expect(levelMeter()).toBeInTheDocument();
      expect(currentAudioGraph().stream).toBe(microphone.stream);

      await user.click(screen.getByRole("button", { name: /recordStop/ }));
      await waitFor(() => expect(onRecorded).toHaveBeenCalledOnce());
      expect(microphone.audioTrack.stop).toHaveBeenCalledOnce();
      expect(openAudioGraphs()).toHaveLength(0);
    });

    it("follows the newly selected microphone", async () => {
      grantInputs();
      enumerateDevices.mockResolvedValue([fakeDevice("audioinput", "mic-2", "USB Microphone")]);
      const first = fakeMicrophone();
      const second = fakeMicrophone();
      getUserMedia.mockResolvedValueOnce(first.stream).mockResolvedValueOnce(second.stream);
      const user = userEvent.setup();

      render(<Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />);
      await user.click(screen.getByRole("button", { name: "record_mic" }));
      await waitFor(() => expect(currentAudioGraph()?.stream).toBe(first.stream));
      await user.click(screen.getByRole("combobox", { name: "recordMic" }));
      await user.click(await screen.findByRole("option", { name: "USB Microphone" }));

      await waitFor(() => expect(currentAudioGraph().stream).toBe(second.stream));
      expect(getUserMedia).toHaveBeenLastCalledWith({ audio: { deviceId: { exact: "mic-2" } } });
      expect(first.audioTrack.stop).toHaveBeenCalledOnce();
      expect(openAudioGraphs()).toEqual([currentAudioGraph()]);
      expect(levelMeter()).toBeInTheDocument();
    });

    it("closes the audio graph and releases the microphone when the recorder unmounts", async () => {
      grantInputs();
      const microphone = fakeMicrophone();
      getUserMedia.mockResolvedValueOnce(microphone.stream);
      const user = userEvent.setup();

      const view = render(<Recorder open onOpenChange={vi.fn()} onRecorded={vi.fn()} />);
      await user.click(screen.getByRole("button", { name: "record_mic" }));
      await waitFor(() => expect(levelMeter()).toBeInTheDocument());

      view.unmount();

      expect(openAudioGraphs()).toHaveLength(0);
      expect(microphone.audioTrack.stop).toHaveBeenCalledOnce();
    });
  });
});
