/** @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FakeAudioContext } from "@/test/fakeAudioContext";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { MicrophoneLevelMeter } from "./MicrophoneLevelMeter";

function fakeStream({ audio }: { audio: boolean }) {
  const audioTrack = { kind: "audio", stop: vi.fn() };
  return {
    getAudioTracks: () => (audio ? [audioTrack] : []),
    getTracks: () => (audio ? [audioTrack] : []),
  } as unknown as MediaStream;
}

/** Animation frames run only when a test advances them, so each frame's effect is observable. */
function controlAnimationFrames() {
  const pending = new Map<number, FrameRequestCallback>();
  let nextId = 0;
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    nextId += 1;
    pending.set(nextId, callback);
    return nextId;
  });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => pending.delete(id));
  return {
    pending: () => pending.size,
    step() {
      const callbacks = [...pending.values()];
      pending.clear();
      callbacks.forEach((callback) => callback(performance.now()));
    },
  };
}

function bar() {
  return screen.getByRole("meter").querySelector<HTMLElement>("[style]")!;
}

describe("MicrophoneLevelMeter", () => {
  let frames: ReturnType<typeof controlAnimationFrames>;

  beforeEach(() => {
    FakeAudioContext.reset();
    vi.stubGlobal("AudioContext", FakeAudioContext);
    frames = controlAnimationFrames();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders nothing and opens no audio graph for a stream without a microphone", () => {
    render(<MicrophoneLevelMeter stream={fakeStream({ audio: false })} />);

    expect(screen.queryByRole("meter")).not.toBeInTheDocument();
    expect(FakeAudioContext.instances).toHaveLength(0);
  });

  it("analyses the stream it is given and draws its level once per animation frame", () => {
    const stream = fakeStream({ audio: true });
    render(<MicrophoneLevelMeter stream={stream} />);

    const meter = screen.getByRole("meter", { name: "recordLevel" });
    expect(FakeAudioContext.instances).toHaveLength(1);
    expect(FakeAudioContext.instances[0].stream).toBe(stream);
    expect(FakeAudioContext.instances[0].resume).toHaveBeenCalledOnce();

    FakeAudioContext.level = 0.5;
    frames.step();
    expect(bar().style.transform).toBe("scaleX(0.65)");
    expect(meter).toHaveAttribute("aria-valuenow", "0.65");
    expect(meter).toHaveAttribute("data-active", "true");

    // Silence decays the bar instead of dropping it, and greys it out at once.
    FakeAudioContext.level = 0;
    frames.step();
    expect(bar().style.transform).toBe("scaleX(0.55)");
    expect(meter).toHaveAttribute("data-active", "false");
    expect(frames.pending()).toBe(1);
  });

  it("closes the old graph and analyses the new stream when the stream changes", () => {
    const first = fakeStream({ audio: true });
    const second = fakeStream({ audio: true });
    const view = render(<MicrophoneLevelMeter stream={first} />);
    FakeAudioContext.level = 1;
    frames.step();

    view.rerender(<MicrophoneLevelMeter stream={second} />);

    const [old, current] = FakeAudioContext.instances;
    expect(old.closed).toBe(true);
    expect(old.sources[0].disconnect).toHaveBeenCalledOnce();
    expect(old.analysers[0].disconnect).toHaveBeenCalledOnce();
    expect(current.stream).toBe(second);
    expect(current.closed).toBe(false);
    expect(bar().style.transform).toBe("scaleX(0)");
    expect(frames.pending()).toBe(1);
  });

  it("closes the graph and stops drawing when a stream loses its meter or the meter unmounts", () => {
    const view = render(<MicrophoneLevelMeter stream={fakeStream({ audio: true })} />);

    view.rerender(<MicrophoneLevelMeter stream={fakeStream({ audio: false })} />);
    expect(FakeAudioContext.instances[0].closed).toBe(true);
    expect(screen.queryByRole("meter")).not.toBeInTheDocument();
    expect(frames.pending()).toBe(0);

    view.rerender(<MicrophoneLevelMeter stream={fakeStream({ audio: true })} />);
    view.unmount();
    expect(FakeAudioContext.instances[1].closed).toBe(true);
    expect(frames.pending()).toBe(0);
  });

  it("does not show a frozen level when Web Audio is unavailable", () => {
    vi.stubGlobal(
      "AudioContext",
      class {
        constructor() {
          throw new Error("unsupported");
        }
      },
    );

    render(<MicrophoneLevelMeter stream={fakeStream({ audio: true })} />);

    expect(screen.queryByRole("meter")).not.toBeInTheDocument();
    expect(frames.pending()).toBe(0);
  });
});
