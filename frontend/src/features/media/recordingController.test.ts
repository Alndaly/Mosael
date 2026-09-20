import { describe, expect, it, vi } from "vitest";

import {
  createRecordingController,
  RecordingStartError,
  type RecordingControllerDependencies,
} from "./recordingController";
import type { RecordingInput, RecordingSession } from "./recordingSession";

function fakeStream({ audio = false }: { audio?: boolean } = {}) {
  const listeners = new Map<string, EventListener>();
  const videoTrack = {
    stop: vi.fn(),
    addEventListener: vi.fn((type: string, listener: EventListener) => listeners.set(type, listener)),
    removeEventListener: vi.fn((type: string, listener: EventListener) => {
      if (listeners.get(type) === listener) listeners.delete(type);
    }),
  };
  const audioTrack = { stop: vi.fn(), readyState: "live" as MediaStreamTrackState };
  const stream = {
    getTracks: () => (audio ? [videoTrack, audioTrack] : [videoTrack]),
    getVideoTracks: () => [videoTrack],
    getAudioTracks: () => (audio ? [audioTrack] : []),
  } as unknown as MediaStream;
  return {
    stream,
    videoTrack,
    audioTrack,
    end: () => listeners.get("ended")?.(new Event("ended")),
  };
}

function dependencies(overrides: Partial<RecordingControllerDependencies> = {}) {
  const session: RecordingSession = {
    start: vi.fn(),
    stop: vi.fn().mockResolvedValue([new File(["recorded"], "capture.webm")]),
    cancel: vi.fn(),
  };
  const getDisplayMedia = vi.fn();
  const getUserMedia = vi.fn();
  const createSession = vi.fn((_inputs: readonly RecordingInput[]) => session);
  return {
    session,
    getDisplayMedia,
    getUserMedia,
    createSession,
    value: {
      mediaDevices: { getDisplayMedia, getUserMedia },
      createSession,
      createMirroredCapture: vi.fn(),
      ...overrides,
    } satisfies RecordingControllerDependencies,
  };
}

const filenames = { screen: "screen", camera: "camera", mic: "mic" };

describe("recording controller", () => {
  it("acquires screen and camera as independent session inputs", async () => {
    const screen = fakeStream({ audio: true });
    const camera = fakeStream({ audio: true });
    const deps = dependencies();
    deps.getDisplayMedia.mockResolvedValue(screen.stream);
    deps.getUserMedia.mockResolvedValue(camera.stream);
    const requestStop = vi.fn();
    const controller = createRecordingController(deps.value);

    const active = await controller.start({
      source: "screenCamera",
      captureSystemAudio: true,
      cameraId: "camera-1",
      micId: "mic-1",
      mirrorCamera: false,
      filenames,
      requestStop,
    });

    expect(deps.getDisplayMedia).toHaveBeenCalledWith({ video: true, audio: true });
    expect(deps.getUserMedia).toHaveBeenCalledWith({
      video: { deviceId: { exact: "camera-1" } },
      audio: { deviceId: { exact: "mic-1" } },
    });
    expect(deps.createSession).toHaveBeenCalledWith(
      [
        { kind: "screen", stream: screen.stream, filenamePrefix: "screen" },
        { kind: "camera", stream: camera.stream, filenamePrefix: "camera" },
      ],
      expect.objectContaining({ onError: expect.any(Function) }),
    );
    expect(deps.session.start).toHaveBeenCalledOnce();
    expect(active.previewStreams).toEqual({ screen: screen.stream, camera: camera.stream });
    expect(active.levelStream).toBe(camera.stream);

    screen.end();
    expect(requestStop).toHaveBeenCalledOnce();
  });

  it("rejects missing requested system audio and releases the partial capture", async () => {
    const screen = fakeStream();
    const deps = dependencies();
    deps.getDisplayMedia.mockResolvedValue(screen.stream);
    const controller = createRecordingController(deps.value);

    await expect(
      controller.start({
        source: "screen",
        captureSystemAudio: true,
        mirrorCamera: false,
        filenames,
        requestStop: vi.fn(),
      }),
    ).rejects.toMatchObject({ issue: "systemAudio" } satisfies Partial<RecordingStartError>);

    expect(screen.videoTrack.stop).toHaveBeenCalledOnce();
    expect(deps.createSession).not.toHaveBeenCalled();
  });

  it("releases screen capture when the later camera request fails", async () => {
    const screen = fakeStream({ audio: true });
    const deps = dependencies();
    deps.getDisplayMedia.mockResolvedValue(screen.stream);
    deps.getUserMedia.mockRejectedValue(new DOMException("denied", "NotAllowedError"));
    const controller = createRecordingController(deps.value);

    await expect(
      controller.start({
        source: "screenCamera",
        captureSystemAudio: true,
        mirrorCamera: false,
        filenames,
        requestStop: vi.fn(),
      }),
    ).rejects.toMatchObject({ issue: "cameraMicrophone" } satisfies Partial<RecordingStartError>);

    expect(screen.videoTrack.stop).toHaveBeenCalledOnce();
    expect(screen.audioTrack.stop).toHaveBeenCalledOnce();
  });

  it("finalizes once when stop is requested concurrently", async () => {
    const screen = fakeStream({ audio: true });
    const deps = dependencies();
    deps.getDisplayMedia.mockResolvedValue(screen.stream);
    const controller = createRecordingController(deps.value);
    await controller.start({
      source: "screen",
      captureSystemAudio: true,
      mirrorCamera: false,
      filenames,
      requestStop: vi.fn(),
    });

    const first = controller.stop();
    const second = controller.stop();

    expect(first).toBe(second);
    await expect(first).resolves.toHaveLength(1);
    expect(deps.session.stop).toHaveBeenCalledOnce();
    expect(screen.videoTrack.removeEventListener).toHaveBeenCalledOnce();
  });

  it("cancels resources acquired after the UI closes during a pending request", async () => {
    const screen = fakeStream({ audio: true });
    const deps = dependencies();
    let resolveDisplay!: (stream: MediaStream) => void;
    deps.getDisplayMedia.mockReturnValue(
      new Promise<MediaStream>((resolve) => {
        resolveDisplay = resolve;
      }),
    );
    const controller = createRecordingController(deps.value);
    const starting = controller.start({
      source: "screen",
      captureSystemAudio: true,
      mirrorCamera: false,
      filenames,
      requestStop: vi.fn(),
    });

    controller.cancel();
    resolveDisplay(screen.stream);

    await expect(starting).rejects.toMatchObject({ name: "RecordingCancelledError" });
    expect(screen.videoTrack.stop).toHaveBeenCalledOnce();
    expect(screen.audioTrack.stop).toHaveBeenCalledOnce();
  });
});
