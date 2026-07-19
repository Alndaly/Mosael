import type { components } from "@/api/generated/schema";

// 服务器可切换(团队模式铺垫):默认本机后端,localStorage 记住自定义地址。
// 切换后整页 reload,让所有模块用新地址重新初始化;换服务器后原 token 失效
// 会命中 401 → 自动回到登录页。
const SERVER_KEY = "mibu.server.url";
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

const TOKEN_KEY = "mibu.auth.token";
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

export type User = components["schemas"]["UserOut"];
export type AuthOut = components["schemas"]["AuthOut"];

export type Workspace = components["schemas"]["WorkspaceOut"];
export type WorkspaceMember = components["schemas"]["WorkspaceMemberOut"];
export type MembersInfo = components["schemas"]["MembersOut"];

export function listMembers(workspaceId: string): Promise<MembersInfo> {
  return api<MembersInfo>(`/api/workspaces/${workspaceId}/members`);
}
export function addMember(workspaceId: string, body: { username: string; password?: string; role: string }): Promise<WorkspaceMember> {
  return api<WorkspaceMember>(`/api/workspaces/${workspaceId}/members`, { method: "POST", body: JSON.stringify(body) });
}
export function setMemberRole(workspaceId: string, userId: string, role: string): Promise<WorkspaceMember> {
  return api<WorkspaceMember>(`/api/workspaces/${workspaceId}/members/${userId}`, { method: "PATCH", body: JSON.stringify({ role }) });
}
export function setMemberPerms(workspaceId: string, userId: string, perms: Record<string, boolean>): Promise<WorkspaceMember> {
  return api<WorkspaceMember>(`/api/workspaces/${workspaceId}/members/${userId}/perms`, { method: "PATCH", body: JSON.stringify({ perms }) });
}
export function removeMember(workspaceId: string, userId: string): Promise<void> {
  return api<void>(`/api/workspaces/${workspaceId}/members/${userId}`, { method: "DELETE" });
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

export function listJobEvents(jobId: string): Promise<TaskEvent[]> {
  return api<TaskEvent[]>(`/api/jobs/${jobId}/events`);
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
export type GenerationModel = components["schemas"]["GenerationModelOut"];
export type GenerationJob = components["schemas"]["GenerationJobOut"];
export type GenerationCreateResponse = components["schemas"]["GenerationCreateResponse"];
export type ScheduledTask = components["schemas"]["ScheduledTaskOut"];
export type ScheduledTaskRun = components["schemas"]["ScheduledTaskRunOut"];
export type RunScheduledTaskResponse = components["schemas"]["RunScheduledTaskResponse"];
export type Plugin = components["schemas"]["PluginOut"];
export type Workflow = components["schemas"]["WorkflowOut"];
export type Batch = components["schemas"]["BatchOut"];
export type PublishPlatform = components["schemas"]["PublishPlatformOut"];
export type PublishAccount = components["schemas"]["PublishAccountOut"];
export type PublishTask = components["schemas"]["PublishTaskOut"];
export type PublishCopy = components["schemas"]["PublishCopyResponse"];
export type BatchItem = components["schemas"]["BatchItemOut"];
export type WorkflowNodeType = components["schemas"]["WorkflowNodeTypeOut"];
export type WorkflowAiEditResponse = components["schemas"]["WorkflowAiEditResponse"];
export type PluginTool = components["schemas"]["PluginToolOut"];
export type PluginInvocation = components["schemas"]["PluginInvocationOut"];
export type PluginPermissionGrant = components["schemas"]["PluginPermissionGrantOut"];

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const auth: Record<string, string> = authToken ? { Authorization: `Bearer ${authToken}` } : {};
  const headers =
    init?.body instanceof FormData
      ? { ...auth, ...(init?.headers as Record<string, string> | undefined) }
      : { "Content-Type": "application/json", ...auth, ...(init?.headers as Record<string, string> | undefined) };
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (res.status === 401 && !path.startsWith("/api/auth/")) {
    onUnauthorized?.();
    throw new Error("Not authenticated");
  }
  if (!res.ok) throw new Error(await res.text());
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
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
  body: { track_id: string; asset_id: string; timeline_start: number; src_in: number; src_out: number },
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

export function setClipTransform(
  sequenceId: string,
  clipId: string,
  transform: Record<string, number>,
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

export function removeTrack(sequenceId: string, trackId: string): Promise<Sequence> {
  return api<Sequence>(`/api/sequences/${sequenceId}/tracks/${trackId}`, { method: "DELETE" });
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

export type AgentSessionInfo = components["schemas"]["AgentSessionOut"];

export function workflowAgentSession(workflowId: string): Promise<AgentSessionInfo> {
  return api<AgentSessionInfo>(`/api/workflows/${workflowId}/agent-session`, { method: "POST" });
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

export function runWorkflow(workflowId: string, params: Record<string, unknown> = {}): Promise<Job> {
  return api<Job>(`/api/workflows/${workflowId}/run`, { method: "POST", body: JSON.stringify({ params }) });
}

export function fetchWorkflowNodeTypes(): Promise<WorkflowNodeType[]> {
  return api<WorkflowNodeType[]>("/api/workflows/node-types");
}

export function aiEditWorkflow(
  workflowId: string,
  body: { instruction: string; graph?: WorkflowGraph },
): Promise<WorkflowAiEditResponse> {
  return api<WorkflowAiEditResponse>(`/api/workflows/${workflowId}/ai-edit`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function listBatches(workspaceId: string): Promise<Batch[]> {
  return api<Batch[]>(`/api/batches?workspace_id=${workspaceId}`);
}

export function createBatch(body: {
  workspace_id: string;
  workflow_id: string;
  name: string;
  params_list: Array<Record<string, unknown>>;
}): Promise<Batch> {
  return api<Batch>("/api/batches", { method: "POST", body: JSON.stringify(body) });
}

export function deleteBatch(batchId: string): Promise<unknown> {
  return api(`/api/batches/${batchId}`, { method: "DELETE" });
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

export interface CredentialStatus {
  provider: string;
  configured: boolean;
  hint: string;
}

/** 各生成服务商的密钥配置状态(secret 不出后端,只回 configured + 尾号提示)。 */
export function listCredentials(): Promise<CredentialStatus[]> {
  return api<CredentialStatus[]>("/api/settings/credentials");
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

export function exportSequence(sequenceId: string): Promise<Job> {
  return api<Job>(`/api/sequences/${sequenceId}/export`, { method: "POST" });
}

export async function importAsset(params: {
  workspaceId: string;
  projectId: string;
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
