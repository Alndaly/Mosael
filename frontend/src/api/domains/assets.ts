import type { components, operations } from "@/api/generated/schema";
import type { Job } from "@/api/domains/jobs";
import type { Transcript } from "@/api/domains/speech";
import { API_BASE, ApiError, api, apiStream, apiUpload, getAuthToken } from "@/api/transport";

export type Asset = components["schemas"]["AssetOut"];

/** 一项出处:从哪份素材、经过什么操作(op 的取值见后端 domain/assets/lineage.OPS)。 */

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

/**
 * 原文件的字节流(带登录态,走 Authorization 头而不是 `?token=`)。给「保存到本地」用:**不落内存** ——
 * 调用方边收边往外交(桌面壳交给主进程写到用户选的那个位置,见 lib/download)。原文件可以有 2 GiB,
 * 所以这里回的是流而不是 Blob。
 */
export function openAssetFile(assetId: string): Promise<ReadableStream<Uint8Array>> {
  return apiStream(`/api/assets/${assetId}/file`);
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

/** 「生成蒙版」那一次要给的五个参数(生成的类型,见 api/generated/schema 的 MaskAssetRequest)。 */
export type MaskAssetRequest = components["schemas"]["MaskAssetRequest"];

/**
 * 按亮度 / alpha 从这张图算一张蒙版,存成一份**新**素材;原素材不动(ADR 0056 决定 6)。
 *
 * 形状四步的先后(**阈值 → 反选 → 扩张/收缩 → 羽化**)由后端定死,不交给调用方 —— 同一组参数在两个入口上
 * 得到同一张图。这条路是「对素材库里已有的一张图,一步得到一张存下来的蒙版」;在画布上画走 MaskEditor
 * (存的时候走 `savePaintedMask`,和这里交给后端同一个写出口,ADR 0057)。
 *
 * 产出的名字由后端定(「蒙版 · <原图名>」),`project_id` 留空就跟着原素材。
 */
export function makeAssetMask(assetId: string, body: MaskAssetRequest): Promise<Asset> {
  return api<Asset>(`/api/assets/${assetId}/mask`, { method: "POST", body: JSON.stringify(body) });
}

/**
 * 编辑器里**画出来的**蒙版存成一份素材(ADR 0057 决定 2)。和 `makeAssetMask` 交给后端的是同一个写出口。
 *
 * 浏览器只管画:交上去的那张图由后端归一成蒙版唯一的形状(读红通道、透明当黑、缩放到源图尺寸、`L` 模式 PNG),
 * 名字(「蒙版 · <源图名>」/「蒙版 · 空白」)和出处也由后端记。`sourceAssetId` 是**在哪张图上画的**:给了,产出就和
 * 它一样大、记它为出处;不给就是一张空白蒙版。
 */
export function savePaintedMask(params: {
  workspaceId: string;
  sourceAssetId?: string;
  projectId?: string;
  file: Blob;
  signal?: AbortSignal;
}): Promise<Asset> {
  const form = new FormData();
  form.set("workspace_id", params.workspaceId);
  if (params.sourceAssetId) form.set("source_asset_id", params.sourceAssetId);
  if (params.projectId) form.set("project_id", params.projectId);
  form.set("file", params.file, "mask.png");
  return apiUpload<Asset>("/api/assets/masks", form, { signal: params.signal });
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

/** 清除元数据任务的那一种(后端 `domain/assets/scrub/task.JOB_KIND`)。按它列任务就能查「这份素材还在清吗」。 */
export const SCRUB_JOB_KIND = "scrub_metadata";

/**
 * 清除元数据(ADR 0062)。默认那一趟只动**你自己的隐私**(地点、设备、账号、封面、数据轨,以及
 * `ffprobe` 看不见的 SEI / AAC 帧内 / `compressorname` 那三层);`provenance` 是**单独一个开关、默认关**。
 *
 * 产出是一份**新的**派生素材:画面和声音逐字节等于原片,原素材一个字节不动。排成任务(`JobOut`,
 * 进度 / 取消在任务中心),任务结果里有新素材 id、整套对账文本、十道门、清掉的计数。
 */
export function startScrub(assetId: string, provenance = false): Promise<Job> {
  return api<Job>(`/api/assets/${encodeURIComponent(assetId)}/scrub`, {
    method: "POST",
    body: JSON.stringify({ provenance }),
  });
}

/**
 * 这份素材上一次清除元数据的对账文本。**没清过是 200 + `status: "none"`**,不是 404 ——
 * 「还没清过」是一次正常的回答(和镜头表同一个态度)。
 *
 * `asset_id` 是**这份素材**:新产出那份干净素材自己那份对账就落在它的文件名上(后端把报告写在源文件
 * 旁边);从源素材(原片)上读也一样读得到最近一次留下的那份。交付方按「干净素材 → 源素材」的顺序问
 * 一次就够(见 `features/media/ScrubMetadata` 的 `useScrubReport`)。
 */
export function getScrubReport(assetId: string): Promise<ScrubReport> {
  return api<ScrubReport>(`/api/assets/${encodeURIComponent(assetId)}/scrub-report`);
}

/** 「清除元数据」的选项 —— 目前只有那一个开关(后端 `ScrubAssetRequest`)。 */
export type ScrubAssetRequest = components["schemas"]["ScrubAssetRequest"];

/** `GET /assets/{id}/scrub-report` 的回答。没清过时 `status` 是 `"none"`、`markdown` 是空串。 */
export type ScrubReport = components["schemas"]["ScrubReportOut"];

/**
 * 一次清除的**结果**(任务 `result` 里那一份):新素材 id、源素材 id、整套对账 Markdown、十道门逐条、
 * 门禁是否全过、清掉了什么(计数)、这一次有没有开 provenance,以及没做到的那几条。
 *
 * 后端发的是裸 dict(`domain/assets/scrub/task.removed_counts`),这里是**唯一**把它读成类型的地方。
 */
export interface ScrubOutcome {
  /** 新的干净素材。 */
  asset_id: string;
  /** 被清的那一份(一个字节没动)。 */
  source_asset_id: string;
  /** 整套对账 Markdown([`getScrubReport`] 读的就是同一份)。 */
  report: string;
  gates: ScrubGate[];
  gates_ok: boolean;
  removed: ScrubRemoved;
  provenance: boolean;
  warnings?: string[];
}

/** 十道门里的一道(后端 `domain/assets/scrub/gates.Gate`)。`name` 是后端给的一句中文说明。 */
export interface ScrubGate {
  id: string;
  name: string;
  ok: boolean;
  detail?: string;
  evidence?: Record<string, unknown>;
}

/** 清掉了什么的计数(后端 `removed_counts`);认不得的键不动,`0` 是「没有」不是「没查」。 */
export type ScrubRemoved = Record<string, number | undefined>;

/** 任务结果里那一份「清除元数据」的结果;不是这个形状(别的任务、老数据)时回 null。 */
export function scrubOutcomeOf(result: unknown): ScrubOutcome | null {
  const value = result as Record<string, unknown> | null | undefined;
  if (!value || typeof value !== "object") return null;
  if (typeof value.asset_id !== "string" || !value.asset_id) return null;
  if (!Array.isArray(value.gates)) return null;
  return {
    asset_id: value.asset_id,
    source_asset_id: typeof value.source_asset_id === "string" ? value.source_asset_id : "",
    report: typeof value.report === "string" ? value.report : "",
    gates: value.gates.filter((one): one is ScrubGate => {
      const gate = one as Record<string, unknown> | null;
      return gate !== null && typeof gate === "object" && typeof gate.id === "string";
    }),
    gates_ok: value.gates_ok !== false,
    removed: (value.removed && typeof value.removed === "object" ? value.removed : {}) as ScrubRemoved,
    provenance: value.provenance === true,
    ...(Array.isArray(value.warnings)
      ? { warnings: value.warnings.filter((one): one is string => typeof one === "string") }
      : {}),
  };
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
