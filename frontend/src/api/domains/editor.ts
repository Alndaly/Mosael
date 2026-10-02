import type { components } from "@/api/generated/schema";
import type { Job } from "@/api/domains/jobs";
import { API_BASE, ApiError, api, apiBlob, getAuthToken } from "@/api/transport";

export type Sequence = components["schemas"]["SequenceOut"];

/**
 * 链接片段(`Clip.link_group`:视频与分离出的音频)默认整组移动 / 修剪 / 切分 / 删除 / 变速。
 * `linked: false` 是「临时解链」:这一下只动点中的那段(后端 sequences/links.py)。
 */
export type LinkOption = { linked?: boolean };
export type Track = components["schemas"]["TrackOut"];
export type Clip = components["schemas"]["ClipOut"];

/**
 * 一次编辑照着的那一版:时间线的 id 和调用方看到的版本号。每个编辑请求都带上它(`base_revision`)——
 * 时间线在这期间被别人改过、而这一步和那些改动对不上时,服务端回 409 并附上最新的一版,不在一份过时的时间线上
 * 替人做决定(见后端 domain/sequences/concurrency)。**类型上必填**:漏传版本号的编辑写不出来。
 */
export type SequenceRef = Pick<Sequence, "id" | "revision">;

/**
 * 这个客户端从自己的编辑回包(和 409 附带的最新序列)里见过的最新版本号。
 *
 * 调用方手里的那份可能还没来得及换成上一步的回包(onSuccess 里用的是重新拉取、或闭包里还是上一次渲染的序列),
 * 只按它报版本号的话,连着做的第二步会把**自己刚做的第一步**当成别人的改动、被 409 挡下。取两者里新的那个:
 * 回包是自己这一步换来的,算「看到过」。
 */
const knownRevisions = new Map<string, number>();

function remember(sequence: Sequence): void {
  knownRevisions.set(sequence.id, Math.max(sequence.revision, knownRevisions.get(sequence.id) ?? sequence.revision));
}

/** 这一步该报的版本号:调用方手里那份和自己见过的回包里新的那个。 */
export function baseRevisionOf(sequence: SequenceRef): number {
  return Math.max(sequence.revision, knownRevisions.get(sequence.id) ?? sequence.revision);
}

type ConflictListener = (latest: Sequence) => void;
const conflictListeners = new Set<ConflictListener>();

/**
 * 编辑(或撤销 / 重做)撞上 409 时,服务端附上的最新序列送到这里 —— 剪辑页、画板上的时间线格各自把手里的缓存换成它。
 * 提示那一句不在这里弹:409 照常抛给发起的那个 mutation,它(或全局的兜底)弹服务端那句话(说清是谁改的)。
 */
export function onSequenceConflict(listener: ConflictListener): () => void {
  conflictListeners.add(listener);
  return () => conflictListeners.delete(listener);
}

/** 409 里附带的最新序列;不是时间线的版本冲突就是 null。 */
export function conflictLatest(error: unknown): Sequence | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  try {
    const detail = (JSON.parse(error.body) as { detail?: { code?: unknown; sequence?: Sequence } }).detail;
    return detail?.code === "sequence_revision_conflict" && detail.sequence ? detail.sequence : null;
  } catch {
    return null;
  }
}

async function send(sequenceId: string, path: string, init: RequestInit): Promise<Sequence> {
  try {
    const next = await api<Sequence>(`/api/sequences/${sequenceId}${path}`, init);
    remember(next);
    return next;
  } catch (error) {
    noticeConflict(error);
    throw error;
  }
}

/** 撞上 409 时把附带的最新序列记下、交给订阅的人(剪辑页、画板时间线格)。不是版本冲突就什么都不做。
 *  排任务的编辑(配音)不回序列,也走它:冲突时剪辑页照样换成最新的一版。 */
export function noticeConflict(error: unknown): void {
  const latest = conflictLatest(error);
  if (latest) {
    remember(latest);
    for (const listener of conflictListeners) listener(latest);
  }
}

/** 一次编辑:照着 `sequence` 那一版做(带上 base_revision)。 */
function edit(sequence: SequenceRef, path: string, init: RequestInit): Promise<Sequence> {
  const separator = path.includes("?") ? "&" : "?";
  return send(sequence.id, `${path}${separator}base_revision=${baseRevisionOf(sequence)}`, init);
}

