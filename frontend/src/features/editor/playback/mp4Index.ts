import { createFile, DataStream, MP4BoxBuffer, type ISOFile, type Movie, type MultiBufferStream } from "mp4box";

/**
 * 代理文件(画面代理 proxy.mp4、音频代理 audio_proxy.m4a)的**样本表**,以及按字节范围取样本数据。
 *
 * 此前每个片段各自 `fetch` 整份代理、整份交给 mp4box 解析、把每个样本的数据都留在内存里 —— 一小时的
 * 访谈切成几十段,就是几十份整代理的下载和常驻。两份代理都是 faststart(moov 在前,见后端
 * media/proxy.py),所以:先按 Range 读开头,解析出样本表(每个样本在文件里的偏移、大小、时间、是否
 * 关键帧),之后要解哪几帧 / 哪一小段声音,就只取那几个样本所在的字节。
 *
 * 这里只认文件格式,不认解码器;画面(ProxyVideoSource)和声音(AudioProxySource)各自拿它去喂
 * WebCodecs。
 */

export interface SampleRef {
  /** 在文件里的字节偏移与长度。 */
  offset: number;
  size: number;
  /** 展示时间(秒),已扣掉编辑列表的起点偏移(AAC 的编码器预延迟)。可以略小于 0。 */
  time: number;
  duration: number;
  sync: boolean;
}

export interface TrackIndex {
  codec: string;
  /** VideoDecoder / AudioDecoder 的 description(avcC 等 / AAC 的 AudioSpecificConfig)。 */
  description?: Uint8Array;
  /** 解码顺序 == 展示顺序(两份代理都没有 B 帧;音频本来就是)。 */
  samples: SampleRef[];
  width: number;
  height: number;
  sampleRate: number;
  channels: number;
}

/** 开头每次多读这么多,直到 moov 读全。一小时的画面代理 moov 约 1MB。 */
const HEAD_CHUNK = 512 * 1024;
/** 读了这么多还没见到 moov:不是 faststart,也不是我们的代理 —— 不再往下读整份文件。 */
const HEAD_LIMIT = 16 * 1024 * 1024;

/**
 * 按 Range 读一个远端文件。服务端不认 Range(回 200 整份)时把整份留下,之后的读都从里面切 ——
 * 退化成从前的整份下载,但只下一次。
 */
export class RangeReader {
  private whole: Uint8Array | null = null;

  constructor(readonly url: string) {}

  /** 读 [start, end) 字节;越过文件尾时返回短的(或空的)。 */
  async read(start: number, end: number): Promise<Uint8Array> {
    if (end <= start) return new Uint8Array(0);
    if (this.whole) return this.whole.subarray(start, Math.min(end, this.whole.byteLength));
    const res = await fetch(this.url, { headers: { Range: `bytes=${start}-${end - 1}` } });
    if (res.status === 206) return new Uint8Array(await res.arrayBuffer());
    if (res.status === 416) return new Uint8Array(0);
    if (!res.ok) throw new Error(`proxy fetch ${res.status}`);
    this.whole = new Uint8Array(await res.arrayBuffer());
    return this.whole.subarray(start, Math.min(end, this.whole.byteLength));
  }

  /** 因服务端不认 Range 而整份留在内存里的字节数。 */
  get retainedBytes(): number {
    return this.whole?.byteLength ?? 0;
  }
}

/**
 * 读开头、解析出指定种类的第一条轨的样本表。不是 faststart(读到上限还没有 moov)、没有这种轨,
 * 都抛错 —— 调用方据此把这份代理判为「这里解不了」,而不是整份下载兜底。
 */
