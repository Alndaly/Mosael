/**
 * 把「系统声音」和「麦克风」混成一条音轨。
 *
 * 屏幕录制此前只能二选一:要么录系统声音(看视频、放音乐),要么单独录麦克风(另一种来源)。
 * 讲课时两样都要 —— 既要有屏幕里的声音,也要有自己的解说,而 MediaRecorder 一个流上只认一条
 * 音轨,所以必须在录之前把两路混成一路。
 *
 * 走 Web Audio(而不是自己拼 PCM):`MediaStreamAudioDestinationNode` 交出来的就是一条可以
 * 直接塞进 `MediaStream` 给 MediaRecorder 的轨道,采样率、声道、重采样都由浏览器处理。
 */
export interface MixedAudio {
  /** 混好之后的那条轨道(已经在 `stream` 里)。 */
  stream: MediaStream;
  /** 收工:断开节点、关掉 AudioContext。麦克风本身由调用方负责停。 */
  release: () => void;
}

interface AudioContextLike {
  createMediaStreamSource(stream: MediaStream): { connect(node: unknown): void; disconnect(): void };
  createMediaStreamDestination(): { stream: MediaStream };
  close(): Promise<void>;
  resume?(): Promise<void>;
}

/**
 * `null` 表示**没有可混的东西**(两路都空,或者这个运行时没有 Web Audio)——
 * 调用方按「保持原样」处理,不要因为混音失败就把整次录制变成失败。
 */
export function mixAudioTracks(
  systemAudio: MediaStream | null,
  microphoneAudio: MediaStream | null,
  createContext: () => AudioContextLike | null = defaultContext,
): MixedAudio | null {
  const sources = [systemAudio, microphoneAudio].filter(
    (stream): stream is MediaStream => Boolean(stream) && hasAudio(stream as MediaStream),
  );
  if (sources.length === 0) return null;
  //: 只有一路时不必混(也少一次重采样):直接用它,调用方仍按统一的 MixedAudio 处理。
  if (sources.length === 1) {
    return { stream: sources[0], release: () => undefined };
  }
  const context = createContext();
  if (!context) return null;
  try {
    const destination = context.createMediaStreamDestination();
    const nodes = sources.map((stream) => {
      const node = context.createMediaStreamSource(stream);
      node.connect(destination);
      return node;
    });
    void context.resume?.().catch(() => undefined);
    return {
      stream: destination.stream,
      release: () => {
        for (const node of nodes) {
          try {
            node.disconnect();
          } catch {
            /* 已经断了 */
          }
        }
        void context.close().catch(() => undefined);
      },
    };
  } catch {
    void context.close().catch(() => undefined);
    return null;
  }
}

function hasAudio(stream: MediaStream): boolean {
  return stream.getAudioTracks().some((track) => track.readyState === "live");
}

function defaultContext(): AudioContextLike | null {
  const Ctor = (globalThis as { AudioContext?: new () => AudioContextLike }).AudioContext;
  return Ctor ? new Ctor() : null;
}
