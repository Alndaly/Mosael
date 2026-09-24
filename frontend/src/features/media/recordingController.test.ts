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
  const createSession = vi.fn((_inputs: readonly RecordingInput[]) => session);
  return {
    session,
    getDisplayMedia,
    createSession,
    value: {
      mediaDevices: { getDisplayMedia },
      createSession,
      createMirroredCapture: vi.fn(),
      ...overrides,
    } satisfies RecordingControllerDependencies,
  };
}

const filenames = { screen: "screen", camera: "camera", mic: "mic" };

function inputSource(stream: MediaStream | Promise<MediaStream>) {
  return { take: vi.fn(() => Promise.resolve(stream)) };
}

const noInputs = { take: vi.fn(() => Promise.reject(new Error("no camera expected"))) };

describe("recording controller", () => {
  it("acquires screen and camera as independent session inputs", async () => {
    const screen = fakeStream({ audio: true });
    const camera = fakeStream({ audio: true });
    const deps = dependencies();
    deps.getDisplayMedia.mockResolvedValue(screen.stream);
    const camera$ = inputSource(camera.stream);
    const requestStop = vi.fn();
    const controller = createRecordingController(deps.value);

    const active = await controller.start({
      source: "screenCamera",
      captureSystemAudio: true,
      inputs: camera$,
      mirrorCamera: false,
      filenames,
      requestStop,
    });

    expect(deps.getDisplayMedia).toHaveBeenCalledWith({ video: true, audio: true });
    // The camera comes from the caller's (already open) input source.
    expect(camera$.take).toHaveBeenCalledOnce();
    expect(deps.createSession).toHaveBeenCalledWith(
      [
        { kind: "screen", stream: screen.stream, filenamePrefix: "screen" },
        { kind: "camera", stream: camera.stream, filenamePrefix: "camera" },
      ],
      expect.objectContaining({ onError: expect.any(Function) }),
    );
    expect(deps.session.start).toHaveBeenCalledOnce();
    // The level follows the microphone carried by the camera stream, never the screen's device audio.
    expect(active.previewStreams).toEqual({
      screen: screen.stream,
      camera: camera.stream,
      microphone: camera.stream,
    });

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
      inputs: inputSource(camera.stream),
      mirrorCamera: true,
      filenames,
      requestStop: vi.fn(),
    });

    expect(createMirroredCapture).toHaveBeenCalledWith(camera.stream);
    expect(deps.createSession).toHaveBeenCalledWith(
      [{ kind: "camera", stream: mirrored.stream, filenamePrefix: "camera", release: mirrored.release }],
      expect.objectContaining({ onError: expect.any(Function) }),
    );
    expect(active.previewStreams).toEqual({ screen: null, camera: camera.stream, microphone: camera.stream });
  });

  it("records the microphone taken from the input source", async () => {
    const microphone = fakeStream({ audio: true });
    const deps = dependencies();
    const microphone$ = inputSource(microphone.stream);
    const controller = createRecordingController(deps.value);

    const active = await controller.start({
      source: "mic",
      captureSystemAudio: false,
      inputs: microphone$,
      mirrorCamera: false,
      filenames,
      requestStop: vi.fn(),
    });

    expect(microphone$.take).toHaveBeenCalledOnce();
    expect(deps.createSession).toHaveBeenCalledWith(
      [{ kind: "mic", stream: microphone.stream, filenamePrefix: "mic" }],
      expect.objectContaining({ onError: expect.any(Function) }),
    );
    expect(active.previewStreams).toEqual({ screen: null, camera: null, microphone: microphone.stream });
  });

  it("reports no microphone for a screen recording, even with device audio", async () => {
    const screen = fakeStream({ audio: true });
    const deps = dependencies();
    deps.getDisplayMedia.mockResolvedValue(screen.stream);
    const controller = createRecordingController(deps.value);

    const active = await controller.start({
      source: "screen",
      captureSystemAudio: true,
      inputs: noInputs,
      mirrorCamera: false,
      filenames,
      requestStop: vi.fn(),
    });

    expect(active.previewStreams).toEqual({ screen: screen.stream, camera: null, microphone: null });
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
        inputs: noInputs,
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
        inputs: { take: () => Promise.reject(new DOMException("denied", "NotAllowedError")) },
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
      inputs: noInputs,
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
      inputs: noInputs,
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
    const camera$ = inputSource(fakeStream().stream);
    const controller = createRecordingController(deps.value);

    await expect(
      controller.start({
        source: "screenCamera",
        captureSystemAudio: true,
        inputs: camera$,
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
      inputs: inputSource(
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