export function insertClip(
  sequence: SequenceRef,
  body: {
    track_id: string;
    asset_id: string;
    timeline_start: number;
    src_in: number;
    src_out: number;
    ripple?: boolean;
  },
): Promise<Sequence> {
  return edit(sequence, "/clips", { method: "POST", body: JSON.stringify(body) });
}

export function moveClip(
  sequence: SequenceRef,
  clipId: string,
  body: { timeline_start: number; track_id?: string | null; ripple?: boolean } & LinkOption,
): Promise<Sequence> {
  return edit(sequence, `/clips/${clipId}/move`, { method: "PATCH", body: JSON.stringify(body) });
}

/** One batch is one operation and therefore one undo step. */
export function deleteClipsBatch(sequence: SequenceRef, clipIds: string[], options: LinkOption = {}): Promise<Sequence> {
  return edit(sequence, "/clips/delete-batch", { method: "POST", body: JSON.stringify({ clip_ids: clipIds, ...options }) });
}

export function getSequence(sequenceId: string): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}`);
}

/**
 * 把整段素材接到它那种轨道的末尾;时间线还空着时画幅跟着它走(后端 sequences.append)。
 * 不带版本号:「末尾」本来就由服务端按现状算,画板上连线接素材时那条时间线常常还没在这个客户端里打开过。
 */
export function appendAssetToSequence(sequenceId: string, assetId: string): Promise<Sequence> {
  return send(sequenceId, "/append", { method: "POST", body: JSON.stringify({ asset_id: assetId }) });
}

/**
 * 波纹删除。默认:被删片段和它的链接组员在各自的轨上删掉、后面的左移。
 * `all_tracks: true`:这段时间从所有**未锁定**的轨上拿掉(区间里的都挖掉、后面的一起左移),锁定轨不动。
 */
export type RippleDeleteOptions = LinkOption & { all_tracks?: boolean };

export function rippleDeleteClipsBatch(
  sequence: SequenceRef,
  clipIds: string[],
  options: RippleDeleteOptions = {},
): Promise<Sequence> {
  return edit(sequence, "/clips/ripple-delete-batch", {
    method: "POST",
    body: JSON.stringify({ clip_ids: clipIds, ...options }),
  });
}

export function moveClipsBatch(
  sequence: SequenceRef,
  moves: { clip_id: string; timeline_start: number; track_id?: string | null }[],
  options: LinkOption = {},
): Promise<Sequence> {
  return edit(sequence, "/clips/move-batch", { method: "PATCH", body: JSON.stringify({ moves, ...options }) });
}

export function trimClip(
  sequence: SequenceRef,
  clipId: string,
  body: { timeline_start: number; src_in: number; src_out: number } & LinkOption,
): Promise<Sequence> {
  return edit(sequence, `/clips/${clipId}/trim`, { method: "PATCH", body: JSON.stringify(body) });
}

/**
 * 按文字剪是波纹删除:同轨后面的左移,链接的音频同步剪(`linked: false` 时不剪),
 * 未锁定字幕轨上落在区间里的字幕删掉、后面的左移;整批一步撤销。
 */
export function cutClipRange(
  sequence: SequenceRef,
  clipId: string,
  body: { src_start: number; src_end: number },
  options: LinkOption = {},
): Promise<Sequence> {
  const query = options.linked === false ? "?linked=false" : "";
  return edit(sequence, `/clips/${clipId}/cut-range${query}`, { method: "POST", body: JSON.stringify(body) });
}

export function deleteClip(sequence: SequenceRef, clipId: string, options: LinkOption = {}): Promise<Sequence> {
  const query = options.linked === false ? "?linked=false" : "";
  return edit(sequence, `/clips/${clipId}${query}`, { method: "DELETE" });
}

export function cutClipRanges(
  sequence: SequenceRef,
  clipId: string,
  ranges: Array<{ src_start: number; src_end: number }>,
  options: LinkOption = {},
): Promise<Sequence> {
  return edit(sequence, `/clips/${clipId}/cut-ranges`, { method: "POST", body: JSON.stringify({ ranges, ...options }) });
}

export function cutClipRangesBatch(
  sequence: SequenceRef,
  cuts: Array<{ clip_id: string; ranges: Array<{ src_start: number; src_end: number }> }>,
  options: LinkOption = {},
): Promise<Sequence> {
  return edit(sequence, "/clips/cut-ranges", { method: "POST", body: JSON.stringify({ cuts, ...options }) });
}

/**
 * `ripple`(默认 true,剪映的习惯):变速后同轨后续片段跟着推开 / 拉回。
 * false:后面的不动;慢放会盖住下一段时后端拒绝(422),不替用户裁掉下一段。
 */
export function setClipSpeed(
  sequence: SequenceRef,
  clipId: string,
  speed: number,
  options: { ripple?: boolean } & LinkOption = {},
): Promise<Sequence> {
  return edit(sequence, `/clips/${clipId}/speed`, { method: "PATCH", body: JSON.stringify({ speed, ...options }) });
}

export function setClipGain(sequence: SequenceRef, clipId: string, gain: number, muted: boolean): Promise<Sequence> {
  return edit(sequence, `/clips/${clipId}/gain`, { method: "PATCH", body: JSON.stringify({ gain, muted }) });
}

export function detachClipAudio(sequence: SequenceRef, clipId: string): Promise<Sequence> {
  return edit(sequence, `/clips/${clipId}/detach-audio`, { method: "POST" });
}

export function setClipTransform(
  sequence: SequenceRef,
  clipId: string,
  transform: Record<string, unknown>,
): Promise<Sequence> {
  return edit(sequence, `/clips/${clipId}/transform`, { method: "PATCH", body: JSON.stringify({ transform }) });
}

export function setSequenceReframe(
  sequence: SequenceRef,
  reframe: { width: number; height: number; fill_mode: string },
): Promise<Sequence> {
  return edit(sequence, "/reframe", { method: "PATCH", body: JSON.stringify(reframe) });
}

export function rippleDeleteClip(
  sequence: SequenceRef,
  clipId: string,
  options: RippleDeleteOptions = {},
): Promise<Sequence> {
  const query = new URLSearchParams();
  if (options.linked === false) query.set("linked", "false");
  if (options.all_tracks) query.set("all_tracks", "true");
  const suffix = query.size ? `?${query}` : "";
  return edit(sequence, `/clips/${clipId}/ripple${suffix}`, { method: "DELETE" });
}

export function splitClip(
  sequence: SequenceRef,
  clipId: string,
  srcTime: number,
  options: LinkOption = {},
): Promise<Sequence> {
  return edit(sequence, `/clips/${clipId}/split`, {
    method: "POST",
    body: JSON.stringify({ src_time: srcTime, ...options }),
  });
}

export function splitClipAtPoints(
  sequence: SequenceRef,
  clipId: string,
  srcTimes: number[],
  options: LinkOption = {},
): Promise<Sequence> {
  return edit(sequence, `/clips/${clipId}/split-points`, {
    method: "POST",
    body: JSON.stringify({ src_times: srcTimes, ...options }),
  });
}

export function splitClipAtPointsBatch(
  sequence: SequenceRef,
  splits: Array<{ clip_id: string; src_times: number[] }>,
  options: LinkOption = {},
): Promise<Sequence> {
  return edit(sequence, "/clips/split-points", { method: "POST", body: JSON.stringify({ splits, ...options }) });
}

/** 轨道头上的几个开关。静音只管声音,隐藏只管字幕显示(只有字幕轨收 hidden、字幕轨不收 muted)。 */
export type TrackStatePatch = { muted?: boolean; hidden?: boolean; locked?: boolean; solo?: boolean; duck?: boolean };

export function setTrackState(sequence: SequenceRef, trackId: string, body: TrackStatePatch): Promise<Sequence> {
  return edit(sequence, `/tracks/${trackId}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function addTrack(sequence: SequenceRef, kind: "video" | "audio" | "subtitle"): Promise<Sequence> {
  return edit(sequence, "/tracks", { method: "POST", body: JSON.stringify({ kind }) });
}

