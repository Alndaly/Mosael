import type { components, operations } from "@/api/generated/schema";
import type { Job } from "@/api/domains/jobs";
import type { Transcript } from "@/api/domains/speech";
import { API_BASE, ApiError, api, apiUpload, getAuthToken } from "@/api/transport";

export type Asset = components["schemas"]["AssetOut"];

export function getAsset(assetId: string): Promise<Asset> {
  return api<Asset>(`/api/assets/${assetId}`);
}

export type AssetLineage = components["schemas"]["AssetLineageOut"];
export type AssetLineageNode = components["schemas"]["AssetLineageNode"];

/** 这份素材的来源链:从哪几份、经过什么操作做出来的,一级一级往上(出处被删了的 name 是 null)。 */
export function getAssetLineage(assetId: string): Promise<AssetLineage> {
  return api<AssetLineage>(`/api/assets/${assetId}/lineage`);
}

export type RemoteEntry = components["schemas"]["RemoteEntryOut"];

export type UrlProbe = components["schemas"]["UrlProbeResponse"];

export interface WaveformData {
  version: number;
  duration: number;
  peaks: number[];
}

function assetUrl(assetId: string, representation: "file" | "preview" | "thumbnail" | "filmstrip" | "proxy" | "audio-proxy") {
  const token = getAuthToken();
  const suffix = token ? `?token=${token}` : "";
  return `${API_BASE}/api/assets/${assetId}/${representation}${suffix}`;
}

/** Probe metadata without downloading the media stream. */
export function probeUrl(
  workspaceId: string,
  url: string,
  profileId?: string | null,
  start = 1,
): Promise<UrlProbe> {
  return api<UrlProbe>("/api/assets/probe-url", {
    method: "POST",
    body: JSON.stringify({ workspace_id: workspaceId, url, profile_id: profileId || null, start }),
  });
}

/** 这个地址有没有站点专门的解析器(B 站、抖音、YouTube……);只认地址,不出网。 */
export function urlSupport(workspaceId: string, url: string): Promise<{ supported: boolean; extractor: string }> {
  return api(`/api/assets/url-support?${new URLSearchParams({ workspace_id: workspaceId, url })}`);
}

/** Download selected remote entries into the asset library as one background job. */
export function importFromUrl(body: {
  workspace_id: string;
  project_id?: string | null;
  /** `page_url` / `page_title`:从内嵌浏览器的哪一页里找到的 —— 记进出处,直链下载时当 Referer 带上。 */
  items: { url: string; title: string; page_url?: string; page_title?: string }[];
  kind: "video" | "audio";
  max_height?: number;
  profile_id?: string | null;
}): Promise<Job> {
  return api<Job>("/api/assets/import-url", { method: "POST", body: JSON.stringify(body) });
}

/** Import a path visible to the bundled desktop backend. */
export function importLocalAsset(workspaceId: string, path: string, projectId?: string): Promise<Asset> {
  return api<Asset>("/api/assets/import-local", {
    method: "POST",
    body: JSON.stringify({ workspace_id: workspaceId, path, project_id: projectId ?? null }),
  });
}

/** Original asset bytes. Media elements carry auth in the query because they cannot add headers. */
export function assetFileUrl(assetId: string): string {
  return assetUrl(assetId, "file");
}

/** Browser-compatible full-size preview; HEIC originals are derived to JPEG on demand. */
export function assetPreviewUrl(assetId: string): string {
  return assetUrl(assetId, "preview");
}

export function assetThumbnailUrl(assetId: string): string {
  return assetUrl(assetId, "thumbnail");
}

/** Uniformly sampled frames used by the editor filmstrip. */
export function assetFilmstripUrl(assetId: string): string {
  return assetUrl(assetId, "filmstrip");
}

/** The 720p preview proxy decoded by the WebCodecs compositor. */
export function assetProxyUrl(assetId: string): string {
  return assetUrl(assetId, "proxy");
}

/** The AAC preview audio proxy the editor mixer reads by Range and decodes chunk by chunk. */
export function assetAudioProxyUrl(assetId: string): string {
  return assetUrl(assetId, "audio-proxy");
}

/** Save one video frame as a new asset without mutating the source. */
export function grabAssetFrame(assetId: string, at: number, projectId?: string | null): Promise<Asset> {
  return api<Asset>(`/api/assets/${assetId}/frame`, {
    method: "POST",
    body: JSON.stringify({ at, project_id: projectId ?? null }),
  });
}

