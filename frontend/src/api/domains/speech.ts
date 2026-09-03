import type { components } from "@/api/generated/schema";
import type { Job } from "@/api/domains/jobs";
import { API_BASE, api, getAuthToken } from "@/api/transport";

export type AsrModel = components["schemas"]["AsrModelOut"];
export type Voice = components["schemas"]["VoiceOut"];
export type Transcript = components["schemas"]["TranscriptOut"];
export type TtsEngine = components["schemas"]["TtsEngineOut"];
export type TtsConfig = components["schemas"]["TtsConfigOut"];

export function listAsrModels(): Promise<AsrModel[]> {
  return api<AsrModel[]>("/api/asr/models");
}

export function downloadAsrModel(id: string): Promise<AsrModel> {
  return api<AsrModel>(`/api/asr/models/${encodeURIComponent(id)}/download`, { method: "POST" });
}

export function listVoices(workspaceId: string): Promise<Voice[]> {
  return api<Voice[]>(`/api/voices?workspace_id=${workspaceId}`);
}

export function uploadVoice(args: {
  workspaceId: string;
  name: string;
  referenceText: string;
  file: File;
}): Promise<Voice> {
  const form = new FormData();
  form.append("workspace_id", args.workspaceId);
  form.append("name", args.name);
  form.append("reference_text", args.referenceText);
  form.append("file", args.file);
  return api<Voice>("/api/voices/upload", { method: "POST", body: form });
}

/** Reference audio is immutable: changing it creates a different voice identity. */
export function updateVoice(id: string, body: { name?: string; reference_text?: string }): Promise<Voice> {
  return api<Voice>(`/api/voices/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function recognizeReference(id: string): Promise<Voice> {
  return api<Voice>(`/api/voices/${id}/recognize-reference`, { method: "POST" });
}

export function deleteVoice(id: string): Promise<void> {
  return api<void>(`/api/voices/${id}`, { method: "DELETE" });
}

export function voiceFromSpeaker(body: {
  asset_id: string;
  speaker?: string | null;
  name?: string;
}): Promise<Voice> {
  return api<Voice>("/api/voices/from-speaker", { method: "POST", body: JSON.stringify(body) });
}

export function synthesizeVoice(
  id: string,
  body: { text: string; project_id?: string | null; clone_engine?: string; speed?: number },
): Promise<Job> {
  return api<Job>(`/api/voices/${id}/synthesize`, { method: "POST", body: JSON.stringify(body) });
}

/** A remote/local synthesis choice offered by the dubbing UI. */
export interface TtsEngineChoice {
  id: string;
  label: string;
  needs_key: boolean;
  needs_voice_id: boolean;
  voices: string[];
  supports_speed: boolean;
  note: string;
  ready: boolean;
}

export interface TtsVoice {
  value: string;
  label: string;
  /** Volcengine resource family echoed during synthesis. */
  resource_id: string;
}

export function listTtsVoices(engine: string): Promise<TtsVoice[]> {
  return api<TtsVoice[]>(`/api/tts/voices?engine=${encodeURIComponent(engine)}`);
}

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

/** Synthesis through an engine-managed voice rather than a stored Voice row. */
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

export interface F5Model {
  id: string;
  label: string;
  languages: string[];
  note: string;
  expected_bytes: number;
  total_is_estimate: boolean;
  installed: boolean;
  status: string;
  progress: number;
  downloaded_bytes: number;
  total_bytes: number;
  speed_bps: number;
  eta_seconds: number | null;
  message: string;
  error: string;
}

export function listF5Models(): Promise<F5Model[]> {
  return api<F5Model[]>("/api/tts/f5-models");
}

export function downloadF5Model(modelId: string): Promise<F5Model> {
  return api<F5Model>(`/api/tts/f5-models/${modelId}/download`, { method: "POST" });
}

/** Generate one audio track from selected subtitle clips as an orchestration job. */
export function dubSubtitles(
  sequenceId: string,
  body: {
    clip_ids: string[];
    match_duration?: boolean;
    line?: "all" | "first" | "last";
    engine?: string;
    voice_id?: string | null;
    clone_engine?: string;
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