export function moveTrack(sequence: SequenceRef, trackId: string, direction: "up" | "down"): Promise<Sequence> {
  return edit(sequence, `/tracks/${trackId}/move`, { method: "PATCH", body: JSON.stringify({ direction }) });
}

export function generateSubtitles(
  sequence: SequenceRef,
  trackId: string,
  cues: Array<{ text: string; timeline_start: number; duration: number }>,
  /** 先清掉这条轨上原有的字幕(「重新生成」),和铺新的一起是撤销栈上的一步。 */
  replace = false,
): Promise<Sequence> {
  return edit(sequence, "/subtitles/generate", { method: "POST", body: JSON.stringify({ track_id: trackId, cues, replace }) });
}

/** 片段换成另一份素材(位置、时长、属性都不动)。给 fromAssetId = 这条时间线上用着那份素材的全部片段。 */
export function replaceClipMedia(
  sequence: SequenceRef,
  body: { asset_id: string; clip_ids?: string[]; from_asset_id?: string },
): Promise<Sequence> {
  return edit(sequence, "/clips/replace-media", { method: "POST", body: JSON.stringify(body) });
}

export type ClipAudioAction = "denoise" | "isolate_voice" | "separate";

/** 对片段做声音处理(降噪 / 只留人声 / 拆成人声和背景音),做完直接换到时间线上。排成任务。 */
export async function processClipAudio(sequence: SequenceRef, clipId: string, action: ClipAudioAction): Promise<Job> {
  // 排的是任务,但处理哪一段是照着这一版选的:带上 base_revision,那一段被别人改过就 409(见后端 _ensure_seen)。
  try {
    return await api<Job>(`/api/sequences/${sequence.id}/clips/${clipId}/audio?base_revision=${baseRevisionOf(sequence)}`, {
      method: "POST",
      body: JSON.stringify({ action }),
    });
  } catch (error) {
    noticeConflict(error);
    throw error;
  }
}