/** Render the sequence playhead, including DOM overlays, into a new asset. */
export function grabSequenceFrame(sequenceId: string, at: number): Promise<Asset> {
  return api<Asset>(`/api/sequences/${sequenceId}/frame`, { method: "POST", body: JSON.stringify({ at }) });
}

export function fetchWaveform(assetId: string): Promise<WaveformData> {
  return api<WaveformData>(`/api/assets/${assetId}/waveform`);
}

/**
 * 素材库列表里的一张卡片:卡片和挑选清单要显示的那些字段,`media_info` 只是卡片读得到的几项(时长、
 * 尺寸、帧率、有没有缩略图;文档的格式、页数、大小)。**要完整字段就取详情**(`getAsset`)。
 */
export type AssetCard = components["schemas"]["AssetCardOut"];
export type AssetPage = components["schemas"]["AssetPageOut"];
export type AssetFacets = components["schemas"]["AssetFacetsOut"];

/**
 * 看哪些素材:就是 `GET /api/assets` 的查询参数(游标除外,它由翻页的那一层管)。筛选和排序都在服务端做
 * (见后端 domain/assets/listing)。`kind` / `tag` 可以给几个;给了 `project_id` 就是「这个项目里的 + 工作区级的」。
 */
export type AssetQuery = Omit<NonNullable<operations["list_assets_api_assets_get"]["parameters"]["query"]>, "cursor">;
export type AssetSort = NonNullable<AssetQuery["sort"]>;

function assetQueryParams(query: AssetQuery): URLSearchParams {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (Array.isArray(value)) for (const one of value) params.append(key, String(one));
    else if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  return params;
}

/** 素材库的一页;`cursor` 是上一页的 `next_cursor`,其余条件不变。 */
export function listAssetPage(query: AssetQuery, cursor?: string | null): Promise<AssetPage> {
  const params = assetQueryParams(query);
  if (cursor) params.set("cursor", cursor);
  return api<AssetPage>(`/api/assets?${params.toString()}`);
}

/**
 * 页签上的数字和标签筛选的候选:整个范围里每种各几份、每个标签挂在几份上(不看搜索)。`intermediate` 给了就是数
 * 那一种中间产物(逐句配音的一句……);另交回每种中间产物各几份。
 */
export function getAssetFacets(workspaceId: string, projectId?: string | null, intermediate?: string): Promise<AssetFacets> {
  const params = new URLSearchParams({ workspace_id: workspaceId });
  if (projectId) params.set("project_id", projectId);
  if (intermediate) params.set("intermediate", intermediate);
  return api<AssetFacets>(`/api/assets/facets?${params.toString()}`);
}

/** 这条时间线上用到的素材,完整字段 —— 剪辑台的时间线、监视器、检查器读它。 */
export function listSequenceAssets(sequenceId: string): Promise<Asset[]> {
  return api<Asset[]>(`/api/sequences/${sequenceId}/assets`);
}

export function renameAsset(assetId: string, name: string): Promise<Asset> {
  return api<Asset>(`/api/assets/${assetId}`, { method: "PATCH", body: JSON.stringify({ name }) });
}

export function setAssetTags(assetId: string, tags: string[]): Promise<Asset> {
  return api<Asset>(`/api/assets/${assetId}`, { method: "PATCH", body: JSON.stringify({ tags }) });
}

/** 重新生成这份素材的预览代理(上一次转坏了)。 */
export function regenerateAssetProxy(assetId: string): Promise<Job> {
  return api<Job>(`/api/assets/${encodeURIComponent(assetId)}/proxy`, { method: "POST" });
}

export function deleteAsset(assetId: string): Promise<unknown> {
  return api(`/api/assets/${assetId}`, { method: "DELETE" });
}

/** Empty language lets the engine detect it; empty engine follows the saved ASR preference. */
export function transcribeAsset(assetId: string, language = "", engine = ""): Promise<Job> {
  const params = new URLSearchParams();
  if (language) params.set("language", language);
  if (engine) params.set("engine", engine);
  const query = params.size > 0 ? `?${params.toString()}` : "";
  return api<Job>(`/api/assets/${assetId}/transcribe${query}`, { method: "POST" });
}

