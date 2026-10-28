import type { components } from "@/api/generated/schema";
import type { Job } from "@/api/domains/jobs";
import { API_BASE, ApiError, api, apiBlob, getAuthToken } from "@/api/transport";
import { baseRevisionOf, noticeConflict, type SequenceRef } from "@/api/domains/editor";

/**
 * 配音引擎的 id 是能力表里的提供方 id(ADR 0032 第四步):内置的带 `builtin:` 前缀,插件连接是它的连接 id。
 * 要按某一家分支的地方只认这里的常量,不在各处手写字面量。
 */
/** 克隆音色(工作区配音库里的那些嗓子)。没选引擎时按它算。 */
export const CLONE_ENGINE = "builtin:clone";
/**
 * 字幕配音「压进原字幕长度」默认开不开 —— **抄的是后端 subtitle_dub.DEFAULT_MATCH_DURATION**,
 * 由 dubDefaults.parity.test.ts 对着 openapi.json 里的默认值钉住。剪辑台、智能体、工作流是同一个默认。
 */
export const DEFAULT_MATCH_DURATION = true;
/** Edge:不要钥匙,音色名里带着语言(见 editor/dubLanguage)。 */
export const EDGE_ENGINE = "builtin:edge";
/** 播客引擎。一次产出一整段双人对话 —— 它在创作页里是自己的一种(播客,ADR 0055)。 */
export const PODCAST_ENGINE = "builtin:volcano-podcast";

export type AsrModel = components["schemas"]["AsrModelOut"];
export type Voice = components["schemas"]["VoiceOut"];
/** 一把嗓子复刻到远端引擎上的一份副本(ADR 0037):在哪条连接、哪个模型上,现在什么状态。 */
export type RemoteCopy = components["schemas"]["RemoteCopyOut"];
export type VoiceDeleteResult = components["schemas"]["VoiceDeleteOut"];
export type Transcript = components["schemas"]["TranscriptOut"];
export type TtsEngine = components["schemas"]["TtsEngineOut"];
export type TtsConfig = components["schemas"]["TtsConfigOut"];
export type SeparationEngine = components["schemas"]["SeparationEngineOut"];
/** 字幕配音之后原声怎么办。档位由后端声明(domain/voices/original_audio)。 */
export type OriginalAudio = components["schemas"]["SubtitleDubRequest"]["original_audio"];
export const ORIGINAL_AUDIO_MODES = ["duck", "mute", "keep", "separate"] as const satisfies readonly OriginalAudio[];
// 后端多了一档而这里没列,编译就过不去。
const allOriginalAudioModesListed: Exclude<OriginalAudio, (typeof ORIGINAL_AUDIO_MODES)[number]> extends never ? true : never = true;
void allOriginalAudioModesListed;

export function listAsrModels(): Promise<AsrModel[]> {
  return api<AsrModel[]>("/api/asr/models");
}

export function downloadAsrModel(id: string): Promise<AsrModel> {
  return api<AsrModel>(`/api/asr/models/${encodeURIComponent(id)}/download`, { method: "POST" });
}

/**
 * 把这一个设成**这台机器**的默认转写模型(管理 → 引擎 → 转写模型;只有部署管理员能调)。
 * 回包是改完之后的那一行 —— 界面照它再向后端问一次整张列表,不自己把别的行改掉。
 */
export function setDefaultAsrModel(id: string): Promise<AsrModel> {
  return api<AsrModel>(`/api/asr/models/${encodeURIComponent(id)}/default`, { method: "PUT" });
}

/** 人声/背景音分离引擎(ADR-0016)。装在**后端主机**上,所以和转写模型同一条路。 */
export function listSeparationEngines(): Promise<SeparationEngine[]> {
  return api<SeparationEngine[]>("/api/separation/engines");
}

export function installSeparationEngine(engine: string): Promise<SeparationEngine> {
  return api<SeparationEngine>(`/api/separation/engines/${encodeURIComponent(engine)}/install`, { method: "POST" });
}

export function listVoices(workspaceId: string): Promise<Voice[]> {
  return api<Voice[]>(`/api/voices?workspace_id=${workspaceId}`);
}

export function uploadVoice(args: {
  workspaceId: string;
  name: string;
  referenceText: string;
  /** 这把嗓子是谁的:self / authorized / fictional(必选,见后端 voices 的授权声明)。 */
  consentKind: string;
  file: File;
}): Promise<Voice> {
  const form = new FormData();
  form.append("workspace_id", args.workspaceId);
  form.append("name", args.name);
  form.append("reference_text", args.referenceText);
  form.append("consent_kind", args.consentKind);
  form.append("file", args.file);
  return api<Voice>("/api/voices/upload", { method: "POST", body: form });
}