export type SubtitleFileFormat = "srt" | "vtt";
export type SubtitleImportResult = components["schemas"]["SubtitleImportOut"];

/** 一条字幕轨导出成 .srt / .vtt。双语字幕(两行)用 `line` 选全写、只写原文或只写译文。 */
export function exportSubtitleFile(
  sequenceId: string,
  trackId: string,
  format: SubtitleFileFormat,
  line: "all" | "first" | "last" = "all",
): Promise<Blob> {
  const query = new URLSearchParams({ track_id: trackId, format, line });
  return apiBlob(`/api/sequences/${sequenceId}/subtitles/export?${query.toString()}`);
}

/**
 * 读一份 .srt / .vtt 落到字幕轨上(不给轨道就新建一条)。整次导入是撤销栈上的一步。
 * 和别的编辑一样照着 `sequence` 那一版做(base_revision);回包里带着改完的序列,冲突时同样把最新的一版交出去。
 */
export async function importSubtitleFile(
  sequence: SequenceRef,
  file: File,
  options: { trackId?: string; offset?: number; replace?: boolean } = {},
): Promise<SubtitleImportResult> {
  const form = new FormData();
  form.append("file", file);
  form.append("track_id", options.trackId ?? "");
  form.append("offset", String(options.offset ?? 0));
  form.append("replace", String(Boolean(options.replace)));
  try {
    const result = await api<SubtitleImportResult>(
      `/api/sequences/${sequence.id}/subtitles/import?base_revision=${baseRevisionOf(sequence)}`,
      { method: "POST", body: form },
    );
    remember(result.sequence);
    return result;
  } catch (error) {
    noticeConflict(error);
    throw error;
  }
}

/** 这个文件是不是字幕文件(按扩展名):素材库收到它时转去导入字幕,而不是当成一份素材上传。 */
export function isSubtitleFile(file: File): boolean {
  return /\.(srt|vtt)$/i.test(file.name);
}

export function setSubtitleStyle(sequence: SequenceRef, style: Record<string, unknown>): Promise<Sequence> {
  return edit(sequence, "/subtitle-style", { method: "PUT", body: JSON.stringify({ style }) });
}

/** Backend safety limit for one translation request; the client exposes an unbounded operation. */
const TRANSLATE_BATCH = 400;

export async function translateTexts(
  workspaceId: string,
  texts: string[],
  targetLang: string,
  /** 翻译提供方 id(`builtin:google`、`builtin:chat`、插件连接 id);空 = 按这个人的默认(ADR 0032)。 */
  engine = "",
  /** Awaited after every batch so callers can persist incremental progress atomically. */
  onBatch?: (translations: string[], offset: number) => void | Promise<void>,
): Promise<{ translations: string[] }> {
  const translations: string[] = [];
  for (let start = 0; start < texts.length; start += TRANSLATE_BATCH) {
    const batch = texts.slice(start, start + TRANSLATE_BATCH);
    // Sequential batches avoid multiplying pressure on an upstream provider; the backend
    // already parallelizes work inside each batch.
    const result = await api<{ translations: string[] }>("/api/translate", {
      method: "POST",
      body: JSON.stringify({ workspace_id: workspaceId, texts: batch, target_lang: targetLang, engine }),
    });
    translations.push(...result.translations);
    await onBatch?.(result.translations, start);
  }
  return { translations };
}

