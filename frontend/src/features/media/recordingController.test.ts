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

function cameraSource(stream: MediaStream | Promise<MediaStream>) {
  return { take: vi.fn(() => Promise.resolve(stream)) };
}

const noCamera = { take: vi.fn(() => Promise.reject(new Error("no camera expected"))) };

describe("recording controller", () => {
  it("acquires screen and camera as independent session inputs", async () => {
    const screen = fakeStream({ audio: true });
    const camera = fakeStream({ audio: true });
    const deps = dependencies();
    deps.getDisplayMedia.mockResolvedValue(screen.stream);
    const camera$ = cameraSource(camera.stream);
    const requestStop = vi.fn();
    const controller = createRecordingController(deps.value);

    const active = await controller.start({
      source: "screenCamera",
      captureSystemAudio: true,
      camera: camera$,
      micId: "mic-1",
      mirrorCamera: false,
      filenames,
      requestStop,
    });

    expect(deps.getDisplayMedia).toHaveBeenCalledWith({ video: true, audio: true });
    // The camera comes from the caller's (already open) camera source, never a second getUserMedia.
    expect(camera$.take).toHaveBeenCalledOnce();
    expect(deps.getUserMedia).not.toHaveBeenCalled();
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

  it("mirrors the camera from its stream alone, while the preview shows the raw camera", async () => {
    const camera = fakeStream({ audio: true });
    const mirrored = { stream: fakeStream().stream, release: vi.fn() };
    const createMirroredCapture = vi.fn(() => mirrored);
    const deps = dependencies({ createMirroredCapture });
    const controller = createRecordingController(deps.value);

    const active = await controller.start({
      source: "camera",
      captureSystemAudio: false,
      camera: cameraSource(camera.stream),
      mirrorCamera: true,
      filenames,
      requestStop: vi.fn(),
    });

    expect(createMirroredCapture).toHaveBeenCalledWith(camera.stream);
    expect(deps.createSession).toHaveBeenCalledWith(
      [{ kind: "camera", stream: mirrored.stream, filenamePrefix: "camera", release: mirrored.release }],
      expect.objectContaining({ onError: expect.any(Function) }),
    );
    expect(active.previewStreams).toEqual({ screen: null, camera: camera.stream });
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
        camera: noCamera,
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
    const controller = createRecordingController(deps.value);

    await expect(
      controller.start({
        source: "screenCamera",
        captureSystemAudio: true,
        camera: { take: () => Promise.reject(new DOMException("denied", "NotAllowedError")) },
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
      camera: noCamera,
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
      camera: noCamera,
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

  it("leaves the camera with its source when the screen picker is dismissed", async () => {
    const deps = dependencies();
    deps.getDisplayMedia.mockRejectedValue(new DOMException("dismissed", "NotAllowedError"));
    const camera$ = cameraSource(fakeStream().stream);
    const controller = createRecordingController(deps.value);

    await expect(
      controller.start({
        source: "screenCamera",
        captureSystemAudio: true,
        camera: camera$,
        mirrorCamera: false,
        filenames,
        requestStop: vi.fn(),
      }),
    ).rejects.toMatchObject({ issue: "screen" } satisfies Partial<RecordingStartError>);

    expect(camera$.take).not.toHaveBeenCalled();
  });

  it("stops a taken camera when the UI closes while it is being handed over", async () => {
    const camera = fakeStream({ audio: true });
    const deps = dependencies();
    let resolveCamera!: (stream: MediaStream) => void;
    const controller = createRecordingController(deps.value);
    const starting = controller.start({
      source: "camera",
      captureSystemAudio: false,
      camera: cameraSource(
        new Promise<MediaStream>((resolve) => {
          resolveCamera = resolve;
        }),
      ),
      mirrorCamera: false,
      filenames,
      requestStop: vi.fn(),
    });

    controller.cancel();
    resolveCamera(camera.stream);

    await expect(starting).rejects.toMatchObject({ name: "RecordingCancelledError" });
    expect(camera.videoTrack.stop).toHaveBeenCalledOnce();
    expect(camera.audioTrack.stop).toHaveBeenCalledOnce();
    expect(deps.createSession).not.toHaveBeenCalled();
  });
});
