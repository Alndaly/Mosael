import type { components } from "@/api/generated/schema";

// 服务器可切换(团队模式铺垫):默认本机后端,localStorage 记住自定义地址。
// 切换后整页 reload,让所有模块用新地址重新初始化;换服务器后原 token 失效
// 会命中 401 → 自动回到登录页。
const SERVER_KEY = "openstudio.server.url";
export const DEFAULT_API_BASE = "http://127.0.0.1:8800";
export const API_BASE = (
  typeof window === "undefined" ? DEFAULT_API_BASE : window.localStorage.getItem(SERVER_KEY) || DEFAULT_API_BASE
).replace(/\/+$/, "");

export function setServerUrl(url: string | null): void {
  if (url && url.replace(/\/+$/, "") !== DEFAULT_API_BASE) {
    window.localStorage.setItem(SERVER_KEY, url.replace(/\/+$/, ""));
  } else {
    window.localStorage.removeItem(SERVER_KEY);
  }
}

export function isCustomServer(): boolean {
  return API_BASE !== DEFAULT_API_BASE;
}

const TOKEN_KEY = "openstudio.auth.token";
let authToken: string | null = typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY);
let onUnauthorized: (() => void) | null = null;

export function setAuthToken(token: string | null): void {
  authToken = token;
  if (typeof window !== "undefined") {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  }
}

export function getAuthToken(): string | null {
  return authToken;
}

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

export type User = components["schemas"]["UserOut"] & {
  display_name: string;
  signature: string;
};
export type AuthOut = Omit<components["schemas"]["AuthOut"], "user"> & { user: User };

export function uploadAvatar(file: File): Promise<User> {
  const form = new FormData();
  form.set("file", file);
  return api<User>("/api/auth/me/avatar", { method: "POST", body: form });
}

/** 头像 URL:<img> 带不了请求头,与素材文件同款 ?token= 鉴权;avatar_key 作 ?v= 破缓存。 */
export function userAvatarUrl(userId: string, avatarKey: string | null | undefined): string {
  if (!avatarKey) return "";
  const suffix = authToken ? `&token=${authToken}` : "";
  return `${API_BASE}/api/auth/users/${userId}/avatar?v=${encodeURIComponent(avatarKey)}${suffix}`;
}

export function updateMe(body: { username: string; display_name: string; signature: string }): Promise<User> {
  return api<User>("/api/auth/me", { method: "PATCH", body: JSON.stringify(body) });
}

export function updatePassword(body: { current_password: string; new_password: string }): Promise<{ ok: boolean }> {
  return api<{ ok: boolean }>("/api/auth/me/password", { method: "POST", body: JSON.stringify(body) });
}

export type Workspace = components["schemas"]["WorkspaceOut"];
export type WorkspaceMember = components["schemas"]["WorkspaceMemberOut"] & { display_name: string };
export type MembersInfo = Omit<components["schemas"]["MembersOut"], "members"> & { members: WorkspaceMember[] };

export function listMembers(workspaceId: string): Promise<MembersInfo> {
  return api<MembersInfo>(`/api/workspaces/${workspaceId}/members`);
}
export type WorkspaceInvitation = components["schemas"]["InvitationOut"];

export function inviteMember(workspaceId: string, body: { username: string; role: string }): Promise<WorkspaceInvitation> {
  return api<WorkspaceInvitation>(`/api/workspaces/${workspaceId}/invitations`, { method: "POST", body: JSON.stringify(body) });
}

export function myInvitations(): Promise<{ invitations: WorkspaceInvitation[] }> {
  return api<{ invitations: WorkspaceInvitation[] }>("/api/invitations");
}

export function respondInvitation(invitationId: string, accept: boolean): Promise<WorkspaceInvitation> {
  return api<WorkspaceInvitation>(`/api/invitations/${invitationId}/${accept ? "accept" : "decline"}`, { method: "POST" });
}
export function setMemberRole(workspaceId: string, userId: string, role: string): Promise<WorkspaceMember> {
  return api<WorkspaceMember>(`/api/workspaces/${workspaceId}/members/${userId}`, { method: "PATCH", body: JSON.stringify({ role }) });
}
export function removeMember(workspaceId: string, userId: string): Promise<void> {
  return api<void>(`/api/workspaces/${workspaceId}/members/${userId}`, { method: "DELETE" });
}
/** 第三方登录:start 拿授权 URL(系统浏览器打开)+ pending_id,随后轮询取票。 */
export function oauthProviders(): Promise<{ providers: string[] }> {
  return api<{ providers: string[] }>("/api/auth/oauth/providers");
}
export function oauthStart(provider: string): Promise<{ pending_id: string; url: string }> {
  return api<{ pending_id: string; url: string }>(`/api/auth/oauth/${provider}/start`, { method: "POST" });
}
export function oauthPending(
  pendingId: string,
): Promise<{ status: string; token?: string; user?: User; error?: string }> {
  return api(`/api/auth/oauth/pending/${pendingId}`);
}