/** Reference audio is immutable: changing it creates a different voice identity. */
export function updateVoice(id: string, body: { name?: string; reference_text?: string; consent_kind?: string }): Promise<Voice> {
  return api<Voice>(`/api/voices/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function recognizeReference(id: string): Promise<Voice> {
  return api<Voice>(`/api/voices/${id}/recognize-reference`, { method: "POST" });
}

/** 删一把嗓子。它在远端的副本先删,删不掉的(钥匙失效、网络)列在 `remote_failures` 里 —— 本机这一行照删。 */
export function deleteVoice(id: string): Promise<VoiceDeleteResult> {
  return api<VoiceDeleteResult>(`/api/voices/${id}`, { method: "DELETE" });
}

/**
 * 把一把嗓子复刻到远端引擎上(配音库的「复刻到百炼」,ADR 0037),排一个复刻任务。`consent` 是确认框里点了同意:
 * 这个账号没同意过、又没带它,回 409(`remote_voice_consent_required`,见 `remoteConsentRequest`)。
 */
export function copyVoiceToEngine(
  voiceId: string,
  body: { engine: string; provider_profile_id?: string | null; consent?: boolean },
): Promise<Job> {
  return api<Job>(`/api/voices/${encodeURIComponent(voiceId)}/remote-copies`, { method: "POST", body: JSON.stringify(body) });
}

/** 「要把参考音频传到这个账号里,而它还没同意过」那个 409 带的东西(后端 voices/remote.RemoteConsentRequired)。 */
export type RemoteConsentRequest = {
  voice_id: string;
  voice_name: string;
  /** 能力表里的引擎 id(`builtin:alibaba-cosyvoice`)。 */
  engine: string;
  provider_profile_id: string;
  /** 那条连接叫什么。 */
  connection: string;
  /** 复刻到哪个模型上。 */
  model: string;
  message: string;
};

export const REMOTE_CONSENT_REQUIRED = "remote_voice_consent_required";

/** 这次失败是不是「还没同意上传」;是就交回确认框要说的那几样,不是就是 null。 */
export function remoteConsentRequest(error: unknown): RemoteConsentRequest | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  try {
    const detail = (JSON.parse(error.body) as { detail?: Partial<RemoteConsentRequest> & { code?: unknown } }).detail;
    return detail?.code === REMOTE_CONSENT_REQUIRED && detail.voice_id && detail.engine
      ? (detail as RemoteConsentRequest)
      : null;
  } catch {
    return null;
  }
}

export function voiceFromSpeaker(body: {
  asset_id: string;
  speaker?: string | null;
  name?: string;
  consent_kind: string;
}): Promise<Voice> {
  return api<Voice>("/api/voices/from-speaker", { method: "POST", body: JSON.stringify(body) });
}

/** A remote/local synthesis choice offered by the dubbing UI. */
export type TtsEngineChoice = components["schemas"]["TtsEngineChoiceOut"];

/** 音色目录里的一项(ADR 0087)。所有挑音色的地方同一个形状;`extra` 只有那一家后端适配器解释,界面不读。 */
export type VoiceOption = components["schemas"]["VoiceOptionOut"];

/**
 * 「选了哪把嗓子」(ADR 0087 的 `VoiceRef`):所有收音色、回音色的接口都是这一个形状。`voice`(引擎自己的音色)与
 * `cloned_voice`(配音库里的克隆音色)恰好一个。**只经下面两个函数造**,调用处不手拼字段。
 */
export type VoiceRef = Pick<VoiceRefBody, "engine"> & Partial<Omit<VoiceRefBody, "engine">>;
//: 生成的类型把带默认值的格都标成了必填(回包里确实都在);写的那一侧只有引擎是必须的,其余缺了就是默认。
type VoiceRefBody = components["schemas"]["VoiceRefBody"];

/**
 * 在一个引擎的音色目录里点了一项 → 那把嗓子。目录那一项的 `extra`(火山的资源族)原样带上 —— 只有目录知道它,
 * 而合成时要它对得上;界面不读、不改。配音库里的嗓子(`source: "cloned"`)写 `cloned_voice`。
 */
export function voiceRefOf(engine: string, option: Pick<VoiceOption, "id" | "source" | "extra">): VoiceRef {
  return option.source === "cloned"
    ? { engine, cloned_voice: option.id }
    : { engine, voice: option.id, ...(option.extra && Object.keys(option.extra).length ? { extra: option.extra } : {}) };
}

/** 本机克隆念配音库里的一把嗓子。`model` 写哪个本机引擎 / 哪一份权重(`f5-tts`、`f5-tts/fr`、`fish-speech`),空 = 部署默认。 */
export function clonedVoiceRef(voiceId: string, model = ""): VoiceRef {
  return { engine: CLONE_ENGINE, cloned_voice: voiceId, ...(model ? { model } : {}) };
}

/** 这把嗓子在它的目录里那一格 id(引擎音色或克隆音色)—— 给人看名字、查目录用。 */
export function spokenId(voice: Pick<VoiceRef, "voice" | "cloned_voice">): string {
  return voice.voice || voice.cloned_voice || "";
}

/**
 * 一个引擎能念的音色。带上工作区时,能复刻的引擎(CosyVoice)在系统音色后面多一组这个工作区配音库里的嗓子
 * (`source: "cloned"`,ADR 0037),选它就是 `voiceRefOf` 给出的 `cloned_voice`。
 */
export function listTtsVoices(engine: string, workspaceId?: string): Promise<VoiceOption[]> {
  const workspace = workspaceId ? `&workspace_id=${encodeURIComponent(workspaceId)}` : "";
  return api<VoiceOption[]>(`/api/tts/voices?engine=${encodeURIComponent(engine)}${workspace}`);
}

/** 这一项是配音库里的克隆嗓子(念的是它的远端副本),不是引擎自己的音色。 */
export function isClonedVoice(voice: VoiceOption | null | undefined): boolean {
  return voice?.source === "cloned";
}

export function listTtsEngines(): Promise<TtsEngineChoice[]> {
  return api<TtsEngineChoice[]>("/api/tts/engines");
}

export type VoiceDefault = components["schemas"]["VoiceDefaultOut"];

/**
 * 把这台机器的默认设成**一把嗓子**(`PUT /api/settings/voice-default`,只有部署管理员能调)。
 *
 * 默认不是一家提供方:引擎和音色是成对选的,所以整把一起写、一起校验(不属于这个引擎的音色回 409)。
 * `null` = 清掉默认。回的是改完之后的那一把;候选列表上的 `is_default` 才是当前默认的唯一来源。
 */
export function setVoiceDefault(voice: VoiceRef | null): Promise<VoiceDefault> {
  return api<VoiceDefault>("/api/settings/voice-default", { method: "PUT", body: JSON.stringify({ voice }) });
}

/**
 * 用一把嗓子念一段,产出登记成素材(`POST /api/tts/synthesize`)。本机克隆、远端引擎、本机预置同一个接口;
 * 能复刻的引擎(CosyVoice)念配音库里的嗓子时,这个账号第一次用要同意上传(见 `remoteConsentRequest`)。
 */
export function synthesize(body: {
  workspace_id: string;
  text: string;
  voice: VoiceRef;
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
  /** 下载中量到的总量;**`null` = 还不知道**(后端以前在这里报 0,界面于是画出「0 MB / 0%」)。 */
  total_bytes: number | null;
  speed_bps: number;
  eta_seconds: number | null;
  message: string;
  error: string;
  /** 这一次失败发生的时刻(UTC ISO);没失败过是空串。失败那一行用它说「最后一次 …」。 */
  failed_at: string;
}

export function listF5Models(): Promise<F5Model[]> {
  return api<F5Model[]>("/api/tts/f5-models");
}

export function downloadF5Model(modelId: string): Promise<F5Model> {
  return api<F5Model>(`/api/tts/f5-models/${modelId}/download`, { method: "POST" });
}

/** Generate one audio track from selected subtitle clips as an orchestration job. */
export async function dubSubtitles(
  sequence: SequenceRef,
  body: {
    clip_ids: string[];
    /** 配哪条字幕轨。一次只配一条:条目跨轨会被后端拒绝。 */
    track_id?: string;
    match_duration?: boolean;
    line?: "all" | "first" | "last";
    original_audio?: OriginalAudio;
    /** 用哪把嗓子念;不给 = 用默认那一把。 */
    voice?: VoiceRef | null;
    speed?: number;
  },
): Promise<Job> {
  // 排的是任务,但配哪几句是照着这一版选的:带上 base_revision,那几条字幕在这之后被别人改过就 409(后端 _ensure_seen),
  // 剪辑页随即换成最新的一版(noticeConflict),不在一份过时的选择上花钱。
  try {
    return await api<Job>(`/api/sequences/${sequence.id}/dub-subtitles?base_revision=${baseRevisionOf(sequence)}`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  } catch (error) {
    noticeConflict(error);
    throw error;
  }
}

/**
 * 试听一把嗓子,拿回一段音频。本地克隆的音色放它的参考录音(那就是它);别的引擎念 `text` 这一小句,走和真用时
 * 同一条合成路(`POST /api/tts/preview`),不建任务、不进素材库。
 */
export function fetchVoicePreview(body: { workspace_id: string; voice: VoiceRef; text: string }): Promise<Blob> {
  return body.voice.engine === CLONE_ENGINE && body.voice.cloned_voice
    ? apiBlob(`/api/voices/${encodeURIComponent(body.voice.cloned_voice)}/sample`)
    : apiBlob("/api/tts/preview", { method: "POST", body: JSON.stringify(body) });
}

/** 智能体念一句话(消息下的「念给我听」、免提):要求「让它出声」开着、选好了音色,没选回 409(`POST /api/agent/speech`)。 */
export function speakWithAgentVoice(body: { workspace_id: string; text: string }): Promise<Blob> {
  return apiBlob("/api/agent/speech", { method: "POST", body: JSON.stringify(body) });
}

/**
 * 试听设置里存着的那份对话音色(`POST /api/agent/speech/preview`)。和对话里真念走同一个合成,
 * 只是不要求「让它出声」开着 —— 试听发生在打开之前。
 */
export function fetchAgentVoicePreview(body: { workspace_id: string; text: string }): Promise<Blob> {
  return apiBlob("/api/agent/speech/preview", { method: "POST", body: JSON.stringify(body) });
}

/**
 * 用设置「语音对话」里选的那把嗓子念他自己的一段字(笔记选区工具条的「朗读」,`POST /api/agent/speech/read`)。
 * 只要求选好、不要求「让它出声」开着;没选过回 409,调用方据此退回免费的 Edge。不建任务、不进素材库。
 */
export function readWithAgentVoice(body: { workspace_id: string; text: string }): Promise<Blob> {
  return apiBlob("/api/agent/speech/read", { method: "POST", body: JSON.stringify(body) });
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

export type InstallSource = components["schemas"]["InstallSourceOut"];

/** 本机引擎(转写 / 声音克隆 / 人声分离)装依赖时用哪个 pip 索引。三个引擎共用这一份。 */
export function getInstallSource(): Promise<InstallSource> {
  return api<InstallSource>("/api/settings/install-source");
}

/** 只改给了的那一行(依赖源、PyTorch 源、GitHub 镜像、R2 更新源、插件索引、模型下载源);空串 = 默认源。 */
export function updateInstallSource(
  body: { pip_index?: string; npm_registry?: string; pytorch_index?: string; github_mirror?: string; update_feed_url?: string; plugin_registry_url?: string; model_source?: string },
): Promise<InstallSource> {
  return api<InstallSource>("/api/settings/install-source", { method: "PUT", body: JSON.stringify(body) });
}

export function getTtsConfig(): Promise<TtsConfig> {
  return api<TtsConfig>("/api/settings/tts");
}

export function updateTtsConfig(body: {
  engine: string;
  python_path: string;
  fish_repo_dir?: string;
  fish_model_dir?: string;
}): Promise<TtsConfig> {
  return api<TtsConfig>("/api/settings/tts", { method: "PUT", body: JSON.stringify(body) });
}

export type AgentVoice = components["schemas"]["AgentVoiceOut"];

/** 语音对话用哪个音色。**和配音的 TTS 默认是两行配置** —— 配音要质量,对话要延迟。 */
export function getAgentVoice(): Promise<AgentVoice> {
  return api<AgentVoice>("/api/settings/agent-voice");
}

/** 存「语音对话」那一份:那把嗓子(`null` = 不选了)和念法。嗓子用写入形状(见 `VoiceRef`)。 */
export function setAgentVoice(
  body: Omit<components["schemas"]["AgentVoiceUpdate"], "voice"> & { voice: VoiceRef | null },
): Promise<AgentVoice> {
  return api<AgentVoice>("/api/settings/agent-voice", { method: "PUT", body: JSON.stringify(body) });
}

/** 听写:一小段录音换成文字(免提对话、输入框的麦克风键)。 */
export function dictate(clip: Blob): Promise<{ text?: string }> {
  const body = new FormData();
  body.append("clip", clip, "clip.webm");
  return api<{ text?: string }>("/api/asr/dictate", { method: "POST", body });
}
