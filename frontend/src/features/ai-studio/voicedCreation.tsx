/**
 * 创作页里的**语音**和**播客**(ADR 0055)。
 *
 * 它们和图像、视频、音乐在同一个工作台里:同一个会话列表、同一条记录流(生成中的占位、停止、已停止、失败、价格脚注)、
 * 同一个底部输入框和右边「引擎参数」—— 只是输入框里写的东西、右栏里调的东西不一样。这里放的就是这些不一样的部分:
 *
 * - 模型下拉里多两组:「语音」是每个配音引擎(来自 `/tts/engines`,不进生成目录 —— 引擎仍是配音那一族的,ADR 0022 决定 2),
 *   「播客」是火山播客;
 * - 输入框:语音是一段要念的字;播客是三档 —— 改写材料、聊一个主题、照稿念(逐段的稿子编辑器);
 * - 右栏:语音是音色(带试听)、克隆引擎和权重、语速;播客是发音人 A / B(带试听)、语速;
 * - 记录:结果卡和音乐同一张(`GeneratedAudioList`:波形、真时长、下载、在素材库里打开),播客多一块「对谈稿」和「改稿再念」。
 *
 * 此前它们是「音频」页里的两张固定表单加一列「最近生成」:没有会话、没有记录,时长一律 0:00(`preload="none"`),名字露音色 id。
 */
import React from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Mic, PenLine, Plus, Trash2, Users } from "lucide-react";

import {
  CLONE_ENGINE,
  EDGE_ENGINE,
  PODCAST_ENGINE,
  fetchVoicePreview,
  getAsset,
  listTtsEngines,
  listTtsVoices,
  type GenerationJob,
  type PodcastCreate,
  type SpeechCreate,
  type TtsEngineChoice,
} from "@/api/client";
import { assetKeys, voiceKeys } from "@/api/queryKeys";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { ConfigNotice, EngineNotice } from "@/components/app/ConfigNotice";
import { VoicePreviewButton } from "@/components/app/VoicePreviewButton";
import { PARAMETER_CONTROL_CLASS, PARAMETER_LABEL_CLASS, ParameterField, ParameterSection } from "@/components/generation/parameterPanel";
import { Button } from "@/components/ui/button";
import { CONTROL_HEIGHT } from "@/components/ui/control-size";
import { Skeleton } from "@/components/ui/skeleton";
import { IconButton } from "@/components/ui/icon-button";
import { OptionPicker } from "@/components/ui/option-picker";
import { segmentedItemClass, segmentedListClass } from "@/components/ui/segmented";
import { Textarea } from "@/components/ui/textarea";
import { Hint } from "@/components/ui/tooltip";
import { SpeechVoiceFields, SpeedPicker } from "@/features/voice/SpeechVoiceFields";
import { speechEngineChoices } from "@/features/voice/speechEngines";
import { runtimeState, useSpeechVoice, type SpeechVoice } from "@/features/voice/useSpeechVoice";
import type { TwoLayerName } from "@/lib/entryNames";
import { isSubmitChord } from "@/lib/shortcuts";
import { cn } from "@/lib/utils";
import {
  MAX_SCRIPT_TURNS,
  MAX_TURN_CHARS,
  otherSpeaker,
  parseScript,
  scriptFromDialogue,
  scriptProblems,
  type ScriptTurn,
} from "@/features/ai-studio/podcastScript";

export const VOICED_KINDS = ["speech", "podcast"] as const;
export type VoicedKind = (typeof VOICED_KINDS)[number];

export function isVoicedKind(kind: string | null | undefined): kind is VoicedKind {
  return kind === "speech" || kind === "podcast";
}

/** 结果是一段声音的那几种:音乐与音效,和语音、播客。 */
export function isAudibleKind(kind: string | null | undefined): boolean {
  return kind === "audio" || isVoicedKind(kind);
}

/** 念一段字最多几个字(后端 SpeechCreate.text 的上限)。 */
export const SPEECH_MAX_CHARS = 2000;

// ---------------------------------------------------------------------------------------------------------------------
// 模型下拉里的语音、播客两组
// ---------------------------------------------------------------------------------------------------------------------

/** 下拉里的一项:某个配音引擎(语音),或者火山播客(播客)。 */
export type VoicedOption = { value: string; kind: VoicedKind; engine: TtsEngineChoice };

/** 下拉里的值。和生成选项(`连接::种类::模型`)不撞:前缀写明了是哪一族。 */
export function voicedOptionValue(kind: VoicedKind, engineId: string): string {
  return `voiced::${kind}::${engineId}`;
}