export function createWorkspace(name: string): Promise<Workspace> {
  return api<Workspace>("/api/workspaces", { method: "POST", body: JSON.stringify({ name }) });
}
export function renameWorkspace(workspaceId: string, name: string): Promise<{ id: string; name: string }> {
  return api(`/api/workspaces/${workspaceId}`, { method: "PATCH", body: JSON.stringify({ name }) });
}
export function deleteWorkspace(workspaceId: string): Promise<void> {
  return api<void>(`/api/workspaces/${workspaceId}`, { method: "DELETE" });
}

export type Project = components["schemas"]["ProjectOut"];
export type ProjectWithStats = components["schemas"]["ProjectWithStatsOut"];
export type Asset = components["schemas"]["AssetOut"];
export type Sequence = components["schemas"]["SequenceOut"];
export type Track = components["schemas"]["TrackOut"];
export type Clip = components["schemas"]["ClipOut"];
export type Job = components["schemas"]["JobOut"];
export type TaskEvent = components["schemas"]["TaskEventOut"];

export function getJob(jobId: string): Promise<Job> {
  return api<Job>(`/api/jobs/${jobId}`);
}

export function listJobEvents(jobId: string): Promise<TaskEvent[]> {
  return api<TaskEvent[]>(`/api/jobs/${jobId}/events`);
}

/** 工作流 job 派生的子任务(发布/导出/转写/生成/配音),在任务详情里「收纳」展示。 */
export function listJobChildren(jobId: string): Promise<Job[]> {
  return api<Job[]>(`/api/jobs/${jobId}/children`);
}

export type AsrModel = components["schemas"]["AsrModelOut"];
export function listAsrModels(): Promise<AsrModel[]> {
  return api<AsrModel[]>("/api/asr/models");
}
export function downloadAsrModel(id: string): Promise<AsrModel> {
  return api<AsrModel>(`/api/asr/models/${encodeURIComponent(id)}/download`, { method: "POST" });
}

export type Voice = components["schemas"]["VoiceOut"];
export type Transcript = components["schemas"]["TranscriptOut"];
export type TtsEngine = components["schemas"]["TtsEngineOut"];
export function listVoices(workspaceId: string): Promise<Voice[]> {
  return api<Voice[]>(`/api/voices?workspace_id=${workspaceId}`);
}
export function uploadVoice(args: { workspaceId: string; name: string; referenceText: string; file: File }): Promise<Voice> {
  const form = new FormData();
  form.append("workspace_id", args.workspaceId);
  form.append("name", args.name);
  form.append("reference_text", args.referenceText);
  form.append("file", args.file);
  return api<Voice>("/api/voices/upload", { method: "POST", body: form });
}
export function deleteVoice(id: string): Promise<void> {
  return api<void>(`/api/voices/${id}`, { method: "DELETE" });
}
export function voiceFromSpeaker(body: { asset_id: string; speaker?: string | null; name?: string }): Promise<Voice> {
  return api<Voice>("/api/voices/from-speaker", { method: "POST", body: JSON.stringify(body) });
}
export function synthesizeVoice(id: string, body: { text: string; project_id?: string | null }): Promise<Job> {
  return api<Job>(`/api/voices/${id}/synthesize`, { method: "POST", body: JSON.stringify(body) });
}
/** An engine the 配音 panel can offer. Distinct from TtsEngine, which is a downloadable LOCAL
    model — same word, two meanings, and naming both TtsEngine shadows one of them. */
export interface TtsEngineChoice {
  id: string;
  label: string;
  needs_key: boolean;
  /** True when the engine's catalogue is too large or account-specific to enumerate, so the
      voice is typed in rather than picked. */
  needs_voice_id: boolean;
  voices: string[];
  note: string;
}