/** 拆成人声 + 背景音两份**新**素材;原素材不动(ADR-0016)。排成任务:长素材要跑十几分钟。 */
export function separateAssetAudio(assetId: string, engine = ""): Promise<Job> {
  const query = engine ? `?engine=${encodeURIComponent(engine)}` : "";
  return api<Job>(`/api/assets/${assetId}/separate${query}`, { method: "POST" });
}

export type DenoiseStrength = "light" | "medium" | "strong";
export type DenoiseEngine = components["schemas"]["DenoiseEngineOut"];

/** 降噪引擎,以及现在能不能用(ADR-0017)。 */
export function listDenoiseEngines(): Promise<DenoiseEngine[]> {
  return api<DenoiseEngine[]>("/api/denoise/engines");
}

/** 下载并装上一个要装的降噪引擎(DeepFilterNet)。后台跑,轮询引擎清单看进度。 */
export function installDenoiseEngine(engine: string): Promise<DenoiseEngine> {
  return api<DenoiseEngine>(`/api/denoise/engines/${encodeURIComponent(engine)}/install`, { method: "POST" });
}

/** 降噪,产出一份**新**素材(视频保留画面、只换声音);原素材不动。排成任务。 */
export function denoiseAsset(assetId: string, body: { engine?: string; strength?: DenoiseStrength } = {}): Promise<Job> {
  return api<Job>(`/api/assets/${assetId}/denoise`, { method: "POST", body: JSON.stringify(body) });
}

/** Create a new GIF asset without mutating the source video. */
export function convertVideoToGif(
  assetId: string,
  options: { fps?: number; width?: number; start?: number; duration?: number | null } = {},
): Promise<Job> {
  return api<Job>(`/api/assets/${assetId}/convert-gif`, {
    method: "POST",
    body: JSON.stringify(options),
  });
}

export async function importAsset(params: {
  workspaceId: string;
  /** Omit projectId for a workspace-level asset; editor imports attach to a project. */
  projectId?: string;
  file: File;
  name?: string;
  /** 给了就说传了多少(0..1)—— 挑素材弹窗、生成面板的槽位上传一段大视频时看得见进度。 */
  onProgress?: (fraction: number) => void;
  /** 给了就停得下来(取消上传)。 */
  signal?: AbortSignal;
}): Promise<Asset> {
  const form = new FormData();
  form.set("workspace_id", params.workspaceId);
  if (params.projectId) form.set("project_id", params.projectId);
  if (params.name) form.set("name", params.name);
  form.set("file", params.file);
  if (params.onProgress || params.signal) {
    return apiUpload<Asset>("/api/assets/import", form, { signal: params.signal, onProgress: params.onProgress });
  }
  return api<Asset>("/api/assets/import", { method: "POST", body: form });
}

/** 网页素材怎么来的:截图三种,或页面上的一张图(见后端 domain/assets/web_capture)。 */
export type WebCaptureKind = "screenshot_visible" | "screenshot_full" | "screenshot_region" | "page_image";

/** 内嵌浏览器里截的图 / 采的页面图片入库,带着出处(来源网址、页面标题、截取时间)。 */
export function importWebCapture(params: {
  workspaceId: string;
  file: Blob;
  capture: WebCaptureKind;
  pageUrl: string;
  pageTitle: string;
  capturedAt: string;
  name: string;
  /** 页面图片自己的地址;截图不给。 */
  sourceUrl?: string;
}): Promise<Asset> {
  const form = new FormData();
  form.set("workspace_id", params.workspaceId);
  form.set("capture", params.capture);
  form.set("page_url", params.pageUrl);
  form.set("page_title", params.pageTitle);
  form.set("captured_at", params.capturedAt);
  form.set("name", params.name);
  if (params.sourceUrl) form.set("source_url", params.sourceUrl);
  // 文件名由服务端定,这里给的只是表单要求的那一格。
  form.set("file", params.file, "capture");
  return api<Asset>("/api/assets/capture", { method: "POST", body: form });
}

/** 这段素材的转写;**还没转写过回 null**(后端答 404),别的失败照常抛。 */
export async function getAssetTranscript(assetId: string): Promise<Transcript | null> {
  try {
    return await api<Transcript>(`/api/assets/${assetId}/transcript`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}
