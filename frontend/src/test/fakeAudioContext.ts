import { vi } from "vitest";

/**
 * A Web Audio stand-in for jsdom, which has no AudioContext. It records every graph built on it,
 * so tests can assert which stream a meter analyses and that the graph was torn down. `level`
 * (0-1) is the amplitude the analysers report for their next read.
 */
export class FakeAudioContext {
  static instances: FakeAudioContext[] = [];
  static level = 0;

  static reset() {
    FakeAudioContext.instances = [];
    FakeAudioContext.level = 0;
  }

  state: AudioContextState = "running";
  readonly sources: { stream: MediaStream; connect: ReturnType<typeof vi.fn>; disconnect: ReturnType<typeof vi.fn> }[] =
    [];
  readonly analysers: { disconnect: ReturnType<typeof vi.fn> }[] = [];
  readonly close = vi.fn(async () => {
    this.state = "closed";
  });
  readonly resume = vi.fn(async () => {});

  constructor() {
    FakeAudioContext.instances.push(this);
  }

  get closed() {
    return this.state === "closed";
  }

  /** The stream of the graph's source, i.e. what this context is measuring. */
  get stream() {
    return this.sources[0]?.stream ?? null;
  }

  createMediaStreamSource(stream: MediaStream) {
    const source = { stream, connect: vi.fn(), disconnect: vi.fn() };
    this.sources.push(source);
    return source;
  }

  createAnalyser() {
    const analyser = {
      fftSize: 2048,
      connect: vi.fn(),
      disconnect: vi.fn(),
      getByteTimeDomainData(samples: Uint8Array) {
        // A square wave at the current level: every other sample swings away from the midpoint.
        const swing = Math.round(FakeAudioContext.level * 127);
        samples.forEach((_, index) => {
          samples[index] = index % 2 === 0 ? 128 + swing : 128 - swing;
        });
      },
    };
    this.analysers.push(analyser);
    return analyser;
  }
}