export interface TtsVoice {
  value: string;
  label: string;
  /** 火山 only: the voice's resource family, which synthesis must echo in a header. */
  resource_id: string;
}

/** The voices an engine can speak in. Separate from the engine list because for 火山 this is a
    live, account-dependent lookup — the engine list is static. */
export function listTtsVoices(engine: string): Promise<TtsVoice[]> {
  return api<TtsVoice[]>(`/api/tts/voices?engine=${encodeURIComponent(engine)}`);
}

/** 火山 podcast: one call produces a whole two-voice dialogue, so it has its own endpoint
    rather than being a voice on the synthesis one. */
export function generatePodcast(body: {
  workspace_id: string;
  project_id?: string | null;
  text?: string;
  topic?: string;
  mode: "summarize" | "read" | "research";
  speakers: string[];
  speed?: number;
}): Promise<Job> {
  return api<Job>("/api/tts/podcast", { method: "POST", body: JSON.stringify(body) });
}

export function listTtsEngines(): Promise<TtsEngineChoice[]> {
  return api<TtsEngineChoice[]>("/api/tts/engines");
}

/** Synthesis through a remote engine. Separate from synthesizeVoice because there is no Voice
    row — the engine supplies the voice, so the request carries a workspace instead. */
export function synthesizeWithEngine(body: {
  workspace_id: string;
  text: string;
  engine: string;
  engine_voice?: string;
  engine_voice_resource?: string;
  speed?: number;
  project_id?: string | null;
}): Promise<Job> {
  return api<Job>("/api/tts/synthesize", { method: "POST", body: JSON.stringify(body) });
}