export function useVoicedOptions(): { options: VoicedOption[]; loaded: boolean } {
  // 和配音面板同一个键:staleTime 不能是 Infinity —— 这里带着「本机引擎装了没有」,用户就是会去设置页装完再回来。
  const engines = useQuery({ queryKey: ["tts-engines"], queryFn: listTtsEngines, staleTime: 30_000 });
  const options = React.useMemo(() => {
    const podcast = (engines.data ?? []).find((engine) => engine.id === PODCAST_ENGINE);
    return [
      ...speechEngineChoices(engines.data).map((engine): VoicedOption => ({
        value: voicedOptionValue("speech", engine.id),
        kind: "speech",
        engine,
      })),
      ...(podcast ? [{ value: voicedOptionValue("podcast", podcast.id), kind: "podcast" as const, engine: podcast }] : []),
    ];
  }, [engines.data]);
  return { options, loaded: engines.isSuccess };
}

/**
 * 新的一条语音 / 播客会话先落在哪个引擎上:语音先 Edge(内置、免费、什么都不用配 —— 不替人挑一个要花钱的),
 * 再是第一个能用的;播客只有一个。
 */
export function defaultVoicedOption(options: readonly VoicedOption[], kind: VoicedKind): VoicedOption | null {
  const ofKind = options.filter((option) => option.kind === kind);
  return (
    ofKind.find((option) => option.engine.id === EDGE_ENGINE && option.engine.ready !== false) ??
    ofKind.find((option) => option.engine.ready !== false) ??
    ofKind[0] ??
    null
  );
}

/** 下拉里这一项怎么写:引擎名;用不了的说一句为什么(照样列出来,不藏 —— 藏起来的话配好了也找不到)。 */
export function voicedPickerEntry(option: VoicedOption, t: ReturnType<typeof useI18n>) {
  const unready = option.engine.ready === false;
  return {
    label: option.engine.label,
    description: unready ? option.engine.note || t("createEngineNotReady") : undefined,
    keywords: [option.engine.id],
  };
}

// ---------------------------------------------------------------------------------------------------------------------
// 语音:谁来念(状态在 useSpeechVoice,和剪辑台的配音面板同一份判据)
// ---------------------------------------------------------------------------------------------------------------------

/**
 * 创作页的「谁来念」:引擎由模型下拉定(这里跟着它),音色、语速接着这条会话最后一条记录用的(打开一条老会话,
 * 右栏停在上次那个音色上 —— 而不是每次都回到第一个)。
 */