export async function readTrackIndex(reader: RangeReader, kind: "video" | "audio"): Promise<TrackIndex> {
  const file = createFile();
  let info: Movie | null = null;
  let error: string | null = null;
  file.onReady = (movie) => {
    info = movie;
  };
  file.onError = (_module, message) => {
    error = message;
  };
  let position = 0;
  while (!info && !error && position < HEAD_LIMIT) {
    const bytes = await reader.read(position, position + HEAD_CHUNK);
    if (bytes.byteLength === 0) break;
    // MP4BoxBuffer 要一块独立的 ArrayBuffer(它会在上面挂 fileStart)。
    const copy = bytes.slice().buffer as ArrayBuffer;
    const next = file.appendBuffer(MP4BoxBuffer.fromArrayBuffer(copy, position));
    const end = position + bytes.byteLength;
    if (bytes.byteLength < HEAD_CHUNK) {
      file.flush();
      break;
    }
    // mp4box 告诉我们下一块该从哪读(moov 在后面时它会跳过 mdat);没说就接着往下。
    position = typeof next === "number" && next > position ? next : end;
  }
  if (error) throw new Error(error);
  if (!info) throw new Error("proxy has no readable moov");
  const movie = info as Movie;
  const track = kind === "video" ? movie.videoTracks[0] : movie.audioTracks[0];
  if (!track) throw new Error(`proxy has no ${kind} track`);
  const trak = file.getTrackById(track.id);
  const mediaTimescale = trak.mdia?.mdhd?.timescale || track.timescale;
  // 编辑列表的起点:AAC 编码器在开头垫了 1024 个样本的预延迟,不扣掉的话整段声音晚 21ms。
  const mediaTime = Number(trak.edts?.elst?.entries?.[0]?.media_time ?? 0);
  const shift = mediaTime > 0 ? mediaTime / mediaTimescale : 0;
  const samples = file.getTrackSamplesInfo(track.id).map((s) => ({
    offset: s.offset,
    size: s.size,
    time: s.cts / s.timescale - shift,
    duration: s.duration / s.timescale,
    sync: s.is_sync,
  }));
  return {
    codec: track.codec,
    description: kind === "video" ? videoDescription(file) : audioDescription(trak),
    samples,
    width: track.track_width ?? 0,
    height: track.track_height ?? 0,
    sampleRate: track.audio?.sample_rate ?? 0,
    channels: track.audio?.channel_count ?? 0,
  };
}

/** avcC/hvcC 等盒子的字节(去掉 8 字节盒头),VideoDecoder.configure 要它。 */
function videoDescription(file: ISOFile): Uint8Array | undefined {
  for (const type of ["avcC", "hvcC", "vpcC", "av1C"] as const) {
    const box = file.getBox(type);
    if (!box) continue;
    const stream = new DataStream(undefined, 0); // defaults to big-endian
    // Runtime: box.write drives a DataStream (the canonical mp4box+WebCodecs path);
    // its typings ask for the MultiBufferStream subclass, so bridge with a cast.
    box.write(stream as unknown as MultiBufferStream);
    return new Uint8Array(stream.buffer.slice(8));
  }
  return undefined;
}

/** AAC 的 AudioSpecificConfig:esds → DecoderConfigDescriptor(0x04)→ DecSpecificInfo(0x05)。 */
function audioDescription(trak: ReturnType<ISOFile["getTrackById"]>): Uint8Array | undefined {
  const entry = trak.mdia?.minf?.stbl?.stsd?.entries?.[0] as { esds?: { esd?: { findDescriptor(tag: number): unknown } } } | undefined;
  const config = entry?.esds?.esd?.findDescriptor(0x04) as { findDescriptor(tag: number): { data?: Uint8Array } | undefined } | undefined;
  const data = config?.findDescriptor(0x05)?.data;
  return data ? new Uint8Array(data) : undefined;
}

/** 第一个展示时间 > sec 的样本之前那一个(即覆盖 sec 的样本);sec 早于第一帧时为 0。二分。 */
export function sampleIndexAt(samples: readonly SampleRef[], sec: number): number {
  let lo = 0;
  let hi = samples.length - 1;
  let ans = 0;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (samples[mid].time <= sec) {
      ans = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return ans;
}

/** 样本 [from, to] 在文件里覆盖的字节范围 [start, end)。两份代理的样本按解码顺序连续排在 mdat 里。 */
export function byteSpan(samples: readonly SampleRef[], from: number, to: number): { start: number; end: number } {
  let start = Number.POSITIVE_INFINITY;
  let end = 0;
  for (let i = from; i <= to; i++) {
    start = Math.min(start, samples[i].offset);
    end = Math.max(end, samples[i].offset + samples[i].size);
  }
  return { start, end };
}