export function voiceSampleUrl(id: string): string {
  const suffix = authToken ? `?token=${authToken}` : "";
  return `${API_BASE}/api/voices/${id}/sample${suffix}`;
}
export function listTtsModels(): Promise<TtsEngine[]> {
  return api<TtsEngine[]>("/api/tts/models");
}
export function downloadTtsModel(id: string): Promise<TtsEngine> {
  return api<TtsEngine>(`/api/tts/models/${encodeURIComponent(id)}/download`, { method: "POST" });
}
export type TtsConfig = components["schemas"]["TtsConfigOut"];
export function getTtsConfig(): Promise<TtsConfig> {
  return api<TtsConfig>("/api/settings/tts");
}
export function updateTtsConfig(body: {
  engine: string;
  python_path: string;
  source: string;
  fish_repo_dir?: string;
  fish_model_dir?: string;
}): Promise<TtsConfig> {
  return api<TtsConfig>("/api/settings/tts", { method: "PUT", body: JSON.stringify(body) });
}
/** 一个「用哪条连接的哪个模型来生成」的选项。后端联接好的那份 —— 见 /generation/options。 */
export type GenerationOption = components["schemas"]["GenerationOptionOut"];
/** 兼容别名:参数描述符的读取函数(lib/generationCapabilities)对两者一视同仁。 */
export type GenerationModel = GenerationOption;
export type GenerationJob = components["schemas"]["GenerationJobOut"];
export type GenerationCreateResponse = components["schemas"]["GenerationCreateResponse"];
export type ScheduledTask = components["schemas"]["ScheduledTaskOut"];
export type ScheduledTaskRun = components["schemas"]["ScheduledTaskRunOut"];
export type RunScheduledTaskResponse = components["schemas"]["RunScheduledTaskResponse"];
export type PluginPackage = components["schemas"]["PluginPackageOut"];
export type PluginInstance = components["schemas"]["PluginInstanceOut"];
export type PluginField = components["schemas"]["PluginFieldOut"];
export type PluginToolState = components["schemas"]["PluginToolStateOut"];
export type Workflow = components["schemas"]["WorkflowOut"];
export type PublishPlatform = components["schemas"]["PublishPlatformOut"];
export type PublishAccount = components["schemas"]["PublishAccountOut"];
export type PublishTask = components["schemas"]["PublishTaskOut"];
export type PublishCopy = components["schemas"]["PublishCopyResponse"];
export type WorkflowNodeType = components["schemas"]["WorkflowNodeTypeOut"];
export type PluginTool = components["schemas"]["PluginToolOut"];
export type PluginInvocation = components["schemas"]["PluginInvocationOut"];
export type PluginPermissionGrant = components["schemas"]["PluginPermissionGrantOut"];
export type PluginCredential = components["schemas"]["PluginCredentialOut"];

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  // 客户端自报版本。后端知道的是**它自己**那个进程的版本 —— 分布式部署里每个人跑的壳可以
  // 各不相同,而"某人还停在旧版"正是管理员要看的:它解释了为什么只有他撞得到那个早修好的 bug。
  const auth: Record<string, string> = {
    "X-Open-Studio-Client": __APP_VERSION__,
    ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
  };
  const headers =
    init?.body instanceof FormData
      ? { ...auth, ...(init?.headers as Record<string, string> | undefined) }
      : { "Content-Type": "application/json", ...auth, ...(init?.headers as Record<string, string> | undefined) };
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (res.status === 401 && !path.startsWith("/api/auth/")) {
    onUnauthorized?.();
    throw new Error("Not authenticated");
  }
  if (!res.ok) {
    const body = await res.text();
    // 开发者可在控制台追溯失败的后端调用;抛出的错误照常驱动界面 toast 给用户。
    const method = (init?.method ?? "GET").toUpperCase();
    console.warn(`[api] ${method} ${path} → ${res.status} ${res.statusText}${body ? `: ${body}` : ""}`);
    throw new Error(`${res.status} ${res.statusText}${body ? `: ${body}` : ""}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

/** 桌面端把文件拖到应用图标上 / 「用 Open Studio 打开」:后端按本机绝对路径入库。
 *  只有桌面端自带的后端提供这个接口(团队服务器上 404)。 */
/** 供应商端点上的一个可用模型。context_window / max_output_tokens 端点没给就是 null —— 不要
 *  用默认值填补,那正是智能体侧硬编 128000 的来源。 */
export interface ProviderModel {
  id: string;
  context_window: number | null;
  max_output_tokens: number | null;
}

export async function listProviderModels(profileId: string): Promise<ProviderModel[]> {
  return api<ProviderModel[]>(`/api/settings/providers/${profileId}/models`);
}

export async function importLocalAsset(workspaceId: string, path: string, projectId?: string): Promise<Asset> {
  return api<Asset>("/api/assets/import-local", {
    method: "POST",
    body: JSON.stringify({ workspace_id: workspaceId, path, project_id: projectId ?? null }),
  });
}

export function assetFileUrl(assetId: string): string {
  // Media elements cannot send headers, so these URLs carry the token.
  const suffix = authToken ? `?token=${authToken}` : "";
  return `${API_BASE}/api/assets/${assetId}/file${suffix}`;
}

export function assetThumbnailUrl(assetId: string): string {
  const suffix = authToken ? `?token=${authToken}` : "";
  return `${API_BASE}/api/assets/${assetId}/thumbnail${suffix}`;
}

/** The 720p preview proxy the WebCodecs compositor decodes (media_info.proxy_status === "ready"). */
export function assetProxyUrl(assetId: string): string {
  const suffix = authToken ? `?token=${authToken}` : "";
  return `${API_BASE}/api/assets/${assetId}/proxy${suffix}`;
}

export interface PromptOptimizeResult {
  prompt: string;
  negative_prompt: string;
  notes: string;
  platform: string;
}

/** 分平台图像提示词优化:按目标 provider/model 的平台习惯重写提示词。与智能助手技能共用同一后端。 */
export function optimizeImagePrompt(body: {
  workspace_id: string;
  provider: string;
  model: string;
  prompt: string;
  provider_profile_id?: string | null;
  language?: string;
}): Promise<PromptOptimizeResult> {
  return api<PromptOptimizeResult>("/api/generation/optimize-prompt", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export interface WaveformData {
  version: number;
  duration: number;
  peaks: number[];
}

export function fetchWaveform(assetId: string): Promise<WaveformData> {
  return api<WaveformData>(`/api/assets/${assetId}/waveform`);
}

export function insertClip(
  sequenceId: string,
  body: { track_id: string; asset_id: string; timeline_start: number; src_in: number; src_out: number; ripple?: boolean },
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips`, { method: "POST", body: JSON.stringify(body) });
}

export function moveClip(
  sequenceId: string,
  clipId: string,
  body: { timeline_start: number; track_id?: string | null; ripple?: boolean },
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/move`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

/** 多选批量删除:一条操作、一步撤销(逐个调 deleteClip 会变成 N 步撤销)。 */
export function deleteClipsBatch(sequenceId: string, clipIds: string[]): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/delete-batch`, {
    method: "POST",
    body: JSON.stringify({ clip_ids: clipIds }),
  });
}

