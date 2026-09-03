import type { components } from "@/api/generated/schema";
import type { Job } from "@/api/domains/jobs";
import { API_BASE, api, getAuthToken } from "@/api/transport";

export * from "@/api/transport";
export * from "@/api/domains/boards";
export * from "@/api/domains/browser";
export * from "@/api/domains/jobs";
export * from "@/api/domains/notifications";
export * from "@/api/domains/publish";
export * from "@/api/domains/scheduler";
export * from "@/api/domains/workflows";

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
  const token = getAuthToken();
  const suffix = token ? `&token=${token}` : "";
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
/** 改音色的说明性字段。参考音频不能改 —— 换了音频就是另一个音色,而用它生成过的配音还在时间线上。 */
export function updateVoice(id: string, body: { name?: string; reference_text?: string }): Promise<Voice> {
  return api<Voice>(`/api/voices/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}
/** 让本机的转写引擎听一遍参考音频,把参考文本填上 —— 比让用户打一遍自己说过的话强。 */
export function recognizeReference(id: string): Promise<Voice> {
  return api<Voice>(`/api/voices/${id}/recognize-reference`, { method: "POST" });
}
export function deleteVoice(id: string): Promise<void> {
  return api<void>(`/api/voices/${id}`, { method: "DELETE" });
}
export function voiceFromSpeaker(body: { asset_id: string; speaker?: string | null; name?: string }): Promise<Voice> {
  return api<Voice>("/api/voices/from-speaker", { method: "POST", body: JSON.stringify(body) });
}
export function synthesizeVoice(
  id: string,
  /** clone_engine 空 = 用设置页那个默认。设置页是默认,不是唯一。 */
  /** speed 只在引擎吃它时才发(见 TtsEngine.supports_speed)—— 发了却被忽略是另一种谎。 */
  body: { text: string; project_id?: string | null; clone_engine?: string; speed?: number },
): Promise<Job> {
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
  /** 接不接语速。接不了就别摆那个旋钮 —— 拨得动却不生效比没有更糟(配音要的正是"塞进原时长",
      用户会以为自己已经调过了)。缺省按支持处理,老引擎行为不变。 */
  supports_speed: boolean;
  note: string;
  /** 这台机器上现在跑得了吗。本地克隆按解释器探测给,远程引擎恒真 —— 界面据此在**挑引擎**
      的时候就说清楚,而不是等填完文本、点了生成才拒绝。 */
  ready: boolean;
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

export type RemoteEntry = {
  id: string;
  url: string;
  title: string;
  duration: number | null;
  uploader: string;
  thumbnail: string;
  /** 实际拿得到的画质高度(从高到低);空 = 未知(播放列表只做浅层探测)。 */
  heights?: number[];
};

export type UrlProbe = {
  title: string;
  is_playlist: boolean;
  entries: RemoteEntry[];
  truncated: boolean;
  /** 这一批从第几条开始(1 起)。 */
  start?: number;
};

/** 这个链接后面有什么 —— 只读元数据,不下载任何媒体流。 */
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

/** 把选中的条目下载进素材库。返回任务 —— 下载要跑一阵。 */
export function importFromUrl(body: {
  workspace_id: string;
  project_id?: string | null;
  items: { url: string; title: string }[];
  kind: "video" | "audio";
  /** 画质上限(0 = 不限)。上限而不是精确值:同一批里每条能给的画质不一样。 */
  max_height?: number;
  /** 借哪个浏览器池档案的登录态;空 = 按公开内容下载。 */
  profile_id?: string | null;
}): Promise<Job> {
  return api<Job>("/api/assets/import-url", { method: "POST", body: JSON.stringify(body) });
}

export type F5Model = {
  id: string;
  label: string;
  languages: string[];
  note: string;
  expected_bytes: number;
  /** 上面那个体积是问下载源问出来的,还是写死的估算(同 TtsEngine)。 */
  total_is_estimate: boolean;
  installed: boolean;
  status: string;
  progress: number;
  /** 下载中实测的字节 / 总量 / 速度 / 剩余秒数 —— 和引擎权重、转写模型报的是同一套。 */
  downloaded_bytes: number;
  total_bytes: number;
  speed_bps: number;
  eta_seconds: number | null;
  message: string;
  error: string;
};

/** 本地克隆能用哪几份权重 —— 引擎什么语言都支持,支持范围由权重决定。 */
export function listF5Models(): Promise<F5Model[]> {
  return api<F5Model[]>("/api/tts/f5-models");
}

export function downloadF5Model(modelId: string): Promise<F5Model> {
  return api<F5Model>(`/api/tts/f5-models/${modelId}/download`, { method: "POST" });
}

/** 给选中的字幕条配音,产物落到一条新的音频轨。返回编排任务(内部逐条排合成子任务)。 */
export function dubSubtitles(
  sequenceId: string,
  body: {
    clip_ids: string[];
    match_duration?: boolean;
    /** 双语字幕念哪一行:整段 / 只念第一行 / 只念最后一行。 */
    line?: "all" | "first" | "last";
    engine?: string;
    voice_id?: string | null;
    clone_engine?: string;
    /** 明说用哪份克隆权重;空 = 按文字自动挑(拉丁字母的语言自动挑不中,只能明说)。 */
    clone_model?: string;
    engine_voice?: string;
    speed?: number;
  },
): Promise<Job> {
  return api<Job>(`/api/sequences/${sequenceId}/dub-subtitles`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function voiceSampleUrl(id: string): string {
  const token = getAuthToken();
  const suffix = token ? `?token=${token}` : "";
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
export type GenerationJob = components["schemas"]["GenerationJobOut"];
export type GenerationCreateResponse = components["schemas"]["GenerationCreateResponse"];
export type PluginPackage = components["schemas"]["PluginPackageOut"];
export type PluginInstance = components["schemas"]["PluginInstanceOut"];
export type PluginField = components["schemas"]["PluginFieldOut"];
export type PluginToolState = components["schemas"]["PluginToolStateOut"];
export type PluginTool = components["schemas"]["PluginToolOut"];
export type PluginInvocation = components["schemas"]["PluginInvocationOut"];
export type PluginPermissionGrant = components["schemas"]["PluginPermissionGrantOut"];
export type PluginCredential = components["schemas"]["PluginCredentialOut"];

/** 桌面端把文件拖到应用图标上 / 「用 Mosael 打开」:后端按本机绝对路径入库。
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
  const token = getAuthToken();
  const suffix = token ? `?token=${token}` : "";
  return `${API_BASE}/api/assets/${assetId}/file${suffix}`;
}

/** 图片显示用的全尺寸浏览器兼容版本。HEIC 等格式由后端按需派生 JPEG,原件仍走 assetFileUrl。 */
export function assetPreviewUrl(assetId: string): string {
  const token = getAuthToken();
  const suffix = token ? `?token=${token}` : "";
  return `${API_BASE}/api/assets/${assetId}/preview${suffix}`;
}

export function assetThumbnailUrl(assetId: string): string {
  const token = getAuthToken();
  const suffix = token ? `?token=${token}` : "";
  return `${API_BASE}/api/assets/${assetId}/thumbnail${suffix}`;
}

/** 取这段视频某一时刻的一帧,存成一份新素材。**原素材不动。** */
export function grabAssetFrame(assetId: string, at: number, projectId?: string | null): Promise<Asset> {
  return api<Asset>(`/api/assets/${assetId}/frame`, {
    method: "POST",
    body: JSON.stringify({ at, project_id: projectId ?? null }),
  });
}

/** 取时间线播放头这一帧。**走渲染那条路** —— 预览里花字和字幕是 DOM 叠的,画布抓不到。 */
export function grabSequenceFrame(sequenceId: string, at: number): Promise<Asset> {
  return api<Asset>(`/api/sequences/${sequenceId}/frame`, { method: "POST", body: JSON.stringify({ at }) });
}

/** 剪辑面板用的帧条:整条片子均匀取几帧拼成的一张横向长图。按需生成、落盘缓存。 */
export function assetFilmstripUrl(assetId: string): string {
  const token = getAuthToken();
  const suffix = token ? `?token=${token}` : "";
  return `${API_BASE}/api/assets/${assetId}/filmstrip${suffix}`;
}

/** The 720p preview proxy the WebCodecs compositor decodes (media_info.proxy_status === "ready"). */
export function assetProxyUrl(assetId: string): string {
  const token = getAuthToken();
  const suffix = token ? `?token=${token}` : "";
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

export function cutClipRangesBatch(
  sequenceId: string,
  cuts: Array<{ clip_id: string; ranges: Array<{ src_start: number; src_end: number }> }>,
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/cut-ranges`, {
    method: "POST",
    body: JSON.stringify({ cuts }),
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

export function splitClipAtPointsBatch(
  sequenceId: string,
  splits: Array<{ clip_id: string; src_times: number[] }>,
): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/clips/split-points`, {
    method: "POST",
    body: JSON.stringify({ splits }),
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

/** 一次请求最多送多少条。**和后端的上限对齐**(api/schemas.TranslateRequest.texts)。
 *
 * 那个上限是防止一次请求打垮后端的安全阀,不是"能翻多少字幕"的答案 —— 而一条一小时视频的
 * 字幕轨轻松上千条。此前超过就直接 422 报错,用户看到的是"翻译失败"而不是"分两次"。 */
const TRANSLATE_BATCH = 400;

export async function translateTexts(
  workspaceId: string,
  texts: string[],
  targetLang: string,
  engine: "google" | "ai" = "google",
  /** 每一批译完就交出去(带这一批在 `texts` 里的起始偏移)。**会被 await**:调用方在这里
   *  把这一批写进轨道,写失败就中止后面的批次 —— 已写进去的留着,没翻的保持原文。 */
  onBatch?: (translations: string[], offset: number) => void | Promise<void>,
): Promise<{ translations: string[] }> {
  // **分批是这一层的事,不是调用方的。** 出口只有这一个,放在这里两个调用点都不用知道有批次;
  // 让每个调用方各自切一遍,就是同一件事写两遍,而漏掉一处就是一条"超过 N 条就报错"。
  const translations: string[] = [];
  for (let start = 0; start < texts.length; start += TRANSLATE_BATCH) {
    const batch = texts.slice(start, start + TRANSLATE_BATCH);
    // 串行而不是并发:后端对每一批**内部**已经开了线程池并发跑,再并发几批只是把同一个
    // 上游端点打得更狠(google 那条免费路尤其容易限流),而总时长省不下多少。
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

/* ---------- 会话分组 ---------- */

export type SessionGroup = components["schemas"]["SessionGroupOut"];

/** 分组挂在哪一种会话上。对话和生成共用一张表、一组接口,但**各自一套分组**。 */
export type SessionGroupKind = "agent" | "generation";

export function listSessionGroups(workspaceId: string, kind: SessionGroupKind): Promise<SessionGroup[]> {
  return api<SessionGroup[]>(`/api/session-groups?workspace_id=${workspaceId}&kind=${kind}`);
}

export function createSessionGroup(
  workspaceId: string,
  kind: SessionGroupKind,
  name: string,
): Promise<SessionGroup> {
  return api<SessionGroup>("/api/session-groups", {
    method: "POST",
    body: JSON.stringify({ workspace_id: workspaceId, kind, name }),
  });
}

export function renameSessionGroup(groupId: string, name: string): Promise<SessionGroup> {
  return api<SessionGroup>(`/api/session-groups/${groupId}`, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });
}

/** 删分组不删会话 —— 成员退回未分组(后端显式清空,见 domain/session_groups)。 */
export function deleteSessionGroup(groupId: string): Promise<unknown> {
  return api(`/api/session-groups/${groupId}`, { method: "DELETE" });
}

export function deleteAgentSession(sessionId: string): Promise<unknown> {
  return api(`/api/agent/sessions/${sessionId}`, { method: "DELETE" });
}

/** 某能力下所有可用模型(跨连接)。文案生成列的是 chat。 */
export interface CapabilityModel {
  provider_profile_id: string;
  provider_name: string;
  model: string;
  display_name: string;
}

export function listCapabilityModels(
  capability: string,
  surface: "all" | "agent" | "direct" | "gateway" | "automation" = "all",
): Promise<CapabilityModel[]> {
  return api<CapabilityModel[]>(`/api/settings/capability-models/${capability}?surface=${surface}`);
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

/** `language` 空 = 按中文预设转(主场景);"auto" = 让引擎自己判语种;具体语言 = 按它选模型。
 *  **"没说"和"要自动"是两件事**,后端据此挑 FunASR 的中文预设还是多语种模型。 */
export function transcribeAsset(assetId: string, language = ""): Promise<Job> {
  const query = language ? `?language=${encodeURIComponent(language)}` : "";
  return api<Job>(`/api/assets/${assetId}/transcribe${query}`, { method: "POST" });
}

/** 生成一份新的 GIF 素材；原视频不变。 */
export function convertVideoToGif(
  assetId: string,
  options: { fps?: number; width?: number; start?: number; duration?: number | null } = {},
): Promise<Job> {
  return api<Job>(`/api/assets/${assetId}/convert-gif`, {
    method: "POST",
    body: JSON.stringify(options),
  });
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
  const token = getAuthToken();
  const suffix = token ? `?token=${token}` : "";
  return `${API_BASE}/api/fonts/${fontId}/file${suffix}`;
}