export function useSpeechDraft(workspaceId: string, engineId: string | null, last: GenerationJob | null): SpeechVoice {
  const voice = useSpeechVoice(workspaceId);
  //: 这几个 setter 每次渲染都是新的(useSpeechVoice 不 memo):不放进依赖 —— 放进去的话每渲染一次就重设一次引擎,
  //: 而换引擎会清掉选好的音色(实测:右栏挑了云希,下一次渲染又回到晓晓)。
  const { setEngine, setEngineVoice, setVoiceId, setSpeed, setCloneEngine } = voice;
  const current = voice.engine;
  React.useEffect(() => {
    if (engineId && engineId !== current) setEngine(engineId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engineId, current]);
  const lastId = last?.id ?? "";
  React.useEffect(() => {
    if (!last || last.kind !== "speech" || last.provider !== engineId) return;
    const request = (last.request ?? {}) as Record<string, unknown>;
    if (last.provider === CLONE_ENGINE) setVoiceId(last.model);
    else setEngineVoice(last.model);
    if (typeof request.speed === "number") setSpeed(request.speed);
    if (typeof request.clone_engine === "string" && request.clone_engine) setCloneEngine(request.clone_engine);
    // 只在换了会话 / 那条记录变了时接一次;之后是用户自己在调
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastId, engineId]);
  return voice;
}

/** 选中的那个音色叫什么(记录上、产出的素材名里用它)。 */
function chosenVoiceLabel(voice: SpeechVoice): string {
  if (voice.engine === CLONE_ENGINE) return voice.library.find((item) => item.id === voice.voiceId)?.name ?? "";
  return voice.voiceChoices.find((item) => item.value === voice.engineVoice)?.label ?? voice.engineVoice;
}

/** 念一段字的请求(工作区、会话由调用方补)。音色一格:克隆是嗓子 id,别的是引擎自己的音色(或配音库里的嗓子 id)。 */
export function speechRequest(voice: SpeechVoice, text: string): Omit<SpeechCreate, "workspace_id" | "session_id"> {
  const { params } = voice;
  return {
    text,
    engine: params.engine,
    voice: params.voice_id ?? params.engine_voice ?? "",
    voice_label: chosenVoiceLabel(voice),
    engine_label: voice.activeEngine?.label ?? (voice.engine === CLONE_ENGINE ? voice.engines.find((one) => one.id === CLONE_ENGINE)?.label ?? "" : ""),
    engine_voice_resource: params.engine_voice_resource ?? "",
    clone_engine: params.clone_engine ?? "",
    ...(params.speed !== undefined ? { speed: params.speed } : {}),
  };
}

/** 这一段念得出来吗:有字、不超长、谁来念定好了(克隆要有音色且引擎装好,远端要有音色)、引擎能用。 */
export function speechReady(voice: SpeechVoice, text: string): boolean {
  return Boolean(text.trim()) && text.length <= SPEECH_MAX_CHARS && voice.ready && voice.activeEngine?.ready !== false;
}

/** 右栏「音色」那一块。没配好的情况用和「还没有可用的生成模型」同一种提示条说,带去处。 */
export function SpeechSettings({ voice, workspaceId }: { voice: SpeechVoice; workspaceId: string }) {
  const t = useI18n();
  const clone = voice.engine === CLONE_ENGINE;
  const noLibrary = clone && voice.libraryLoaded && voice.library.length === 0;
  const cloneUnready = clone && runtimeState(voice.cloneRuntime) === "unready";
  const engineUnready = !clone && voice.activeEngine?.ready === false;
  const previewVoice = clone ? voice.voiceId : voice.engineVoice;
  return (
    <ParameterSection icon={Mic} title={t("createSectionVoice")}>
      {noLibrary && (
        <ConfigNotice message={t("audioCloneNeedsVoice")} actionLabel={t("audioManageVoices")} section="dubbing" />
      )}
      {cloneUnready && <EngineNotice message={t("createCloneNotInstalled")} />}
      {engineUnready && (
        <ConfigNotice
          message={voice.activeEngine?.note || t("createEngineNotReady")}
          actionLabel={t("wfGoConfigure")}
          section="provider-audio"
        />
      )}
      {/* 试听键贴在音色右边、和它同高(和播客的发音人一个摆法);语速自成一行 —— 窄栏里三样挤一行,音色名就只剩半截 */}
      <div data-speech-voice="" className="grid gap-3">
        <SpeechVoiceFields
          voice={voice}
          hideEngine
          speedOwnRow
          labelClassName={PARAMETER_LABEL_CLASS}
          voiceAction={
            <VoicePreviewButton
              load={() =>
                fetchVoicePreview({ workspace_id: workspaceId, engine: voice.engine, voice: previewVoice, text: t("createVoicePreviewText") })
              }
              disabled={!previewVoice || engineUnready}
              disabledReason={t("createPickVoiceFirst")}
            />
          }
        />
      </div>
    </ParameterSection>
  );
}

/** 输入框里那一格:要念的字。⌘Enter 交,回车换行(和生成同一个键)。 */
export function SpeechComposerField({
  value,
  onChange,
  onSubmit,
  composer,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (event: React.FormEvent) => void;
  composer: React.RefObject<HTMLTextAreaElement | null>;
}) {
  const t = useI18n();
  return (
    <Textarea
      ref={composer}
      rows={3}
      className="max-h-[220px] min-h-11 w-full min-w-0 resize-none border-0 bg-transparent px-0 py-0.5 pb-1.5 text-ui-md leading-[1.55] shadow-none outline-none focus-visible:ring-0"
      value={value}
      aria-label={t("createSpeechLabel")}
      placeholder={t("createSpeechPlaceholder")}
      onChange={(event) => {
        onChange(event.target.value);
        event.target.style.height = "auto";
        event.target.style.height = `${Math.min(event.target.scrollHeight, 220)}px`;
      }}
      onKeyDown={(event) => {
        if (isSubmitChord(event)) {
          event.preventDefault();
          onSubmit(event);
        }
      }}
    />
  );
}

// ---------------------------------------------------------------------------------------------------------------------
// 播客
// ---------------------------------------------------------------------------------------------------------------------

export const PODCAST_MODES = ["summarize", "research", "read"] as const;
export type PodcastMode = (typeof PODCAST_MODES)[number];

const PODCAST_MODE_LABELS: Record<PodcastMode, MessageKey> = {
  summarize: "createPodcastModeSummarize",
  research: "createPodcastModeResearch",
  read: "createPodcastModeRead",
};

/** 播客这一次的稿子和发音人。材料 / 主题用输入框那一份(和语音、生成同一个 `prompt`),这里只放播客自己的。
 *  发音人、语速接着这条会话最后一条播客记录用的(`last`)。 */
export function usePodcastDraft(enabled: boolean, last: GenerationJob | null) {
  const [mode, setMode] = React.useState<PodcastMode>("summarize");
  const [turns, setTurns] = React.useState<ScriptTurn[]>([{ speaker: 0, text: "" }]);
  const [picked, setPicked] = React.useState<[string, string]>(["", ""]);
  const [speed, setSpeed] = React.useState(1);
  //: 发音人跟着账号现拉(火山);播客那一项在下拉里时才问。
  const voices = useQuery({
    queryKey: voiceKeys.engineVoices(PODCAST_ENGINE),
    queryFn: () => listTtsVoices(PODCAST_ENGINE),
    enabled,
  });
  const choices = React.useMemo(() => voices.data ?? [], [voices.data]);
  const lastId = last?.id ?? "";
  React.useEffect(() => {
    if (!last || last.kind !== "podcast") return;
    const request = (last.request ?? {}) as Record<string, unknown>;
    const values = speakersOf(request).map((one) => one.value);
    if (values[0]) setPicked([values[0], values[1] ?? ""]);
    if (typeof request.speed === "number") setSpeed(request.speed);
    // 只在换了会话 / 那条记录变了时接一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastId]);
  // 下拉没选时**显示**的是第一 / 第二位,那就交同样的。
  const pair: [string, string] = [picked[0] || choices[0]?.value || "", picked[1] || choices[1]?.value || ""];
  const labelOf = React.useCallback((value: string) => choices.find((one) => one.value === value)?.label ?? value, [choices]);
  const setSpeaker = (index: 0 | 1, value: string) =>
    setPicked((current) => (index === 0 ? [value, current[1]] : [current[0], value]));
  /** 「改稿再念」:那一份对谈稿装进照稿念,发音人换成那一次的两位。 */
  const rescript = (next: ScriptTurn[], speakers: readonly string[]) => {
    setMode("read");
    setTurns(next.length > 0 ? next : [{ speaker: 0, text: "" }]);
    if (speakers[0]) setPicked([speakers[0], speakers[1] ?? ""]);
  };
  return { mode, setMode, turns, setTurns, pair, setSpeaker, choices, labelOf, speed, setSpeed, rescript };
}
export type PodcastDraft = ReturnType<typeof usePodcastDraft>;

/** 这一次交得出去吗。照稿念看稿子;改写、讨论要两位不同的发音人和一段字。 */
export function podcastReady(draft: PodcastDraft, text: string, engine: TtsEngineChoice | undefined): boolean {
  if (engine?.ready === false) return false;
  if (draft.mode === "read") {
    const problems = scriptProblems(draft.turns);
    return !problems.empty && !problems.tooMany && problems.tooLong.length === 0 && Boolean(draft.pair[0]);
  }
  return Boolean(text.trim()) && Boolean(draft.pair[0] && draft.pair[1]) && draft.pair[0] !== draft.pair[1];
}

export function podcastRequest(draft: PodcastDraft, text: string): Omit<PodcastCreate, "workspace_id" | "session_id"> {
  const speakers = draft.pair.filter(Boolean).map((value) => ({ value, label: draft.labelOf(value) }));
  if (draft.mode === "read") {
    return {
      mode: "read",
      turns: draft.turns.filter((turn) => turn.text.trim()).map((turn) => ({ speaker: turn.speaker, text: turn.text.trim() })),
      speakers,
      speed: draft.speed,
    };
  }
  return { mode: draft.mode, text, speakers, speed: draft.speed };
}

/** 输入框里的播客:顶上三档,下面跟着换(材料 / 主题 / 逐段的稿子)。 */
export function PodcastComposerFields({
  draft,
  text,
  setText,
  onSubmit,
  composer,
}: {
  draft: PodcastDraft;
  text: string;
  setText: (value: string) => void;
  onSubmit: (event: React.FormEvent) => void;
  composer: React.RefObject<HTMLTextAreaElement | null>;
}) {
  const t = useI18n();
  const onKeyDown = (event: React.KeyboardEvent) => {
    if (isSubmitChord(event)) {
      event.preventDefault();
      onSubmit(event);
    }
  };
  return (
    <div className="grid gap-2" data-podcast-composer={draft.mode}>
      <div className={cn(segmentedListClass("sm"), "justify-self-start")} role="tablist" aria-label={t("createPodcastModeLabel")}>
        {PODCAST_MODES.map((mode) => (
          <button
            key={mode}
            type="button"
            role="tab"
            aria-selected={draft.mode === mode}
            className={segmentedItemClass(draft.mode === mode, "sm")}
            onClick={() => draft.setMode(mode)}
          >
            {t(PODCAST_MODE_LABELS[mode])}
          </button>
        ))}
      </div>
      {draft.mode === "read" ? (
        <ScriptEditor draft={draft} onSubmitChord={onKeyDown} />
      ) : (
        <Textarea
          ref={composer}
          rows={draft.mode === "research" ? 2 : 4}
          className="max-h-[260px] min-h-11 w-full min-w-0 resize-none border-0 bg-transparent px-0 py-0.5 pb-1.5 text-ui-md leading-[1.55] shadow-none outline-none focus-visible:ring-0"
          value={text}
          aria-label={t(draft.mode === "research" ? "createPodcastTopicLabel" : "createPodcastMaterialLabel")}
          placeholder={t(draft.mode === "research" ? "createPodcastTopicPlaceholder" : "createPodcastMaterialPlaceholder")}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onKeyDown}
        />
      )}
    </div>
  );
}

/**
 * 照稿念的编辑器:一段一行。左边 A / B 换发音人,右边这一段念什么。回车接下一段(换另一位念),在空的一段上退格删掉它;
 * 粘一大段多行的字自动拆成几段(认得 `A:` / `B:` 和发音人的名字)。每段超过 280 字标红、超过 60 段说出来 —— 都是接口的上限。
 */
function ScriptEditor({ draft, onSubmitChord }: { draft: PodcastDraft; onSubmitChord: (event: React.KeyboardEvent) => void }) {
  const t = useI18n();
  const { turns, setTurns } = draft;
  const rows = React.useRef<(HTMLTextAreaElement | null)[]>([]);
  const [focusAt, setFocusAt] = React.useState<number | null>(null);
  React.useEffect(() => {
    if (focusAt === null) return;
    rows.current[focusAt]?.focus();
    setFocusAt(null);
  }, [focusAt]);
  const names = [draft.labelOf(draft.pair[0]), draft.labelOf(draft.pair[1])] as const;
  const problems = scriptProblems(turns);
  const update = (index: number, patch: Partial<ScriptTurn>) =>
    setTurns(turns.map((turn, at) => (at === index ? { ...turn, ...patch } : turn)));
  const insertAfter = (index: number, added: ScriptTurn[]) => {
    setTurns([...turns.slice(0, index + 1), ...added, ...turns.slice(index + 1)]);
    setFocusAt(index + added.length);
  };
  const remove = (index: number) => {
    const next = turns.filter((_, at) => at !== index);
    setTurns(next.length > 0 ? next : [{ speaker: 0, text: "" }]);
    setFocusAt(Math.max(0, index - 1));
  };
  const full = turns.length >= MAX_SCRIPT_TURNS;
  return (
    <div className="grid gap-1.5" data-script-editor="">
      <ol className="m-0 grid max-h-[300px] list-none gap-1 overflow-y-auto p-0">
        {turns.map((turn, index) => {
          const tooLong = problems.tooLong.includes(index);
          const name = names[turn.speaker] || (turn.speaker === 0 ? "A" : "B");
          return (
            <li key={index} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-1.5" data-script-turn={turn.speaker}>
              <Hint label={t("createScriptSwitchSpeaker").replace("{name}", names[otherSpeaker(turn.speaker)] || "")}>
                <button
                  type="button"
                  className={cn(
                    "mt-0.5 inline-flex h-6 min-w-6 cursor-pointer items-center justify-center rounded-md border px-1.5 text-ui-2xs font-semibold",
                    turn.speaker === 0
                      ? "border-[color-mix(in_srgb,var(--primary)_40%,transparent)] bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] text-primary"
                      : "border-[color-mix(in_srgb,var(--warning)_45%,transparent)] bg-[color-mix(in_srgb,var(--warning)_12%,transparent)] text-warning",
                  )}
                  aria-label={t("createScriptSpeakerOf").replace("{n}", String(index + 1)).replace("{name}", name)}
                  onClick={() => update(index, { speaker: otherSpeaker(turn.speaker) })}
                >
                  {turn.speaker === 0 ? "A" : "B"}
                </button>
              </Hint>
              <Textarea
                ref={(node) => {
                  rows.current[index] = node;
                }}
                rows={1}
                value={turn.text}
                aria-label={t("createScriptTurnLabel").replace("{n}", String(index + 1))}
                aria-invalid={tooLong || undefined}
                placeholder={index === 0 ? t("createScriptFirstPlaceholder") : t("createScriptTurnPlaceholder")}
                className={cn(
                  "min-h-7 resize-none border-0 bg-transparent px-1 py-0.5 text-ui-sm leading-[1.55] shadow-none focus-visible:ring-0 field-sizing-content",
                  tooLong && "text-destructive",
                )}
                onChange={(event) => update(index, { text: event.target.value })}
                onPaste={(event) => {
                  const pasted = event.clipboardData.getData("text");
                  if (!/\r?\n/.test(pasted.trim())) return;
                  event.preventDefault();
                  const parsed = parseScript(pasted, names, turn.speaker);
                  if (parsed.length === 0) return;
                  //: 粘在一段空的上:第一段就落在这一段;粘在有字的一段上:接在它后面
                  if (!turn.text.trim()) {
                    setTurns([...turns.slice(0, index), ...parsed, ...turns.slice(index + 1)]);
                    setFocusAt(index + parsed.length - 1);
                  } else {
                    insertAfter(index, parsed);
                  }
                }}
                onKeyDown={(event) => {
                  if (isSubmitChord(event)) return onSubmitChord(event);
                  if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                    event.preventDefault();
                    if (!full) insertAfter(index, [{ speaker: otherSpeaker(turn.speaker), text: "" }]);
                  } else if (event.key === "Backspace" && !turn.text && turns.length > 1) {
                    event.preventDefault();
                    remove(index);
                  }
                }}
              />
              <span className="flex items-center">
                {tooLong && (
                  <span className="mt-1 text-ui-2xs tabular-nums text-destructive" aria-live="polite">
                    {turn.text.trim().length}/{MAX_TURN_CHARS}
                  </span>
                )}
                <IconButton
                  variant="ghost"
                  size="icon-xs"
                  className="text-muted-foreground"
                  label={t("createScriptRemoveTurn")}
                  onClick={() => remove(index)}
                >
                  <Trash2 size={12} />
                </IconButton>
              </span>
            </li>
          );
        })}
      </ol>
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="xs"
          className="text-muted-foreground"
          disabled={full}
          onClick={() => insertAfter(turns.length - 1, [{ speaker: otherSpeaker(turns[turns.length - 1]?.speaker ?? 1), text: "" }])}
        >
          <Plus size={12} />
          {t("createScriptAddTurn")}
        </Button>
        <span className={cn("text-ui-2xs text-muted-foreground", problems.tooLong.length > 0 && "text-destructive")}>
          {problems.tooLong.length > 0 ? t("createScriptTooLong").replace("{max}", String(MAX_TURN_CHARS)) : t("createScriptHint")}
        </span>
      </div>
    </div>
  );
}

/** 输入框底栏右边那个数:语音是字数 / 上限,照稿念是段数 / 上限。 */
export function voicedCount(kind: VoicedKind, text: string, draft: PodcastDraft, t: ReturnType<typeof useI18n>): { label: string; over: boolean } | null {
  if (kind === "speech") {
    if (!text) return null;
    return {
      label: t("createSpeechCount").replace("{n}", String(text.length)).replace("{max}", String(SPEECH_MAX_CHARS)),
      over: text.length > SPEECH_MAX_CHARS,
    };
  }
  if (draft.mode !== "read") return null;
  const filled = draft.turns.filter((turn) => turn.text.trim()).length;
  return {
    label: t("createScriptTurns").replace("{n}", String(filled)).replace("{max}", String(MAX_SCRIPT_TURNS)),
    over: filled > MAX_SCRIPT_TURNS,
  };
}

/** 右栏「发音人」那一块:A、B 各一个下拉,各带试听;语速。没配好播客连接时说去哪配。 */
export function PodcastSettings({
  draft,
  engine,
  workspaceId,
}: {
  draft: PodcastDraft;
  engine: TtsEngineChoice | undefined;
  workspaceId: string;
}) {
  const t = useI18n();
  const unready = engine?.ready === false;
  const speakerRow = (index: 0 | 1) => (
    <ParameterField label={t(index === 0 ? "voicePodcastSpeakerA" : "voicePodcastSpeakerB")}>
      <span className="flex min-w-0 items-center gap-1.5">
        <OptionPicker
          value={draft.pair[index]}
          onChange={(value) => draft.setSpeaker(index, value)}
          options={draft.choices}
          ariaLabel={t(index === 0 ? "voicePodcastSpeakerA" : "voicePodcastSpeakerB")}
          className={PARAMETER_CONTROL_CLASS}
        />
        <VoicePreviewButton
          load={() =>
            fetchVoicePreview({ workspace_id: workspaceId, engine: PODCAST_ENGINE, voice: draft.pair[index], text: t("createVoicePreviewText") })
          }
          disabled={!draft.pair[index] || unready}
          disabledReason={t("createPickVoiceFirst")}
        />
      </span>
    </ParameterField>
  );
  return (
    <ParameterSection icon={Users} title={t("createSectionSpeakers")}>
      {unready && (
        <ConfigNotice message={engine?.note || t("audioPodcastUnavailable")} actionLabel={t("audioConfigurePodcast")} section="provider-audio" />
      )}
      {draft.choices.length > 0 && speakerRow(0)}
      {draft.choices.length > 0 && speakerRow(1)}
      {draft.mode !== "read" && draft.pair[0] && draft.pair[0] === draft.pair[1] && (
        <p className="m-0 text-ui-xs leading-[1.45] text-destructive">{t("voicePodcastNeedTwo")}</p>
      )}
      <ParameterField label={t("voiceSpeed")}>
        <SpeedPicker value={draft.speed} onChange={draft.setSpeed} ariaLabel={t("voiceSpeed")} />
      </ParameterField>
    </ParameterSection>
  );
}

// ---------------------------------------------------------------------------------------------------------------------
// 记录流里的语音、播客
// ---------------------------------------------------------------------------------------------------------------------

type RequestOf = Record<string, unknown>;

function speakersOf(request: RequestOf): { value: string; label: string }[] {
  return Array.isArray(request.speakers)
    ? request.speakers.filter((one): one is { value: string; label?: string } => Boolean(one && typeof one === "object" && "value" in one))
        .map((one) => ({ value: String(one.value), label: String(one.label ?? "") }))
    : [];
}

/** 记录上的音色叫什么:记着的名字 → 现在引擎目录里的名字 → 音色 id(老版本迁过来的没记名字)。 */
export function voicedTitle(generation: GenerationJob, voiceLabels: ReadonlyMap<string, string>): string {
  const request = (generation.request ?? {}) as RequestOf;
  if (generation.kind === "speech") {
    return String(request.voice_label ?? "").trim() || voiceLabels.get(generation.model) || generation.model;
  }
  const subject = String(request.prompt ?? "").trim().split("\n")[0] || firstTurn(request);
  return subject.slice(0, 60);
}

function firstTurn(request: RequestOf): string {
  const turns = Array.isArray(request.turns) ? (request.turns as { text?: unknown }[]) : [];
  return String(turns[0]?.text ?? "");
}

/** 记录的那个气泡里写什么:语音是念的字;播客是材料 / 主题,照稿念的是一段一行、标着谁念。 */
export function voicedBubbleText(generation: GenerationJob, labelOf: (value: string) => string): string {
  const request = (generation.request ?? {}) as RequestOf;
  const prompt = String(request.prompt ?? "").trim();
  if (generation.kind === "speech" || prompt) return prompt;
  const speakers = speakersOf(request);
  const turns = Array.isArray(request.turns) ? (request.turns as { speaker?: unknown; text?: unknown }[]) : [];
  return turns
    .map((turn) => {
      const index = turn.speaker === 1 ? 1 : 0;
      const who = speakers[index]?.label || labelOf(speakers[index]?.value ?? "") || (index === 0 ? "A" : "B");
      return `${who}:${String(turn.text ?? "")}`;
    })
    .join("\n");
}

/** 脚注里的引擎名:现在目录里的名字 → 记录上记着的 → 引擎 id。副名写音色(播客写「播客」)。 */
export function voicedEngineName(generation: GenerationJob, options: readonly VoicedOption[], t: ReturnType<typeof useI18n>): TwoLayerName {
  const request = (generation.request ?? {}) as RequestOf;
  const known = options.find((option) => option.engine.id === generation.provider)?.engine.label;
  return {
    primary: known || String(request.engine_label ?? "").trim() || generation.provider,
    secondary: generation.kind === "podcast" ? t("createKindPodcast") : String(request.voice_label ?? "").trim(),
  };
}

/** 这条记录的文字只剩开头(老版本只存了前一段,ADR 0055 §8):气泡下说一句。 */
export function TruncatedNote({ generation }: { generation: GenerationJob }) {
  const t = useI18n();
  if (!(generation.request as RequestOf | undefined)?.truncated) return null;
  return <span className="text-ui-2xs text-muted-foreground">{t("createTruncated")}</span>;
}

/**
 * 播客结果卡下面那一块:对谈稿(按发音人分色,收着),和「改稿再念」—— 把这份稿子装进「照稿念」,改完再念一遍,
 * 这一次只花合成的钱。稿子读素材自己的 `media_info.dialogue`(任务清掉了也还在)。
 */
export function PodcastDialogue({
  assetId,
  generation,
  onRescript,
}: {
  assetId: string;
  generation: GenerationJob;
  onRescript?: (turns: ScriptTurn[], speakers: string[]) => void;
}) {
  const t = useI18n();
  const asset = useQuery({ queryKey: assetKeys.detail(assetId), queryFn: () => getAsset(assetId), staleTime: 60_000 });
  //: 老版本迁过来的没记发音人的名字:从播客的发音人目录里认(和右栏同一个查询,有缓存)
  const catalog = useQuery({
    queryKey: voiceKeys.engineVoices(PODCAST_ENGINE),
    queryFn: () => listTtsVoices(PODCAST_ENGINE),
    staleTime: 60_000,
  });
  const info = (asset.data?.media_info ?? {}) as Record<string, unknown>;
  const dialogue = Array.isArray(info.dialogue)
    ? (info.dialogue as { speaker?: unknown; text?: unknown }[]).map((line) => ({ speaker: String(line.speaker ?? ""), text: String(line.text ?? "") }))
    : [];
  const request = (generation.request ?? {}) as RequestOf;
  const speakers = speakersOf(request).map((one) => one.value);
  const fromInfo = Array.isArray(info.speakers)
    ? (info.speakers as { value?: unknown; label?: unknown }[]).map((one) => ({ value: String(one.value ?? ""), label: String(one.label ?? "") }))
    : [];
  const order = speakers.length > 0 ? speakers : fromInfo.map((one) => one.value);
  const labelOf = (value: string) =>
    speakersOf(request).find((one) => one.value === value)?.label ||
    fromInfo.find((one) => one.value === value)?.label ||
    catalog.data?.find((one) => one.value === value)?.label ||
    value;
  const [open, setOpen] = React.useState(false);
  //: 素材还没到:先占住对谈稿那一行(和会话首次加载的骨架同一个壳),到了原地换上,版面不跳
  if (asset.isPending) return <PodcastDialogueSkeleton />;
  if (dialogue.length === 0) return null;
  return (
    <div className={DIALOGUE_BLOCK_CLASS} data-podcast-dialogue="">
      <div className={DIALOGUE_ROW_CLASS}>
        <Button variant="ghost" size="xs" className="text-muted-foreground" aria-expanded={open} onClick={() => setOpen(!open)}>
          <ChevronDown size={12} className={cn("transition-transform duration-100", !open && "-rotate-90")} />
          {t("createDialogueShow").replace("{n}", String(dialogue.length))}
        </Button>
        {onRescript && (
          <Hint label={t("createRescriptHint")}>
            <Button variant="outline" size="xs" onClick={() => onRescript(scriptFromDialogue(dialogue, order), order)}>
              <PenLine size={12} />
              {t("createRescript")}
            </Button>
          </Hint>
        )}
      </div>
      {open && (
        <ol className="m-0 grid list-none gap-1 rounded-lg border border-border bg-card p-2.5 text-ui-sm leading-[1.6]">
          {dialogue.map((line, index) => {
            const second = order.indexOf(line.speaker) === 1;
            return (
              <li key={index} className="grid grid-cols-[auto_minmax(0,1fr)] gap-2">
                <span className={cn("shrink-0 text-ui-xs font-semibold", second ? "text-warning" : "text-primary")}>
                  {labelOf(line.speaker)}
                </span>
                <span className="whitespace-pre-wrap break-words text-foreground">{line.text}</span>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}

/** 对谈稿那一块和它的按钮行(PodcastDialogue 与它的骨架共用)。 */
const DIALOGUE_BLOCK_CLASS = "grid w-full max-w-[min(560px,100%)] gap-1.5";
const DIALOGUE_ROW_CLASS = "flex items-center gap-1.5";

/** 对谈稿那一行还没到时的样子:同一个壳,按钮那么高(xs 档)的一条扫光。 */
export function PodcastDialogueSkeleton() {
  return (
    <div className={DIALOGUE_BLOCK_CLASS} data-podcast-dialogue-skeleton="" aria-hidden>
      <div className={DIALOGUE_ROW_CLASS}>
        <Skeleton className={cn(CONTROL_HEIGHT.xs, "w-32")} />
      </div>
    </div>
  );
}

/** 当前这条语音会话的音色目录里的名字(老记录没记名字时,标题从这里认)。只在有语音记录时问。 */
export function useVoiceLabels(workspaceId: string, engines: readonly string[]): ReadonlyMap<string, string> {
  const engine = engines.find((one) => one && one !== CLONE_ENGINE) ?? "";
  const voices = useQuery({
    queryKey: voiceKeys.engineVoices(engine, workspaceId),
    queryFn: () => listTtsVoices(engine, workspaceId),
    enabled: Boolean(engine),
    staleTime: 60_000,
  });
  return React.useMemo(() => new Map((voices.data ?? []).map((one) => [one.value, one.label])), [voices.data]);
}