/** 多选批量波纹删除:同轨后续左移补位,同样一条操作、一步撤销。 */
export function rippleDeleteClipsBatch(sequenceId: string, clipIds: string[]): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/ripple-delete-batch`, {
    method: "POST",
    body: JSON.stringify({ clip_ids: clipIds }),
  });
}

/** 框选整组拖动:一次请求、一条操作、一步撤销(逐个调 moveClip 会变成 N 步撤销)。 */
export function moveClipsBatch(
  sequenceId: string,
  moves: { clip_id: string; timeline_start: number; track_id?: string | null }[],
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/move-batch`, {
    method: "PATCH",
    body: JSON.stringify({ moves }),
  });
}

export function trimClip(
  sequenceId: string,
  clipId: string,
  body: { timeline_start: number; src_in: number; src_out: number },
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/trim`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function cutClipRange(
  sequenceId: string,
  clipId: string,
  body: { src_start: number; src_end: number },
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/cut-range`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function deleteClip(sequenceId: string, clipId: string): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}`, { method: "DELETE" });
}

export function cutClipRanges(
  sequenceId: string,
  clipId: string,
  ranges: Array<{ src_start: number; src_end: number }>,
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/cut-ranges`, {
    method: "POST",
    body: JSON.stringify({ ranges }),
  });
}

export function setClipSpeed(sequenceId: string, clipId: string, speed: number): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/speed`, {
    method: "PATCH",
    body: JSON.stringify({ speed }),
  });
}

export function setClipGain(sequenceId: string, clipId: string, gain: number, muted: boolean): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/gain`, {
    method: "PATCH",
    body: JSON.stringify({ gain, muted }),
  });
}

export function detachClipAudio(sequenceId: string, clipId: string): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/detach-audio`, { method: "POST" });
}

export function setClipTransform(
  sequenceId: string,
  clipId: string,
  // number scalars(scale/x/y/rotation/opacity)+ 可选 keyframes 数组;后端按字段读取校验。
  transform: Record<string, unknown>,
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/transform`, {
    method: "PATCH",
    body: JSON.stringify({ transform }),
  });
}

export function setSequenceReframe(
  sequenceId: string,
  reframe: { width: number; height: number; fill_mode: string },
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/reframe`, {
    method: "PATCH",
    body: JSON.stringify(reframe),
  });
}

export function rippleDeleteClip(sequenceId: string, clipId: string): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/ripple`, { method: "DELETE" });
}

export function splitClip(sequenceId: string, clipId: string, srcTime: number): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/split`, {
    method: "POST",
    body: JSON.stringify({ src_time: srcTime }),
  });
}

export function splitClipAtPoints(sequenceId: string, clipId: string, srcTimes: number[]): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/split-points`, {
    method: "POST",
    body: JSON.stringify({ src_times: srcTimes }),
  });
}

export function setTrackState(
  sequenceId: string,
  trackId: string,
  body: { muted?: boolean; locked?: boolean; solo?: boolean; duck?: boolean },
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/tracks/${trackId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function addTrack(sequenceId: string, kind: "video" | "audio" | "subtitle"): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/tracks`, { method: "POST", body: JSON.stringify({ kind }) });
}

export function moveTrack(sequenceId: string, trackId: string, direction: "up" | "down"): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/tracks/${trackId}/move`, {
    method: "PATCH",
    body: JSON.stringify({ direction }),
  });
}

export function generateSubtitles(
  sequenceId: string,
  trackId: string,
  cues: Array<{ text: string; timeline_start: number; duration: number }>,
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/subtitles/generate`, {
    method: "POST",
    body: JSON.stringify({ track_id: trackId, cues }),
  });
}

export function setSubtitleStyle(sequenceId: string, style: Record<string, unknown>): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/subtitle-style`, {
    method: "PUT",
    body: JSON.stringify({ style }),
  });
}

export function translateTexts(
  workspaceId: string,
  texts: string[],
  targetLang: string,
  engine: "google" | "ai" = "google",
): Promise<{ translations: string[] }> {
  return api<{ translations: string[] }>("/api/translate", {
    method: "POST",
    body: JSON.stringify({ workspace_id: workspaceId, texts, target_lang: targetLang, engine }),
  });
}