export function insertTextClip(
  sequence: SequenceRef,
  body: { track_id: string; text: string; timeline_start: number; duration: number },
): Promise<Sequence> {
  return edit(sequence, "/text-clips", { method: "POST", body: JSON.stringify(body) });
}

export function setClipText(sequence: SequenceRef, clipId: string, text: string): Promise<Sequence> {
  return edit(sequence, `/clips/${clipId}/text`, { method: "PATCH", body: JSON.stringify({ text }) });
}

/** Retext many clips in one revision and one undo step. */
export function setClipTexts(sequence: SequenceRef, texts: { clip_id: string; text: string }[]): Promise<Sequence> {
  return edit(sequence, "/clips/texts", { method: "PATCH", body: JSON.stringify({ texts }) });
}

/** Removing a populated track is destructive and therefore requires an explicit flag. */
export function removeTrack(sequence: SequenceRef, trackId: string, withClips = false): Promise<Sequence> {
  const suffix = withClips ? "?with_clips=true" : "";
  return edit(sequence, `/tracks/${trackId}${suffix}`, { method: "DELETE" });
}

export function setClipEffects(
  sequence: SequenceRef,
  clipId: string,
  effects: Record<string, unknown>,
): Promise<Sequence> {
  return edit(sequence, `/clips/${clipId}/effects`, { method: "PATCH", body: JSON.stringify({ effects }) });
}

/**
 * 撤销 / 重做的两个选项。
 *
 * - `expectedRevision`:调用方看到的是第几版。只给它时撤**整条时间线上最新的一步**,时间线已经被改过就 409、
 *   不撤别人的那一步(画板上的撤销)。
 * - `mine`:撤**自己**最近的一步(剪辑页的 ⌘Z)。其间别人的改动和它冲突才 409(说清是谁),不冲突的话版本落后也照撤。
 *
 * 409 附带的最新序列照编辑一样送给 onSequenceConflict。
 */
export type HistoryOptions = { expectedRevision?: number; mine?: boolean };

function historyQuery({ expectedRevision, mine }: HistoryOptions): string {
  const params = new URLSearchParams();
  if (expectedRevision !== undefined) params.set("expected_revision", String(expectedRevision));
  if (mine) params.set("mine", "true");
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function undoSequence(sequenceId: string, options: HistoryOptions = {}): Promise<Sequence> {
  return send(sequenceId, `/undo${historyQuery(options)}`, { method: "POST" });
}

export function redoSequence(sequenceId: string, options: HistoryOptions = {}): Promise<Sequence> {
  return send(sequenceId, `/redo${historyQuery(options)}`, { method: "POST" });
}

export type ExportParams = components["schemas"]["ExportRequest"];

export function exportSequence(sequenceId: string, params?: ExportParams): Promise<Job> {
  return api<Job>(`/api/sequences/${sequenceId}/export`, {
    method: "POST",
    ...(params ? { body: JSON.stringify(params) } : {}),
  });
}

export type Lut = components["schemas"]["LutOut"];

export function listLuts(workspaceId: string): Promise<Lut[]> {
  return api<Lut[]>(`/api/luts?workspace_id=${workspaceId}`);
}

export async function uploadLut(params: { workspaceId: string; file: File; name?: string }): Promise<Lut> {
  const form = new FormData();
  form.set("workspace_id", params.workspaceId);
  if (params.name) form.set("name", params.name);
  form.set("file", params.file);
  return api<Lut>("/api/luts", { method: "POST", body: form });
}

export function deleteLut(lutId: string): Promise<void> {
  return api<void>(`/api/luts/${lutId}`, { method: "DELETE" });
}

export type Font = components["schemas"]["FontOut"];

export function listFonts(workspaceId: string): Promise<Font[]> {
  return api<Font[]>(`/api/fonts?workspace_id=${workspaceId}`);
}

export async function uploadFont(params: { workspaceId: string; file: File }): Promise<Font> {
  const form = new FormData();
  form.set("workspace_id", params.workspaceId);
  form.set("file", params.file);
  return api<Font>("/api/fonts", { method: "POST", body: form });
}

export function deleteFont(fontId: string): Promise<void> {
  return api<void>(`/api/fonts/${fontId}`, { method: "DELETE" });
}

export function fontFileUrl(fontId: string): string {
  const token = getAuthToken();
  const suffix = token ? `?token=${token}` : "";
  return `${API_BASE}/api/fonts/${fontId}/file${suffix}`;
}