export function insertTextClip(
  sequenceId: string,
  body: { track_id: string; text: string; timeline_start: number; duration: number },
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/text-clips`, { method: "POST", body: JSON.stringify(body) });
}

export function setClipText(sequenceId: string, clipId: string, text: string): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/text`, {
    method: "PATCH",
    body: JSON.stringify({ text }),
  });
}

/** Retext many clips in ONE revision. Per-clip calls left a half-translated track behind on a
    mid-way failure, and made undoing a translation an N-step chore. */
export function setClipTexts(
  sequenceId: string,
  texts: { clip_id: string; text: string }[],
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/texts`, {
    method: "PATCH",
    body: JSON.stringify({ texts }),
  });
}

/** Removing a track that still holds clips destroys them, so the backend refuses unless
    withClips is set — the caller is expected to have asked the user first. */
export function removeTrack(sequenceId: string, trackId: string, withClips = false): Promise<Sequence> {
  const suffix = withClips ? "?with_clips=true" : "";
  return api<Sequence>(`/api/sequences/${sequenceId}/tracks/${trackId}${suffix}`, { method: "DELETE" });
}

export function setClipEffects(sequenceId: string, clipId: string, effects: Record<string, unknown>): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/${clipId}/effects`, {
    method: "PATCH",
    body: JSON.stringify({ effects }),
  });
}

export function undoSequence(sequenceId: string): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/undo`, { method: "POST" });
}

export function redoSequence(sequenceId: string): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/redo`, { method: "POST" });
}

export interface WorkflowGraph {
  nodes: Array<{
    id: string;
    type: string;
    name?: string;
    position?: { x: number; y: number };
    config?: Record<string, unknown>;
    /** 以输入接点(连接态)暴露在节点左侧的 config 字段名。 */
    inputs?: string[];
  }>;
  edges: Array<{
    id: string;
    source: string;
    target: string;
    source_handle?: string | null;
    /** 缺省 / "control" = 执行边;"data" = 数据边(带 source_output → target_input)。 */
    kind?: "control" | "data";
    source_output?: string;
    target_input?: string;
  }>;
}


export function listWorkflows(workspaceId: string): Promise<Workflow[]> {
  return api<Workflow[]>(`/api/workflows?workspace_id=${workspaceId}`);
}

export function createWorkflow(body: {
  workspace_id: string;
  name: string;
  description?: string;
  graph?: WorkflowGraph | null;
}): Promise<Workflow> {
  return api<Workflow>("/api/workflows", { method: "POST", body: JSON.stringify(body) });
}

export function updateWorkflow(
  workflowId: string,
  body: { name?: string; description?: string; graph?: WorkflowGraph },
): Promise<Workflow> {
  return api<Workflow>(`/api/workflows/${workflowId}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function deleteWorkflow(workflowId: string): Promise<unknown> {
  return api(`/api/workflows/${workflowId}`, { method: "DELETE" });
}

/** 导出文件信封:{format, version, name, description, graph}。 */
export function exportWorkflowFile(workflowId: string): Promise<Record<string, unknown>> {
  return api<Record<string, unknown>>(`/api/workflows/${workflowId}/export`);
}

export function importWorkflow(body: { workspace_id: string; data: Record<string, unknown> }): Promise<Workflow> {
  return api<Workflow>("/api/workflows/import", { method: "POST", body: JSON.stringify(body) });
}

export function runWorkflow(workflowId: string, params: Record<string, unknown> = {}): Promise<Job> {
  return api<Job>(`/api/workflows/${workflowId}/run`, { method: "POST", body: JSON.stringify({ params }) });
}

export function fetchWorkflowNodeTypes(): Promise<WorkflowNodeType[]> {
  return api<WorkflowNodeType[]>("/api/workflows/node-types");
}

/** Execution history — this workflow's run jobs, newest first. */
export function listWorkflowRuns(workflowId: string): Promise<Job[]> {
  return api<Job[]>(`/api/workflows/${workflowId}/runs`);
}

export interface AppNotification {
  id: string;
  workspace_id: string;
  type: string;
  title: string;
  body: string;
  link: string | null;
  payload: Record<string, unknown>;
  read_at: string | null;
  created_at: string;
}

export function listNotifications(workspaceId: string): Promise<{ items: AppNotification[]; unread: number }> {
  return api(`/api/notifications?workspace_id=${workspaceId}`);
}

export function readNotification(id: string): Promise<AppNotification> {
  return api(`/api/notifications/${id}/read`, { method: "POST" });
}

export function readAllNotifications(workspaceId: string): Promise<{ read: number }> {
  return api(`/api/notifications/read-all?workspace_id=${workspaceId}`, { method: "POST" });
}

export function listPublishPlatforms(): Promise<PublishPlatform[]> {
  return api<PublishPlatform[]>("/api/publish/platforms");
}

export function listPublishAccounts(workspaceId: string): Promise<PublishAccount[]> {
  return api<PublishAccount[]>(`/api/publish/accounts?workspace_id=${workspaceId}`);
}

export function createPublishAccount(body: {
  workspace_id: string;
  platform: string;
  name: string;
  config: Record<string, unknown>;
  proxy?: string | null;
}): Promise<PublishAccount> {
  return api<PublishAccount>("/api/publish/accounts", { method: "POST", body: JSON.stringify(body) });
}

export function deletePublishAccount(accountId: string): Promise<unknown> {
  return api(`/api/publish/accounts/${accountId}`, { method: "DELETE" });
}

export function patchPublishAccount(
  accountId: string,
  body: { name?: string; enabled?: boolean; proxy?: string | null },
): Promise<PublishAccount> {
  return api<PublishAccount>(`/api/publish/accounts/${accountId}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function recheckPublishAccount(accountId: string): Promise<PublishAccount> {
  return api<PublishAccount>(`/api/publish/accounts/${accountId}/recheck`, { method: "POST" });
}

// ---- 浏览器池:持久登录档案(发布账号 = 挂平台的档案;通用档案任意站点复用) ----

export type BrowserProfile = components["schemas"]["BrowserProfileOut"];

export function listBrowserProfiles(workspaceId: string): Promise<BrowserProfile[]> {
  return api<BrowserProfile[]>(`/api/browser/profiles?workspace_id=${workspaceId}`);
}

export function createBrowserProfile(body: {
  workspace_id: string;
  name: string;
  proxy?: string | null;
}): Promise<BrowserProfile> {
  return api<BrowserProfile>("/api/browser/profiles", { method: "POST", body: JSON.stringify(body) });
}

/** 把「我的东西」放进一个工作区,或者收回来。发布账号与它的浏览器档案会一起动(后端保证)。 */
export function setResourceShared(
  kind: "publish_account" | "browser_profile" | "agent_session" | "generation_session" | "scheduled_task",
  resourceId: string,
  workspaceId: string,
  shared: boolean,
): Promise<{ workspaces: string[] }> {
  return api(`/api/shares/${kind}/${resourceId}`, {
    method: shared ? "POST" : "DELETE",
    body: JSON.stringify({ workspace_id: workspaceId }),
  });
}

export function updateBrowserProfile(
  profileId: string,
  body: { name?: string; proxy?: string | null; enabled?: boolean },
): Promise<BrowserProfile> {
  return api<BrowserProfile>(`/api/browser/profiles/${profileId}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function deleteBrowserProfile(profileId: string): Promise<unknown> {
  return api(`/api/browser/profiles/${profileId}`, { method: "DELETE" });
}

export function listPublishTasks(workspaceId: string): Promise<PublishTask[]> {
  return api<PublishTask[]>(`/api/publish/tasks?workspace_id=${workspaceId}`);
}

export function createPublishTask(body: {
  workspace_id: string;
  account_id: string;
  asset_id: string;
  title: string;
  description: string;
  tags: string[];
  short_title?: string;
}): Promise<PublishTask> {
  return api<PublishTask>("/api/publish/tasks", { method: "POST", body: JSON.stringify(body) });
}

export function deletePublishTask(taskId: string): Promise<unknown> {
  return api(`/api/publish/tasks/${taskId}`, { method: "DELETE" });
}

export function generatePublishCopy(body: {
  workspace_id: string;
  asset_id?: string | null;
  brief?: string;
}): Promise<PublishCopy> {
  return api<PublishCopy>("/api/publish/copy", { method: "POST", body: JSON.stringify(body) });
}

export type WorkspaceSummary = components["schemas"]["WorkspaceSummaryOut"];

export function workspaceSummary(workspaceId: string): Promise<WorkspaceSummary> {
  return api<WorkspaceSummary>(`/api/workspaces/${workspaceId}/summary`);
}

export function renameProject(projectId: string, name: string): Promise<Project> {
  return api<Project>(`/api/projects/${projectId}`, { method: "PATCH", body: JSON.stringify({ name }) });
}

export function deleteProject(projectId: string): Promise<unknown> {
  return api(`/api/projects/${projectId}`, { method: "DELETE" });
}

export function listAssets(workspaceId: string, projectId?: string): Promise<Asset[]> {
  const params = new URLSearchParams({ workspace_id: workspaceId });
  if (projectId) params.set("project_id", projectId);
  return api<Asset[]>(`/api/assets?${params.toString()}`);
}

export type ComfyWorkflow = { path: string; name: string; modified: number | null };
/** 拉取某 ComfyUI 档案实例里保存的工作流,供生成时下拉选择。 */
export function listComfyuiWorkflows(profileId?: string): Promise<ComfyWorkflow[]> {
  const q = profileId ? `?profile_id=${encodeURIComponent(profileId)}` : "";
  return api<ComfyWorkflow[]>(`/api/generation/comfyui/workflows${q}`);
}

export type ComfyParam = {
  node_id: string;
  class_type: string;
  title: string | null;
  name: string;
  value: unknown;
  role: "prompt" | "negative" | "seed" | "width" | "height" | null;
  type: "INT" | "FLOAT" | "STRING" | "COMBO" | "BOOLEAN";
  options?: string[];
  min?: number;
  max?: number;
  step?: number;
  multiline?: boolean;
};
/** 提取某工作流的可调参数(类型/范围/当前值/角色),供动态表单渲染。 */
export function listComfyuiWorkflowParams(workflow: string, profileId?: string): Promise<ComfyParam[]> {
  const q = new URLSearchParams({ workflow });
  if (profileId) q.set("profile_id", profileId);
  return api<ComfyParam[]>(`/api/generation/comfyui/workflow-params?${q.toString()}`);
}

export function renameAsset(assetId: string, name: string): Promise<Asset> {
  return api<Asset>(`/api/assets/${assetId}`, { method: "PATCH", body: JSON.stringify({ name }) });
}

export function setAssetTags(assetId: string, tags: string[]): Promise<Asset> {
  return api<Asset>(`/api/assets/${assetId}`, { method: "PATCH", body: JSON.stringify({ tags }) });
}

export function deleteAsset(assetId: string): Promise<unknown> {
  return api(`/api/assets/${assetId}`, { method: "DELETE" });
}

export function transcribeAsset(assetId: string): Promise<Job> {
  return api<Job>(`/api/assets/${assetId}/transcribe`, { method: "POST" });
}

export function fetchJob(jobId: string): Promise<Job> {
  return api<Job>(`/api/jobs/${jobId}`);
}

export type ExportParams = {
  resolution: "original" | "1080p" | "720p" | "480p";
  fps: number | null;
  quality: "high" | "standard" | "compact";
};

export function exportSequence(sequenceId: string, params?: ExportParams): Promise<Job> {
  return api<Job>(`/api/sequences/${sequenceId}/export`, {
    method: "POST",
    ...(params ? { body: JSON.stringify(params) } : {}),
  });
}

export async function importAsset(params: {
  workspaceId: string;
  /** 省略 = 工作区级素材(素材页、AI 助手附件都走这条);只有剪辑页导入才挂项目。 */
  projectId?: string;
  file: File;
  name?: string;
}): Promise<Asset> {
  const form = new FormData();
  form.set("workspace_id", params.workspaceId);
  if (params.projectId) form.set("project_id", params.projectId);
  if (params.name) form.set("name", params.name);
  form.set("file", params.file);
  return api<Asset>("/api/assets/import", { method: "POST", body: form });
}

export interface Lut {
  id: string;
  workspace_id: string;
  name: string;
  original_filename: string;
  size: number;
  created_at?: string | null;
}

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

export interface Font {
  id: string;
  workspace_id: string;
  /** Read from the font file's own name table — what libass matches on at export. */
  family: string;
  original_filename: string;
  size: number;
  created_at?: string | null;
}

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
  // An @font-face url() sends no headers, so the token rides along like the other media URLs.
  const suffix = authToken ? `?token=${authToken}` : "";
  return `${API_BASE}/api/fonts/${fontId}/file${suffix}`;
}
