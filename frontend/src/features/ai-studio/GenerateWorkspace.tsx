import { assetKeys } from "@/api/queryKeys";
import React from "react";
import { StudioIndex } from "@/components/layout/StudioIndex";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownLeft,
  ClipboardList,
  Clock3,
  Cpu,
  Eye,
  Film,
  Image as ImageIcon,
  Images,
  Music,
  Ratio,
  SlidersHorizontal,
  CircleAlert,
  Loader2,
  Send,
  Sparkles,
  Square,
  TriangleAlert,
  Wand2,
  X,
} from "lucide-react";
import { toast } from "sonner";

import {
  api,
  assetFileUrl,
  createPodcast,
  createSpeech,
  assetPreviewUrl,
  assetThumbnailUrl,
  cancelJob,
  entityReceipt,
  listJobs,
  optimizeImagePrompt,
  repeatGeneration,
  retrieveGeneration,
  type EntitySummary,
  type GenerationCreateResponse,
  type GenerationJob,
  type GenerationOption,
  type JobSummary,
  type Workspace,
} from "@/api/client";
import { jobSettled } from "@/components/jobs/runStatus";
import type { components } from "@/api/generated/schema";
import { errorText } from "@/api/errorMessage";
import { MissingModelNotice, UpgradeInLibraryButton } from "@/features/plugins/MissingModelNotice";
import { GenerationFailureCard, GenerationStoppedCard } from "@/features/ai-studio/GenerationFailureCard";
import { OpenInWorkbench } from "@/features/plugins/workbench/OpenInWorkbench";
import { JumpToLatest, useStickToBottom } from "@/features/agent/stickToBottom";
import { IconButton } from "@/components/ui/icon-button";
import { Skeleton, SkeletonLine } from "@/components/ui/skeleton";
import { useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { EntityMentionButton, entityMentionChips } from "@/features/entities/EntityMention";
import { ComposerChips } from "@/features/agent/ComposerChips";
import { PromptTemplateButton, withTemplate } from "@/components/app/PromptTemplates";
import { EntityReceiptNote } from "@/features/entities/entityMeta";
import { EmptyState } from "@/components/layout/EmptyState";
import { ConfigNotice } from "@/components/app/ConfigNotice";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { useImagePreview, type ImagePreviewItem } from "@/components/app/image-preview";
import { VideoPlayer } from "@/components/app/media-playback";
import { useEffectiveChatModel } from "@/features/agent/effectiveModel";
import {
  DeclaredParameterControl,
  PARAMETER_CONTROL_CLASS,
  ParameterField,
  ParameterSection,
} from "@/components/generation/parameterPanel";
import { CustomSizePicker } from "@/components/generation/CustomSizePicker";
import {
  formedGroups,
  generationOptionNames,
  generationPickerEntry,
  missingModelLabel,
  missingModelNames,
  twoLayerTitle,
  type TwoLayerName,
} from "@/lib/entryNames";
import { useGenerationOptions, useMissingModel } from "@/lib/generationOptions";
import { formatCombo, isSubmitChord, SUBMIT_COMBO } from "@/lib/shortcuts";
import { elapsedSecondsBetween, formatElapsedSeconds, parseServerTime, useNow } from "@/lib/time";
import { MessageFooter, MessageTime } from "@/features/agent/messageUsage";
import { formatCosts } from "@/lib/money";
import {
  appForm,
  aspectRatioOptions,
  booleanParameterKeys,
  capabilityBoolean,
  capabilityString,
  chooseGenerationOption,
  declaredParameters,
  declaredParameterValue,
  defaultDuration,
  DURATION_UNSET,
  durationOptions,
  durationRange,
  durationChoices,
  sizeOptions,
  customSizeRule,
  countsRuns,
  maxImages,
  outputsPerRun,
  parameterChoiceEntries,
  pickGenerationOption,
  runsHint,
  supportsParameter,
  sourceLabels,
  sourceLimit,
  exclusiveSourceGroups,
  hasEnoughText,
  promptDefault,
  promptMode,
  promptToSend,
  videoResolutionOptions,
  withTriggerWords,
  type AppForm,
  type AppFormItem,
  type DeclaredParameter,
} from "@/lib/generationCapabilities";
import { ModelFilePicker } from "@/components/generation/ModelFilePicker";
import { GENERATION_BOOLEAN_LABELS, GENERATION_PARAMETER_HINTS, GENERATION_PARAMETER_LABELS, generationParameterLabel } from "@/lib/generationParameterLabels";
import { FrameSlotField, KeyframePairField } from "@/features/ai-studio/FrameSlotField";
import { DurationFollowsNote, TruncationHint, durationFollowsRole } from "@/features/ai-studio/durationFollows";
import { DigitalHumanConsent } from "@/components/generation/DigitalHumanConsent";
import {
  AUDIO_SOURCE_HINTS,
  GeneratedAudioList,
  LyricsField,
  PendingAudioList,
  audioSourceRoles,
  lyricsLimit,
} from "@/features/ai-studio/audioGeneration";
import { SessionList } from "@/features/ai-studio/SessionList";
import { GenerationModelGate } from "@/features/ai-studio/GenerationModelGate";
import { AI_PANEL_BOUNDS } from "@/features/ai-studio/ChatWorkspace";
import { takeGenerationHandoff } from "@/lib/generationHandoff";
import {
  CREATE_FILTERS,
  CREATE_FILTER_KEY,
  CREATION_FILTER_EVENT,
  OPEN_CREATION_SESSION_EVENT,
  creationSessionKey,
  isCreateFilter,
  type CreateFilter,
} from "@/lib/aiStudioLink";
import { useOpenRequest } from "@/lib/deepLink";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { isConsentDeclined, withRemoteVoiceConsent } from "@/features/voice/remoteVoiceConsent";
import { CreateFilterRow, KindBadge, emptySessionsKey, familyKinds, generationKindOf } from "@/features/ai-studio/createFilter";
import {
  PodcastComposerFields,
  PodcastDialogue,
  PodcastDialogueSkeleton,
  PodcastSettings,
  SpeechComposerField,
  SpeechSettings,
  TruncatedNote,
  defaultVoicedOption,
  isAudibleKind,
  isVoicedKind,
  podcastReady,
  podcastRequest,
  speechReady,
  speechRequest,
  useVoiceLabels,
  useSpeechDraft,
  usePodcastDraft,
  useVoicedOptions,
  voicedBubbleText,
  voicedCount,
  voicedEngineName,
  voicedPickerEntry,
  voicedTitle,
  type VoicedOption,
} from "@/features/ai-studio/voicedCreation";
import type { ScriptTurn } from "@/features/ai-studio/podcastScript";
import { useMediaMatch } from "@/lib/useMediaMatch";
import { SIDEBAR_HANDLE_CLASS, handleOffset, useSidePanels } from "@/lib/useResizableSidebar";
import {
  EMPTY_SLOT,
  emptyFrames,
  filledCount,
  SOURCE_ROLES,
  frameUrlParameters,
  sourceAssetsFrom,
  type FrameSlot,
  type SourceRole,
  type FrameSlots,
} from "@/lib/sourceFrames";
import { cn } from "@/lib/utils";
import { toPlainText } from "@/components/markdown/inlineSyntax";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";

type GenerationSession = components["schemas"]["GenerationSessionOut"];

const ENGINE_SEP = "::";

type GenerationConfig = {
  size: string;
  numImages: string;
  seed: string;
  negativePrompt: string;
  durationSeconds: string;
  generateAudio: boolean;
  booleanParameters: Record<string, boolean>;
  enumParameters: Record<string, string>;
  resolution: string;
  aspectRatio: string;
  /** 带角色的输入素材:首帧 / 尾帧 / 参考图。它们是同一种东西,差的只是用途。 */
  frames: FrameSlots;
  usePreviousImage: boolean;
  /** 模型自己声明的参数(`parameter_schema`)里**用户动过的**那些,存控件里的原文。没动过的不发。 */
  declared: Record<string, string>;
  /** 音频:歌词(和提示词分开的一段长文字)与纯音乐开关。见 audioGeneration.tsx。 */
  lyrics: string;
  instrumental: boolean;
};

/** 有专属控件的布尔参数 —— 不再进「调参」那一串通用开关里,免得同一个开关出现两次。 */
const DEDICATED_BOOLEANS = new Set(["generate_audio", "instrumental"]);

/** 三种「拿现成的东西当输入」各自说清自己是干什么的 —— 光看名字分不出编辑和续写的区别。 */
const VIDEO_INPUT_HINTS = {
  source_video: "genSourceVideoHint",
  first_clip: "genFirstClipHint",
  driving_audio: "genDrivingAudioHint",
} as const;

/** 选项**由后端联接好**(/generation/options),前端只补一个用于下拉的 value。
 *  以前这里拿生成目录 / 启用档案 / 能力默认三张表在浏览器里做交叉连接,三份口径任何一份
 *  变一点,拼出来的就和设置页对不上 —— 有的模型只在目录里、设置页加的模型进不来,
 *  都是这么来的。 */
type GenerationEngineOption = GenerationOption & { value: string };

function defaultGenerationConfig(model: GenerationOption | null): GenerationConfig {
  const sizes = sizeOptions(model);
  const resolutions = videoResolutionOptions(model);
  const ratios = aspectRatioOptions(model);
  // 音频的时长**可以不给**(多数音乐模型按歌词长短自己定曲长):只认模型**声明了**的默认值,
  // 没声明就空着、空着就不发 —— 不能像视频那样取区间的第一档(Suno 会被悄悄定成 10 秒)。
  // 视频同理:模型既没声明默认值也没给档位时 defaultDuration 回 DURATION_UNSET(0),那就空着 ——
  // 框里摆个 0 再原样发出去,等于替用户选了「0 秒」(和画板 NodeComposer 同一条,见 ADR 0015)。
  const declaredDuration = model?.capabilities?.default_duration_seconds;
  const videoDuration = defaultDuration(model);
  const duration =
    model?.kind === "audio"
      ? typeof declaredDuration === "number" ? String(declaredDuration) : ""
      : videoDuration === DURATION_UNSET ? "" : String(videoDuration);
  return {
    size: capabilityString(model, "default_size", sizes[0] ?? ""),
    numImages: "1",
    seed: "",
    negativePrompt: "",
    durationSeconds: duration,
    generateAudio: capabilityBoolean(model, "default_generate_audio"),
    booleanParameters: Object.fromEntries(
      booleanParameterKeys(model)
        .filter((key) => !DEDICATED_BOOLEANS.has(key))
        .map((key) => [key, capabilityBoolean(model, `default_${key}`)]),
    ),
    enumParameters: Object.fromEntries(
      parameterChoiceEntries(model).map(([key, choices]) => [
        key,
        capabilityString(model, `default_${key}`, choices[0] ?? ""),
      ]),
    ),
    resolution: capabilityString(model, "default_resolution", resolutions[0] ?? ""),
    aspectRatio: capabilityString(model, "default_aspect_ratio", ratios[0] ?? ""),
    frames: emptyFrames(),
    // **默认不带参考图**。此前默认 true,于是每次生成都会悄悄把上一张结果当参考图喂进去 ——
    // 用户输入一句全新的提示词,出来的图却还带着上一张的人和构图,而参考图那一栏他从没碰过。
    // 想接着上一张改的时候,右栏有「用上一张结果」一键设上。
    usePreviousImage: false,
    declared: {},
    lyrics: "",
    instrumental: capabilityBoolean(model, "default_instrumental"),
  };
}

function generationParameters(model: GenerationOption, config: GenerationConfig) {
  // **图像和视频都要的那几项先放这儿。** 此前它们写在 image 分支里,于是视频那条路上
  // 控件照常渲染、值却在这一行被丢掉 —— 用户填了种子不生效,
  // 而界面什么都没说。控件的显示条件本来就不分 kind(见 supportsParameter 那几处)。
  const shared: Record<string, string | number | boolean> = {};
  if (supportsParameter(model, "seed") && config.seed.trim()) shared.seed = Number(config.seed);
  for (const key of booleanParameterKeys(model)) {
    if (!DEDICATED_BOOLEANS.has(key)) shared[key] = config.booleanParameters[key] ?? capabilityBoolean(model, `default_${key}`);
  }
  for (const [key, choices] of parameterChoiceEntries(model)) {
    const value = config.enumParameters[key] ?? capabilityString(model, `default_${key}`, choices[0] ?? "");
    if (value) shared[key] = value;
  }
  // 模型自己声明的参数:**只发用户动过的**。插件给的默认值只是占位提示 —— 它本来就是那个模型
  // 自己的默认,原样发回去没有意义,而且会把「我没选过」变成「我选了这个」(ADR 0015)。
  for (const parameter of declaredParameters(model)) {
    const value = declaredParameterValue(parameter, config.declared[parameter.key] ?? "");
    if (value !== undefined) shared[parameter.key] = value;
  }

  if (model.kind === "image") {
    const params: Record<string, string | number | boolean> = { ...shared };
    if (supportsParameter(model, "size") && config.size) params.size = config.size;
    // 分辨率档(GPT Image 的 1K / 2K / 4K)决定像素预算、也就决定价钱:声明了就发。
    if (supportsParameter(model, "resolution") && config.resolution) params.resolution = config.resolution;
    if (supportsParameter(model, "num_images")) params.num_images = Math.max(1, Math.min(maxImages(model), Number(config.numImages) || 1));
    return params;
  }
  if (model.kind === "audio") {
    const params: Record<string, string | number | boolean | string[]> = { ...shared };
    // 时长空着 = 让模型自己定;填了才发。
    if (supportsParameter(model, "duration_seconds") && config.durationSeconds.trim() !== "") {
      params.duration_seconds = Number(config.durationSeconds);
    }
    if (supportsParameter(model, "instrumental")) params.instrumental = config.instrumental;
    // 纯音乐不带歌词 —— 两个都发,后端会拦下(各家要么报错、要么悄悄丢掉歌词)。
    if (supportsParameter(model, "lyrics") && !config.instrumental && config.lyrics.trim()) params.lyrics = config.lyrics;
    Object.assign(params, frameUrlParameters(config.frames, (role) => supportsParameter(model, role)));
    return params;
  }
  const params: Record<string, string | number | boolean> = { ...shared };
  // 空着或 0 = 未设置,不发,让模型用它自己的默认(与画板一致,见 lib/generationCapabilities.DURATION_UNSET)。
  if (supportsParameter(model, "duration_seconds") && config.durationSeconds.trim() !== "") {
    // 不在前端悄悄夹到上下界：-1 这类特殊值会被夹坏，真正非法的值应由统一校验器明确报错。
    const seconds = Number(config.durationSeconds);
    if (seconds !== DURATION_UNSET) params.duration_seconds = seconds;
  }
  // 尺寸**按模型声明的来**。这一支此前只认 `resolution`(720p 那种档位名)—— 那是按火山 /
  // 可灵那几家定的形状,而万相收的是 `宽*高` 的像素对。声明了 size 的模型于是一个尺寸都发不出去,
  // 参数描述符说了话而界面没听。
  if (supportsParameter(model, "size") && config.size) params.size = config.size;
  if (supportsParameter(model, "resolution") && config.resolution) params.resolution = config.resolution;
  if (supportsParameter(model, "aspect_ratio") && config.aspectRatio) params.aspect_ratio = config.aspectRatio;
  if (supportsParameter(model, "generate_audio")) params.generate_audio = config.generateAudio;
  // 外链形式的输入素材:first_frame_url / last_frame_url / reference_image_url。
  // 三种角色一条路 —— 此前只有首帧那一条,而且是手写的。
  Object.assign(params, frameUrlParameters(config.frames, (role) => supportsParameter(model, role)));
  return params;
}

function generationOptionValue(providerProfileId: string, kind: string, model: string) {
  return [providerProfileId, kind, model].join(ENGINE_SEP);
}

function findGenerationOption(
  options: GenerationEngineOption[],
  providerProfileId: string,
  kind: string,
  model: string,
) {
  return options.find((option) => option.value === generationOptionValue(providerProfileId, kind, model)) ?? null;
}

/**
 * 一页生成是**哪几种**:「生成」页是图像和视频,「音频」页的「音乐与音效」是音频(见 AudioWorkspace)。
 * 两页是同一个组件、同一条生成管线 —— 差的只是列哪几种模型、列哪几条会话(会话按种类分页,见后端
 * `GET /generation/sessions?kind=`)。第一种是这一页的缺省:新会话记成它,没设默认时先挑它的默认模型。
 */
//: 生成管线的几种(ADR 0022):模型清单按它们各拉一份。语音、播客的引擎来自配音那一族(voicedCreation)。
const GENERATION_KINDS = ["image", "video", "audio"] as const;

/**
 * 生成的样子和对话一样:左边会话,中间这条会话的来回,右边模型与参数。
 *
 * 同事共享来的会话**只能看**(后端 generation/sessions 定的规矩,`is_mine` 是它给的答案):输入区换成一句只读说明,
 * 模型与参数栏不开 —— 会话记着的是主人的连接,在这里换模型等于把自己的连接写进别人的会话。
 */
export function GenerateWorkspace({
  workspace,
  switcher,
}: {
  workspace: Workspace;
  switcher?: React.ReactNode;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const qc = useQueryClient();
  
  const panels = useSidePanels("generation", AI_PANEL_BOUNDS);
  const narrowLayout = useMediaMatch("(max-width: 1180px)");
  const singleColumn = useMediaMatch("(max-width: 820px)");
  const [parametersOpen, setParametersOpen] = React.useState(() => !narrowLayout);
  //: 右栏「引擎参数」(焦点要落进去)。底下那枚模型按钮点了:开着的就把模型那一块亮一下(engineFlash 是这一次的时刻)。
  const enginePanel = React.useRef<HTMLElement>(null);
  const enginePanelId = React.useId();
  const [engineFlash, setEngineFlash] = React.useState(0);
  //: 创作页(ADR 0055):一份会话列表,上面一排筛选(全部 · 图像 · 视频 · 语音 · 播客 · 音乐),记在本机。
  const [filter, setFilter] = usePersistentTab<CreateFilter>(CREATE_FILTER_KEY, "all", CREATE_FILTERS);
  //: 「上次开着哪条」一个键:筛选只是看哪几条,不是另一页。
  const sessionKey = creationSessionKey(workspace.id);
  const [sessionId, setSessionId] = React.useState<string | null>(() => window.localStorage.getItem(sessionKey));
  const [prompt, setPrompt] = React.useState("");
  //: 这一次 `@` 到的资产(ADR 0027):提示词描述和参考图由服务端按所选模型收得下的张数挂上。
  const [mentionedEntities, setMentionedEntities] = React.useState<EntitySummary[]>([]);
  const [modelId, setModelId] = React.useState<string | null>(null);
  const [generationConfig, setGenerationConfig] = React.useState<GenerationConfig>(() => defaultGenerationConfig(null));
  

  const sessions = useQuery({
    //: 键以 ["generation-sessions", 工作区] 开头:会话列表、共享菜单按这个前缀失效,两页一起刷。
    queryKey: ["generation-sessions", workspace.id, filter],
    //: 在服务端筛,不在界面上筛:列表有条数上限,界面筛的话一种会话能把另一种挤出去。
    queryFn: () =>
      api<GenerationSession[]>(
        `/api/generation/sessions?workspace_id=${workspace.id}${filter === "all" ? "" : `&kind=${filter}`}`,
      ),
  });
  //: 别处要求打开某一条创作会话(任务中心「前往」、智能体 open_view("ai", id)、资产详情「在哪里用过」):筛选回到「全部」
  //: (那一条是什么种类这边不知道),开着它。
  useOpenRequest(OPEN_CREATION_SESSION_EVENT, (id) => {
    setFilter("all");
    setSessionId(id);
    window.localStorage.setItem(sessionKey, id);
  });
  //: 「筛选换成这一种」(模型库「用它生成」带着种类过来)。
  useOpenRequest(CREATION_FILTER_EVENT, (kind) => {
    if (isCreateFilter(kind)) setFilter(kind);
  });
  //: 生成管线的几种各拉一份选项;语音、播客的引擎另拉(useVoicedOptions)。
  const generationOptions = useGenerationOptions(GENERATION_KINDS);
  const voicedOptions = useVoicedOptions();
  //: 挂着创作记录的任务(生成、语音、播客):按种类列 `tts` 会把字幕配音的几百句零件一起拉回来。
  const jobs = useQuery({
    queryKey: ["jobs", workspace.id, "creation"],
    queryFn: () => listJobs(workspace.id, { recorded: true }),
    refetchInterval: (query) =>
      query.state.data?.some((job) => job.status === "queued" || job.status === "running") ? 1000 : false,
    refetchOnWindowFocus: true,
  });
  //: 开着的那条:**选过的那条,没选过就是「新的一条」** —— 不落进列表里最近的那条。画板、工作流、智能体、定时任务每跑一次
  //: 生成都会新开一条会话,落进「最近一条」的话,用户在这里写的提示词就续进了画板那条线程(UC-03)。新的一条第一次提交时才建。
  const activeSession = (sessions.data ?? []).find((session) => session.id === sessionId) ?? null;
  //: 同事共享来的:只能看。只认后端明说「不是你的」—— 没说的(刚建、还没回来)当作自己的。
  const readOnly = activeSession?.is_mine === false;
  //: 模型与参数栏是「写」的一部分:只读的会话不开它(开着的话,在这里换模型会写进别人的会话)。
  const panelOpen = parametersOpen && !readOnly;
  const showRightPanel = panelOpen && !narrowLayout;
  // 内联 gridTemplateColumns 会覆盖 class 里的 max-[...] 回退,所以断点在 JS 里一起判 ——
  // 单列也显式指定,避免 CSS 与 matchMedia 在断点处有不同的边界语义。
  const columns = singleColumn
    ? "minmax(0,1fr)"
    : showRightPanel
      ? `${panels.left}px minmax(0,1fr) ${panels.right}px`
      : `${panels.left}px minmax(0,1fr)`;
  //: 贴底跟随(见 features/agent/stickToBottom)。
  const stick = useStickToBottom<HTMLDivElement>(activeSession?.id);
  const sessionJobs = useQuery({
    queryKey: ["generation-jobs", workspace.id, activeSession?.id],
    enabled: Boolean(activeSession),
    queryFn: () =>
      api<GenerationJob[]>(`/api/generation/jobs?workspace_id=${workspace.id}&session_id=${activeSession!.id}`),
    refetchInterval: (query) => {
      const activeJobIds = new Set(
        (jobs.data ?? []).filter((job) => job.status === "queued" || job.status === "running").map((job) => job.id),
      );
      if (query.state.data?.some((generation) => generation.job_id && activeJobIds.has(generation.job_id))) return 1000;
      //: 刚停下的那一条,账是执行体收完尾才记的(先让服务商 / 插件把远端那一次停掉,见后端 runner._settle_after_cancel),
      //: 比任务落「已停止」晚几秒:再看几眼,脚注里「未扣费」或金额才出得来。
      return query.state.data?.some(settlingAfterStop) ? 2000 : false;
    },
    refetchOnWindowFocus: true,
  });

  //: 下拉用的那一串:每个选项带上它在下拉里的值(连接 · 种类 · 模型)。
  const modelOptions = React.useMemo(
    () =>
      generationOptions.options.map((option): GenerationEngineOption => ({
        ...option,
        value: generationOptionValue(option.provider_profile_id, option.kind, option.model),
      })),
    [generationOptions.options],
  );
  const optionByValue = React.useMemo(
    () => new Map(modelOptions.map((option) => [option.value, option])),
    [modelOptions],
  );
  //: 两层名字(ADR 0045):主名是这一项自己的,副名说它来自哪张工作流、哪台服务器。有表单的那几张工作流,完整工作流的副名写
  //: 「完整工作流」,和它的表单分得开。
  const formed = React.useMemo(() => formedGroups(modelOptions), [modelOptions]);
  const namesOf = (option: GenerationOption) => generationOptionNames(option, formed, t);
  //: 会话锁「族」(ADR 0055 §2):有记录的会话,下拉只列同一族(视觉 = 图像 + 视频、音乐、语音、播客);想换族就新开一条。
  //: 没有记录的(新的一条、刚开还空着的)按筛选列:选了「语音」就只列语音引擎,「全部」列全部。
  //: 记录还没读到时按「有记录」算:会话是第一次提交才建的,开着的那条几乎都有记录;不这样的话读完那一下右栏冒出锁族那句说明,
  //: 下面的字段整块往下跳一截(和中间那一轮的骨架同一个目标:加载完不挪位置)。
  const hasRecords = (sessionJobs.data ?? []).length > 0 || (Boolean(activeSession) && sessionJobs.isLoading);
  const familyLocked = Boolean(activeSession?.kind && hasRecords);
  const pickerKinds: readonly string[] | null = familyLocked
    ? familyKinds(activeSession!.kind!)
    : filter === "all" ? null : [filter];
  const pickerModelOptions = React.useMemo(
    () => (pickerKinds ? modelOptions.filter((option) => pickerKinds.includes(option.kind)) : modelOptions),
    // pickerKinds 每次是新数组;按它的内容比
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [modelOptions, pickerKinds?.join(",")],
  );
  const pickerVoicedOptions = pickerKinds
    ? voicedOptions.options.filter((option) => pickerKinds.includes(option.kind))
    : voicedOptions.options;
  const voicedByValue = React.useMemo(
    () => new Map(voicedOptions.options.map((option) => [option.value, option])),
    [voicedOptions.options],
  );
  //: 语音、播客那一族选中的是哪个引擎:这次挑的 → 会话记着的(语音 / 播客会话的 model 是引擎 id)→ 新的一条按筛选落在默认引擎上
  //: (语音先 Edge:内置、免费,不替人挑一个要花钱的)。挑了生成模型(modelId 不是语音 / 播客的值)就不是这一族。
  const sessionVoicedKind = isVoicedKind(activeSession?.kind) ? activeSession!.kind as "speech" | "podcast" : null;
  const pickedVoiced = modelId ? voicedByValue.get(modelId) ?? null : null;
  const voicedChoice: VoicedOption | null =
    pickedVoiced ??
    (modelId
      ? null
      : sessionVoicedKind
        ? voicedOptions.options.find((option) => option.kind === sessionVoicedKind && option.engine.id === activeSession?.model) ??
          defaultVoicedOption(voicedOptions.options, sessionVoicedKind)
        : !activeSession && isVoicedKind(filter)
          ? defaultVoicedOption(voicedOptions.options, filter)
          : null);
  //: 生成管线那几种的「记着的」:语音、播客会话不算(它们的 model 是配音引擎,不在生成选项里)。
  const sessionEngine =
    !sessionVoicedKind && activeSession?.provider_profile_id && activeSession.model && activeSession.kind
      ? { provider_profile_id: activeSession.provider_profile_id, model: activeSession.model, kind: activeSession.kind }
      : null;
  //: 新的一条先落在哪一种的默认上:筛选那一种;「全部」时图像。
  const preferredKind = generationKindOf(pickerKinds?.[0]) ?? "image";
  //: 这次挑的 → 会话记着的 → (会话什么都没记着时)用户设的默认(先这一页的第一种,没有就这一页随便哪一种的默认)→ 没有。
  //: **不拿第一项顶上**:没设默认时选择器显示「选择模型」,等人选(见 pickGenerationOption)。**会话记着的不在选项里,也不拿
  //: 默认顶上**(见 chooseGenerationOption):此前顶上的是默认的按次付费模型,下拉、右栏、底下那枚按钮全是它,点发送就拿它去
  //: 生成了,而用户以为在用他的 ComfyUI 工作流。现在显示的是记着的那个、标着用不了、说原因,发送键灰着;自己挑了别的才换。
  const sessionChoice = chooseGenerationOption(pickerModelOptions, sessionEngine, { kind: preferredKind, loaded: generationOptions.loaded });
  const pickedOption = modelId ? optionByValue.get(modelId) ?? null : null;
  const selectedModel = voicedChoice || sessionVoicedKind
    ? pickedOption
    : pickedOption ?? sessionChoice.option ?? (sessionEngine ? null : pickGenerationOption(pickerModelOptions));
  //: 会话记着的那个现在用不了(这次也没挑别的):它叫什么、为什么、怎么修
  const missingEngine = pickedOption || voicedChoice ? null : sessionChoice.missing;
  const missingModel = useMissingModel(missingEngine);
  const generationModelsLoading = generationOptions.pending;
  //: 这一页的几种生成一个模型都没有。选项在后端就只列启用连接下启用的模型(provider_models.models_for_capability),
  //: 所以「没配置」只有这一种样子 —— 不再拿设置页的连接列表另判一遍「选中的这个配没配」:
  //: 那一判只在连接列表还没到或取失败时为真,表现为提示条一闪、或一直挂着。
  //: 下拉里这会儿能挑的(按筛选 / 会话那一族)一个都没有。
  const noGenerationModels =
    pickerModelOptions.length === 0 && pickerVoicedOptions.length === 0 && !generationModelsLoading && voicedOptions.loaded;
  //: 去配置时落到哪一页:选中的模型是哪种能力就去哪种;一个都没选时看会话记着的、筛选的那种,再没有才去图像。语音、播客去配音那一页。
  const settingsSection = voicedChoice || isVoicedKind(filter)
    ? "provider-audio"
    : `providers:${selectedModel?.kind ?? generationKindOf(activeSession?.kind) ?? preferredKind}`;
  const selectedAdapterAvailable = selectedModel?.adapter_available ?? false;
  const selectedDurations = durationChoices(selectedModel, generationConfig.resolution);
  const selectedResolutions = videoResolutionOptions(selectedModel);
  const selectedAspectRatios = aspectRatioOptions(selectedModel);
  // 音频的时长是**可选的数字输入**,不是下拉:Suno 收 10–360 秒,摊成下拉就是三百多项;而且空着
  // 是合法的(让模型按歌词定),不能被下面那条「不在档位里就改成第一档」悄悄填上。
  const audioDurationRange = selectedModel?.kind === "audio" ? durationRange(selectedModel) : null;
  const durationIsFreeInput = selectedModel?.kind === "audio" && durationOptions(selectedModel).length === 0;
  React.useEffect(() => {
    if (durationIsFreeInput) return;
    const current = Number(generationConfig.durationSeconds);
    if (selectedDurations.length > 0 && !selectedDurations.includes(current)) {
      setGenerationConfig((config) => ({ ...config, durationSeconds: String(selectedDurations[0]) }));
    }
  }, [generationConfig.durationSeconds, selectedDurations, durationIsFreeInput]);
  // 图像和视频分走两套栏目(张数 vs 时长/分辨率/画幅),这个判断在下面出现十来次。
  const isImageModel = selectedModel?.kind === "image";
  // 音频多两样:歌词和纯音乐开关;结果是一段声音(见 audioGeneration.tsx)。
  const isAudioModel = selectedModel?.kind === "audio";
  //: 这个模型对提示词的要求(见 promptMode):不收的不摆框,可以不写的在占位里说清楚。
  const selectedPromptMode = promptMode(selectedModel);
  //: 输入框占位和空态正文说的是同一句话,按所选模型来:可选的说可选,音频说声音,其余说画面。
  //: 不收提示词的那一句由输入框那一格说,空态不再重复一遍。
  //: 可以不写、而且说得出不写用哪一句的(ComfyUI 工作流里存着一句):占位就说「不写就用工作流里存的那句」,不再是笼统的
  //: 「不写也能生成」—— 那句话没说生成的是什么。
  const promptHintKey =
    selectedPromptMode === "none"
      ? "genPromptNotUsed"
      : selectedPromptMode === "optional"
        ? promptDefault(selectedModel) ? "promptPlaceholderStored" : "promptPlaceholderOptional"
        : isAudioModel
          ? "audioPromptPlaceholder"
          : "promptPlaceholder";
  //: 作者给这张工作流挑的那张表(精简表单):有就照它摆右栏(见 appFormPanel)
  const selectedForm = appForm(selectedModel);
  //: 输入框:表单里「提示词」那一项的「去写」把焦点送过来
  const composer = React.useRef<HTMLTextAreaElement>(null);
  const supportsLyrics = isAudioModel && supportsParameter(selectedModel, "lyrics");
  const supportsInstrumental = isAudioModel && supportsParameter(selectedModel, "instrumental");
  const selectedAudioRoles = audioSourceRoles(selectedModel);
  const supportsNegativePrompt = supportsParameter(selectedModel, "negative_prompt");
  const supportsReferenceImage = supportsParameter(selectedModel, "reference_image");
  const supportsFirstFrame = selectedModel?.kind === "video" && supportsParameter(selectedModel, "first_frame");
  // 视频的参考素材:参考图/参考视频/参考音频。它们和首尾帧**不是一回事** —— 首尾帧决定
  // 成片的第一格和最后一格,参考素材一帧都不出现在成片里,只影响风格与主体。
  const videoReferenceRoles = (["reference_image", "reference_video", "reference_audio"] as const).filter(
    (role) => selectedModel?.kind === "video" && supportsParameter(selectedModel, role),
  );
  // 拿一段现成的视频当输入,这是第三条路:编辑(输出就是这一段改过的样子)和续写(输出以它
  // 开头再往下长)。它们既不是首尾帧也不是参考素材,所以单独列在最上面 —— 选了这类模型,
  // 用户第一件要做的事就是把那段片子挂上去。
  const videoInputRoles = (["source_video", "first_clip", "driving_audio"] as const).filter(
    (role) => selectedModel?.kind === "video" && supportsParameter(selectedModel, role),
  );
  // 互斥由描述符说了算(各家接口的硬约束,不是我们的规矩):一组用上了,另一组就灰掉,
  // 而不是让用户挂满了才在提交时吃一个说着数组下标的英文 400。
  const lockedRoles = React.useMemo(() => {
    const groups = exclusiveSourceGroups(selectedModel);
    const used = new Set(
      SOURCE_ROLES.filter((role) => filledCount(generationConfig.frames, role) > 0),
    );
    const active = groups.filter((group) => group.some((role) => used.has(role as SourceRole)));
    if (active.length === 0) return new Set<string>();
    return new Set(
      groups.filter((group) => !active.includes(group)).flatMap((group) => group),
    );
  }, [selectedModel, generationConfig.frames]);
  React.useEffect(() => {
    setModelId(null);
  }, [activeSession?.id]);
  //: 挂了驱动音频 = 数字人生成:提交前必须勾上授权(后端生成漏斗同一条,不勾就 422)。换模型时清掉,不替他带过去。
  const [digitalHumanConsent, setDigitalHumanConsent] = React.useState(false);
  const needsDigitalHumanConsent =
    videoInputRoles.includes("driving_audio") && filledCount(generationConfig.frames, "driving_audio") > 0;
  //: 别的页面交过来的「用这个去生成」(模型库的「用它生成」,见 lib/generationHandoff):清单和会话列表都到了再接 ——
  //: 会话一到会把这一页的选择清回会话记着的那个(上面那条 effect),先接了也白接。选中的模型换了,参数会回到它的
  //: 默认(下面那条 effect),所以交过来的那几格记在这里,等换完再填上。
  const handedOver = React.useRef<{ value: string; declared: Record<string, string> } | null>(null);
  React.useEffect(() => {
    if (generationModelsLoading || sessions.isPending) return;
    const handoff = takeGenerationHandoff();
    if (!handoff) return;
    const option = findGenerationOption(modelOptions, handoff.providerProfileId, handoff.kind, handoff.model);
    if (!option) return;
    if (handoff.promptWords.length > 0) setPrompt((current) => withTriggerWords(current, handoff.promptWords));
    if (selectedModel?.value === option.value) {
      setGenerationConfig((current) => ({ ...current, declared: { ...current.declared, ...handoff.declared } }));
      return;
    }
    handedOver.current = { value: option.value, declared: handoff.declared };
    setModelId(option.value);
    // 只在清单 / 会话到齐的那一刻接一次;交接本身取走就没了
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [generationModelsLoading, sessions.isPending, modelOptions]);
  React.useEffect(() => {
    const defaults = defaultGenerationConfig(selectedModel);
    const handed = handedOver.current;
    if (handed && handed.value === selectedModel?.value) {
      handedOver.current = null;
      setGenerationConfig({ ...defaults, declared: { ...defaults.declared, ...handed.declared } });
    } else {
      setGenerationConfig(defaults);
    }
    setDigitalHumanConsent(false);
  }, [selectedModel?.value]);
  const modelGroups = React.useMemo(() => {
    const grouped = new Map<string, GenerationEngineOption[]>();
    for (const model of pickerModelOptions) {
      grouped.set(model.kind, [...(grouped.get(model.kind) ?? []), model]);
    }
    const known = ["image", "video", "audio"];
    return [...known, ...[...grouped.keys()].filter((kind) => !known.includes(kind))]
      .filter((kind) => (grouped.get(kind) ?? []).length > 0)
      .map((kind) => ({ kind, models: grouped.get(kind) ?? [] }));
  }, [pickerModelOptions]);
  const capabilityLabel = (kind: string) =>
    kind === "image"
      ? t("capImage")
      : kind === "video"
        ? t("capVideo")
        : kind === "audio"
          ? t("capAudio")
          : kind === "speech"
            ? t("createKindSpeech")
            : kind === "podcast"
              ? t("createKindPodcast")
              : kind;
  const canSubmitText = hasEnoughText(selectedModel, prompt, generationConfig.lyrics, generationConfig.instrumental);
  const setConfigValue = (key: keyof GenerationConfig, value: string) =>
    setGenerationConfig((current) => ({ ...current, [key]: value }));
  const setFrames = (role: SourceRole, slots: FrameSlot[]) =>
    setGenerationConfig((current) => ({ ...current, frames: { ...current.frames, [role]: slots } }));
  const clearReferenceImage = () =>
    setGenerationConfig((current) => ({
      ...current,
      frames: { ...current.frames, reference_image: [{ ...EMPTY_SLOT }] },
      usePreviousImage: false,
    }));
  const usePreviousImageAsReference = () =>
    setGenerationConfig((current) => ({
      ...current,
      frames: { ...current.frames, reference_image: [{ ...EMPTY_SLOT }] },
      usePreviousImage: true,
    }));
  const selectEngine = (value: string) => {
    if (readOnly) return;
    //: 语音、播客:会话记着的「模型」是引擎 id(音色、语速接着最后一条记录用的,见 useSpeechDraft)
    const voiced = voicedByValue.get(value);
    const option = voiced ? null : optionByValue.get(value);
    if (!voiced && !option) return;
    setModelId(value);
    if (activeSession) {
      updateSessionEngine.mutate({
        id: activeSession.id,
        provider_profile_id: voiced ? null : option!.provider_profile_id,
        model: voiced ? voiced.engine.id : option!.model,
        kind: voiced ? voiced.kind : option!.kind,
      });
    }
  };

  //: 新会话记着种类:它决定会话在筛选里归哪一种(ADR 0055)。
  const newSessionKind = selectedModel?.kind ?? preferredKind;
  //: 「+」:换成新的一条(草稿先行,和对话那边一样,ADR 0044)—— 不在服务端建一条空会话,第一次提交时才建(createGeneration)。
  //: 此前每点一次就建一条,当「清空输入、换个思路」用的人列表里积满空的「新生成」(UC-10)。
  const startNewSession = () => {
    setSessionId(null);
    window.localStorage.removeItem(sessionKey);
  };
  const ordered = React.useMemo(() => sessionJobs.data ?? [], [sessionJobs.data]);
  //: 老的语音记录(迁移过来的)没记音色名:标题从这条会话所用引擎的音色目录里认
  const voiceLabels = useVoiceLabels(
    workspace.id,
    ordered.filter((generation) => generation.kind === "speech" && !generation.request?.voice_label).map((generation) => generation.provider),
  );
  // 会话画廊:点开任意一张图,可左右翻看本会话的全部图片产出。
  //: **每条生成摊平成它的全部产出** —— 一次出四张时,画廊里就该有四张;只收封面的话,
  //: 用户左右翻着翻着会发现刚看到的那三张翻不到。
  //: 视频生成的那几条也在里面(灯箱同一个,那一项换成播放器):一个出视频的会话,左右翻的就是这几段片子。
  const sessionGallery = React.useMemo<ImagePreviewItem[]>(
    () =>
      ordered
        .filter((generation) => generation.kind === "image" || generation.kind === "video")
        .flatMap((generation) => {
          const title = String(generation.request.prompt ?? generation.model);
          if (generation.kind === "video") {
            //: 和下面那张播放器一样只放封面那一份(result_asset_id)。
            return generation.result_asset_id ? [{ src: assetFileUrl(generation.result_asset_id), title, video: true }] : [];
          }
          const ids = generation.result_asset_ids?.length
            ? generation.result_asset_ids
            : generation.result_asset_id
              ? [generation.result_asset_id]
              : [];
          return ids.map((assetId) => ({ src: assetPreviewUrl(assetId), title }));
        }),
    [ordered],
  );
  const latestImageResult = React.useMemo(
    () => [...ordered].reverse().find((generation) => generation.kind === "image" && generation.result_asset_id) ?? null,
    [ordered],
  );
  const effectiveReferenceImageAssetId =
    selectedModel?.kind === "image"
      ? generationConfig.frames.reference_image[0]?.assetId ||
        (generationConfig.usePreviousImage ? latestImageResult?.result_asset_id ?? "" : "")
      : "";

  const createGeneration = useMutation({
    mutationFn: async () => {
      let targetSessionId = activeSession?.id;
      if (!targetSessionId) {
        const payload: Record<string, string> = {
          workspace_id: workspace.id,
          kind: newSessionKind,
          // 音频可以只给歌词:那就拿歌词的第一行当会话名。
          title:
            prompt.trim().slice(0, 40) ||
            generationConfig.lyrics.trim().split("\n")[0]?.slice(0, 40) ||
            t("generationNewSession"),
        };
        //: 记下这一条用的模型:下次打开这条会话,选择器停在它上面(它后来用不了了,就照实说,不拿别的顶上)
        if (selectedModel) {
          payload.provider_profile_id = selectedModel.provider_profile_id;
          payload.model = selectedModel.model;
        }
        const created = await api<GenerationSession>("/api/generation/sessions", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        targetSessionId = created.id;
        setSessionId(created.id);
        window.localStorage.setItem(sessionKey, created.id);
      }
      await api<GenerationCreateResponse>("/api/generation/jobs", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: workspace.id,
          session_id: targetSessionId,
          project_id: null,
          provider_profile_id: selectedModel!.provider_profile_id,
          provider: selectedModel!.provider,
          model: selectedModel!.model,
          kind: selectedModel!.kind,
          prompt: promptToSend(selectedModel, prompt),
          negative_prompt: supportsNegativePrompt ? generationConfig.negativePrompt.trim() : "",
          parameters: generationParameters(selectedModel!, generationConfig),
          // 每份素材带着**它的用途**。此前这里是一个裸 id 数组,谁是首帧靠后端「取第 0 个」
          // 那条约定 —— 尾帧因此没地方放,而多加一个位置约定不会报错,只会生成出别的东西。
          source_assets: sourceAssetsFrom(
            // 「用上一张结果」是把上一次的产物**当场**当参考图,它不落在配置里(配置只记
            // 用户挑了什么),所以在这里合进去。
            {
              ...generationConfig.frames,
              reference_image: effectiveReferenceImageAssetId
                ? [
                    { ...(generationConfig.frames.reference_image[0] ?? EMPTY_SLOT), assetId: effectiveReferenceImageAssetId },
                    ...generationConfig.frames.reference_image.slice(1),
                  ]
                : generationConfig.frames.reference_image,
            },
            (role) => supportsParameter(selectedModel, role),
          ),
          entity_ids: mentionedEntities.map((one) => one.id),
          digital_human_consent: needsDigitalHumanConsent && digitalHumanConsent,
        }),
      });
      return targetSessionId;
    },
    onSuccess: (targetSessionId) => {
      setPrompt("");
      setMentionedEntities([]);
      void qc.invalidateQueries({ queryKey: ["generation-sessions", workspace.id] });
      void qc.invalidateQueries({ queryKey: ["generation-jobs", workspace.id, targetSessionId] });
    },
  });
  //: 语音、播客(ADR 0055):谁来念、播客的稿子和发音人。音色、语速、发音人接着这条会话最后一条记录用的。
  const lastOf = (kind: string) => [...(sessionJobs.data ?? [])].reverse().find((generation) => generation.kind === kind) ?? null;
  const speech = useSpeechDraft(workspace.id, voicedChoice?.kind === "speech" ? voicedChoice.engine.id : null, lastOf("speech"));
  const podcast = usePodcastDraft(voicedOptions.options.some((option) => option.kind === "podcast"), lastOf("podcast"));
  const voicedCanSubmit = voicedChoice
    ? voicedChoice.kind === "speech"
      ? speechReady(speech, prompt)
      : podcastReady(podcast, prompt, voicedChoice.engine)
    : false;
  //: 念 / 做播客:没带会话就由后端现开一条(回执里的 session_id),这边接着开着它。远端引擎念配音库里的嗓子、这个账号
  //: 第一次用时先问要不要传上去(ADR 0037)。
  const createVoiced = useMutation({
    mutationFn: async () => {
      const base = { workspace_id: workspace.id, session_id: activeSession?.id ?? null };
      const created = voicedChoice!.kind === "speech"
        ? await withRemoteVoiceConsent(() => createSpeech({ ...base, ...speechRequest(speech, prompt) }))
        : await createPodcast({ ...base, ...podcastRequest(podcast, prompt) });
      return created.generation.session_id ?? null;
    },
    onSuccess: (targetSessionId) => {
      setPrompt("");
      if (voicedChoice?.kind === "podcast" && podcast.mode === "read") podcast.setTurns([{ speaker: 0, text: "" }]);
      if (targetSessionId) {
        setSessionId(targetSessionId);
        window.localStorage.setItem(sessionKey, targetSessionId);
      }
      void qc.invalidateQueries({ queryKey: ["generation-sessions", workspace.id] });
      void qc.invalidateQueries({ queryKey: ["generation-jobs", workspace.id, targetSessionId ?? undefined] });
      void qc.invalidateQueries({ queryKey: ["jobs", workspace.id, "creation"] });
    },
    onError: (error) => {
      if (!isConsentDeclined(error)) toast.error(errorText(error));
    },
  });
  //: 「改稿再念」:那一份对谈稿装进照稿念,发音人换成那一次的两位;引擎留在播客上,滚到底下的输入框
  const rescriptPodcast = (turns: ScriptTurn[], speakers: string[]) => {
    podcast.rescript(turns, speakers);
    stick.scrollToBottom();
  };
  //: 优化走的是「对话」默认 LLM,不是图像模型(见下方 mutationFn):能不能点看对话默认模型在不在,
  //: 和图像模型的适配器可不可用无关。默认值还在路上时不算缺。
  const chatModel = useEffectiveChatModel(null);
  const chatModelMissing = !chatModel.pending && !chatModel.providerProfileId;
  // 分平台提示词优化:按当前所选图像模型的平台习惯重写提示框内容(与助手技能共用同一后端)。
  const optimizePrompt = useMutation({
    mutationFn: () =>
      optimizeImagePrompt({
        workspace_id: workspace.id,
        provider: selectedModel!.provider,
        model: selectedModel!.model,
        prompt,
        // 不传图像模型的 profile:重写用的是「对话」默认 LLM,后端按 resolve_default("chat") 解析。
        language: locale,
      }),
    onSuccess: (result) => {
      setPrompt(result.prompt);
      // SD 类平台会连 negative 一起给;仅当当前模型支持 negative 时才写回。
      if (result.negative_prompt && supportsNegativePrompt) {
        setGenerationConfig((config) => ({ ...config, negativePrompt: result.negative_prompt }));
      }
      toast.success(`${t("optimizePrompt")} · ${result.platform}`, { description: result.notes || undefined });
    },
    onError: (error) => {
      toast.error(t("optimizePromptFailed"), { description: errorText(error) });
    },
  });
  const updateSessionEngine = useMutation({
    mutationFn: ({
      id,
      provider_profile_id,
      model,
      kind,
    }: {
      id: string;
      provider_profile_id: string | null;
      model: string;
      kind: string;
    }) =>
      api<GenerationSession>(`/api/generation/sessions/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ provider_profile_id, model, kind }),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["generation-sessions", workspace.id] });
    },
  });

  //: 停下一条:取消它的任务(和任务中心的「取消」、画板的「停止」同一条路,见后端 jobs.cancel_job)。任务落成「已停止」,
  //: 跑在插件上的(ComfyUI)由插件把**这一次**的任务从那台机器上停掉 —— 在跑的中断、在排的撤掉,别人的不碰。
  const stopGeneration = useMutation({
    mutationFn: (jobId: string) => cancelJob(jobId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["jobs", workspace.id, "creation"] });
      void qc.invalidateQueries({ queryKey: ["generation-jobs", workspace.id, activeSession?.id] });
    },
    onError: (error) => toast.error(t("genStopFailed"), { description: errorText(error) }),
  });

  //: 重新取回一条失败了的:服务商已经做完的那一次,不重新提交、不再付钱(见后端 generation.use_cases.retrieve)。挂上一个新任务,
  //: 卡片从失败变回进度,和刚提交的那一条同一种样子;落了终态由下面那段重拉记录。
  const retrieveAgain = useMutation({
    mutationFn: (generationId: string) => retrieveGeneration(generationId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["jobs", workspace.id, "creation"] });
      void qc.invalidateQueries({ queryKey: ["generation-jobs", workspace.id, activeSession?.id] });
    },
    onError: (error) => toast.error(t("genRetrieveFailed"), { description: errorText(error) }),
  });

  //: 失败卡上的「再来一次」:照这一条记着的模型和参数重新提交一次,收在同一条会话里(见后端 generation.use_cases.again)。新的一条
  //: 接在下面,和点发送一样。
  const repeatAgain = useMutation({
    mutationFn: (generationId: string) => repeatGeneration(generationId),
    onSuccess: () => {
      stick.scrollToBottom();
      void qc.invalidateQueries({ queryKey: ["jobs", workspace.id, "ai_generation"] });
      void qc.invalidateQueries({ queryKey: ["generation-jobs", workspace.id, activeSession?.id] });
      void qc.invalidateQueries({ queryKey: ["generation-sessions", workspace.id] });
    },
    onError: (error) => toast.error(t("genRepeatFailed"), { description: errorText(error) }),
  });

  //: 一条任务落了终态就重拉这条会话的记录:成功的带回产出,失败的带回**记录自己存的**失败原因
  //: (生成记录在任务失败那一刻抄下它,任务之后会被清掉,见后端 generation.runner.record_failure)。
  //: 按「哪几条落了终态」认,不按条数:列表只给最近的两百条加上在跑的(后端定的),新建一条把最老的一条挤出去、同一拍里
  //: 另一条落了终态,条数不变 —— 按条数认的话这一次就不重拉了。
  const settled = (jobs.data ?? []).filter((job) => jobSettled(job.status)).map((job) => job.id).join(",");
  React.useEffect(() => {
    if (settled) {
      void qc.invalidateQueries({ queryKey: assetKeys.everywhere() });
      void qc.invalidateQueries({ queryKey: ["generation-jobs", workspace.id, activeSession?.id] });
      void qc.invalidateQueries({ queryKey: ["generation-sessions", workspace.id] });
    }
  }, [settled, qc, workspace.id, activeSession?.id]);

  //: 输入框底下那枚模型按钮:打开右边的「引擎参数」,焦点落到模型选择上。**已经开着也要有反应** —— 此前它只会
  //: setParametersOpen(true),栏开着时点了什么都不发生(维护者:「点击底部这个 ComfyUI 开头的这一串没有任何反应」)。
  //: 现在开着就把模型那一块亮一下,焦点照样过去;收起栏用栏头的 ×、或顶上那颗「引擎参数」。
  const showEngineSettings = () => {
    setParametersOpen(true);
    setEngineFlash(Date.now());
  };
  //: 记着的模型用不了时的「换一个模型」:打开右栏、直接打开模型下拉
  const pickAnotherModel = () => {
    setParametersOpen(true);
    window.requestAnimationFrame(() => enginePanel.current?.querySelector<HTMLElement>("[data-engine-picker] button")?.click());
  };
  React.useEffect(() => {
    if (!engineFlash) return;
    //: 等栏挂出来(收着的时候它是 hidden,里面的东西接不住焦点)
    const frame = window.requestAnimationFrame(() => {
      enginePanel.current?.querySelector<HTMLElement>("[data-engine-picker] button")?.focus();
    });
    const timer = window.setTimeout(() => setEngineFlash(0), 1200);
    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(timer);
    };
  }, [engineFlash]);

  //: 输入框底下那枚模型按钮写什么:生成模型的两层名字,或者语音 / 播客的引擎名(副名说是哪一种)。
  const chipName = selectedModel
    ? namesOf(selectedModel)
    : voicedChoice
      ? { primary: voicedChoice.engine.label, secondary: capabilityLabel(voicedChoice.kind) }
      : null;
  //: 底栏右边那个数:要念的字数 / 上限,照稿念的段数 / 上限。
  const voicedCounter = voicedChoice ? voicedCount(voicedChoice.kind, prompt, podcast, t) : null;
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (voicedChoice) {
      if (readOnly || !voicedCanSubmit || createVoiced.isPending) return;
      stick.scrollToBottom();
      createVoiced.mutate();
      return;
    }
    if (readOnly || !canSubmitText || !selectedModel || !selectedAdapterAvailable || createGeneration.isPending) return;
    if (needsDigitalHumanConsent && !digitalHumanConsent) {
      toast.error(t("genDigitalHumanConsentNeeded"));
      return;
    }
    stick.scrollToBottom(); // 自己发的消息一定要看得见
    createGeneration.mutate();
  };

  //: ---- 右栏的一格一格 ----
  //: 通用的那几栏(出片规格、素材、调参)和「精简表单」(作者挑的那张表)摆的是**同一些控件**:表单只是换了顺序和名字。
  //: 所以每一格只写一处,两边都叫它 —— 不为表单另抄一份尺寸、种子、参考图。
  const sizeField = (model: GenerationEngineOption, label = t("genSize")) => {
    const sizes = sizeOptions(model);
    if (!supportsParameter(model, "size") || sizes.length === 0) return null;
    const custom = customSizeRule(model);
    return (
      <ParameterField key="size" label={label}>
        {custom ? (
          /* 推荐的几档、手填的也收(ComfyUI 的工作流) */
          <CustomSizePicker
            value={generationConfig.size}
            onChange={(value) => setConfigValue("size", value)}
            options={sizes}
            minimum={custom.minimum}
            ariaLabel={label}
            className={PARAMETER_CONTROL_CLASS}
          />
        ) : (
          <Select value={generationConfig.size} onValueChange={(value) => setConfigValue("size", value)}>
            <SelectTrigger className={PARAMETER_CONTROL_CLASS} aria-label={label}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {sizes.map((size) => (
                <SelectItem key={size} value={size}>
                  {size}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </ParameterField>
    );
  };
  const numImagesField = (model: GenerationEngineOption, label = generationParameterLabel("num_images", model, t)) =>
    supportsParameter(model, "num_images") ? (
      // ComfyUI 的工作流「张数」是跑几遍:标签换成「跑几遍」,下面说清一遍出几张、一共几张(见 runsHint)。
      <ParameterField
        key="num_images"
        label={label}
        hint={countsRuns(model)
          ? runsHint(t, model, generationParameters(model, generationConfig),
            Math.max(1, Math.min(maxImages(model), Number(generationConfig.numImages) || 1)))
          : undefined}
      >
        <Input
          className={PARAMETER_CONTROL_CLASS}
          type="number"
          aria-label={label}
          min={1}
          max={maxImages(model)}
          value={generationConfig.numImages}
          onChange={(event) => setConfigValue("numImages", event.target.value)}
        />
      </ParameterField>
    ) : null;
  const seedField = (label = t("genSeed")) => (
    <ParameterField key="seed" label={label}>
      <Input
        className={PARAMETER_CONTROL_CLASS}
        type="number"
        aria-label={label}
        placeholder="auto"
        value={generationConfig.seed}
        onChange={(event) => setConfigValue("seed", event.target.value)}
      />
    </ParameterField>
  );
  const negativePromptField = (label = t("genNegativePrompt")) => (
    <ParameterField key="negative_prompt" label={label}>
      <Input
        className={PARAMETER_CONTROL_CLASS}
        aria-label={label}
        value={generationConfig.negativePrompt}
        onChange={(event) => setConfigValue("negativePrompt", event.target.value)}
      />
    </ParameterField>
  );
  const setDeclared = (key: string, value: string) =>
    setGenerationConfig((current) => ({ ...current, declared: { ...current.declared, [key]: value } }));
  const declaredField = (model: GenerationEngineOption, parameter: DeclaredParameter, label?: string) => (
    <ParameterField
      key={parameter.key}
      // 宿主认得的参数名(人声、曲名……)按界面语言说;插件自己的参数用插件给的名字(表单里用表单上的名字)。
      label={label ?? (GENERATION_PARAMETER_LABELS[parameter.key] ? t(GENERATION_PARAMETER_LABELS[parameter.key]) : parameter.label)}
      title={toPlainText(parameter.description) || undefined}
    >
      {parameter.modelFolder && model.plugin_instance_id && parameter.options.length > 0 ? (
        /* 选模型文件的那一格:缩略图、底模、触发词来自这个连接的模型库,选中 LoRA 能一键加触发词 */
        <ModelFilePicker
          parameter={parameter}
          instanceId={model.plugin_instance_id}
          value={generationConfig.declared[parameter.key] ?? ""}
          onChange={(value) => setDeclared(parameter.key, value)}
          onUseTriggers={(words) => setPrompt((current) => withTriggerWords(current, words))}
          className={PARAMETER_CONTROL_CLASS}
        />
      ) : (
        <DeclaredParameterControl
          parameter={parameter}
          value={generationConfig.declared[parameter.key] ?? ""}
          onChange={(value) => setDeclared(parameter.key, value)}
        />
      )}
    </ParameterField>
  );
  //: 图像的参考图和视频那边**是同一件事**,所以用同一个控件:一行缩略图、一次能选多张、上限读描述符(seedream 4 十四张、
  //: qwen 三张、gpt-image 十六张)。手挑了图就不再"用上一张结果" —— 两个都开着的话,发出去的是哪张全看代码顺序。
  const referenceImageField = (model: GenerationEngineOption) => (
    <div key="reference_image" className="grid gap-1.5">
      <FrameSlotField
        role="reference_image"
        slots={generationConfig.frames.reference_image}
        limit={sourceLimit(model, "reference_image")}
        names={sourceLabels(model, "reference_image")}
        onChange={(slots) =>
          setGenerationConfig((current) => ({
            ...current,
            frames: { ...current.frames, reference_image: slots },
            usePreviousImage: slots.some((one) => one.assetId || one.url.trim()) ? false : current.usePreviousImage,
          }))
        }
        workspaceId={workspace.id}
      />
      {latestImageResult?.result_asset_id && !generationConfig.frames.reference_image[0]?.assetId && (
        <Button
          type="button"
          variant={generationConfig.usePreviousImage ? "outline" : "ghost"}
          size="sm"
          onClick={generationConfig.usePreviousImage ? clearReferenceImage : usePreviousImageAsReference}
        >
          {t("genUsePreviousImage")}
        </Button>
      )}
    </div>
  );
  const keyframesField = (model: GenerationEngineOption) => {
    // 尾帧:首尾帧一起给 = 让模型从一张图动到另一张图。只有描述符声明了的模型才出这个控件 ——
    // 控件跟着描述符走,不按 kind 写死(见 docs/CONVENTIONS 那条棘轮)。
    const withLast = model.kind === "video" && supportsParameter(model, "last_frame");
    return (
      <KeyframePairField
        key="keyframes"
        first={generationConfig.frames.first_frame}
        last={generationConfig.frames.last_frame}
        showLast={withLast}
        onChange={({ first, last }) =>
          setGenerationConfig((current) => ({ ...current, frames: { ...current.frames, first_frame: first, last_frame: last } }))
        }
        workspaceId={workspace.id}
        hint={withLast ? t("genLastFrameHint") : t("genKeyframeHint")}
        names={{ first: sourceLabels(model, "first_frame")[0], last: sourceLabels(model, "last_frame")[0] }}
        disabled={lockedRoles.has("first_frame")}
        disabledReason={t("genSourceGroupsExclusive")}
      />
    );
  };
  const slotsField = (model: GenerationEngineOption, role: SourceRole, hint?: string) => (
    <FrameSlotField
      key={role}
      role={role}
      slots={generationConfig.frames[role]}
      limit={sourceLimit(model, role)}
      names={sourceLabels(model, role)}
      onChange={(slots) => setFrames(role, slots)}
      workspaceId={workspace.id}
      hint={hint}
      disabled={lockedRoles.has(role)}
      disabledReason={t("genSourceGroupsExclusive")}
    />
  );
  /** 表单上的一个素材角色:和通用那一栏同一个控件、同一句提示(图像的参考图带「用上一张结果」,首尾帧成一对)。 */
  const sourceField = (model: GenerationEngineOption, role: SourceRole) => {
    if (role === "reference_image" && model.kind === "image") return referenceImageField(model);
    if ((role === "first_frame" || role === "last_frame") && model.kind === "video") return keyframesField(model);
    const hint =
      model.kind === "audio" && role in AUDIO_SOURCE_HINTS ? t(AUDIO_SOURCE_HINTS[role as keyof typeof AUDIO_SOURCE_HINTS])
        : role in VIDEO_INPUT_HINTS ? t(VIDEO_INPUT_HINTS[role as keyof typeof VIDEO_INPUT_HINTS])
          : role.startsWith("reference_") ? t("genReferenceHint")
            : undefined;
    return slotsField(model, role, hint);
  };
  /**
   * 表单上的主提示词:它就是下面那个输入框,这里说清楚 —— 去那儿写;可以不写的,说清不写用哪一句(工作流里存着的那句),
   * 一键填进输入框改。此前右栏对这一项一个字都没有,看着和工作流库里那张表(标题、说明、「提示词」)对不上。
   */
  const formPromptField = (model: GenerationEngineOption, label: string) => {
    const stored = promptDefault(model);
    const optional = promptMode(model) === "optional";
    return (
      <div key="prompt" className="grid gap-1.5 text-ui-sm text-muted-foreground" data-form-prompt="">
        <span>{label}</span>
        <div className="grid gap-1.5 rounded-lg border border-dashed border-border px-2.5 py-2">
          <span className="flex items-center gap-1.5 text-ui-xs font-medium text-foreground">
            <ArrowDownLeft size={13} className="shrink-0 text-muted-foreground" aria-hidden />
            {t(optional ? "genFormPromptOptional" : "genFormPromptInComposer")}
          </span>
          {optional && stored ? (
            <Truncate lines={3} className="text-ui-xs leading-relaxed text-muted-foreground [overflow-wrap:anywhere]">
              {t("genFormPromptStored").replace("{prompt}", stored)}
            </Truncate>
          ) : null}
          <div className="flex flex-wrap gap-1">
            <Button type="button" variant="ghost" size="xs" onClick={() => composer.current?.focus()}>
              {t("genFormPromptWrite")}
            </Button>
            {optional && stored ? (
              <Button
                type="button"
                variant="ghost"
                size="xs"
                onClick={() => {
                  setPrompt(stored);
                  composer.current?.focus();
                }}
              >
                {t("genFormPromptUseStored")}
              </Button>
            ) : null}
          </div>
        </div>
      </div>
    );
  };
  /**
   * 「精简表单」那一栏:表的标题、说明,然后**表上的每一项,按表上的顺序、用表上的名字**(后端描述符的 `form`,来自插件说的
   * 那张表)。表之外、每张工作流都有的那一两个选项(「结果取自」)另起一栏放在后面,不混进表里。
   */
  const appFormPanel = (model: GenerationEngineOption, form: AppForm) => {
    const parameters = new Map(declaredParameters(model).map((parameter) => [parameter.key, parameter]));
    const inForm = new Set(form.items.map((item) => item.key));
    const rest = [...parameters.values()].filter((parameter) => !inForm.has(parameter.key));
    const field = (item: AppFormItem) => {
      if (item.key === "prompt") return selectedPromptMode === "none" ? null : formPromptField(model, item.label || t("genPromptLabel"));
      if (item.key === "negative_prompt") return negativePromptField(item.label || undefined);
      if (item.key === "seed") return seedField(item.label || undefined);
      if (item.key === "size") return sizeField(model, item.label || undefined);
      if (item.key === "num_images") return numImagesField(model, item.label || undefined);
      if ((SOURCE_ROLES as readonly string[]).includes(item.key)) return sourceField(model, item.key as SourceRole);
      const parameter = parameters.get(item.key);
      return parameter ? declaredField(model, parameter, item.label || undefined) : null;
    };
    //: 首帧和尾帧是一对、一个控件:表上两项都在时只摆一次
    const shown = form.items.filter((item, index, all) =>
      !(item.key === "last_frame" && model.kind === "video" && all.slice(0, index).some((one) => one.key === "first_frame")));
    return (
      <>
        <ParameterSection icon={ClipboardList} title={t("genAppFormSection")}>
          {/* 列宽 minmax(0,1fr):长的副名截断,不把整栏撑出右边 */}
          <div key="head" className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-0.5" data-app-form-head="">
            <span className="text-ui-md font-semibold text-foreground">
              <Truncate>{form.title || model.model_label}</Truncate>
            </span>
            {/* 副名:这张表来自哪张工作流、哪台服务器(ADR 0045)—— 出了问题知道该去改哪张 */}
            <span className="text-ui-xs text-muted-foreground" data-entry-origin="">
              <Truncate>{namesOf(model).secondary}</Truncate>
            </span>
            {form.description.trim() ? (
              <span className="text-ui-xs leading-relaxed text-muted-foreground">
                <InlineMarkdown text={form.description} />
              </span>
            ) : null}
          </div>
          {shown.map(field)}
          {needsDigitalHumanConsent && (
            <DigitalHumanConsent key="consent" checked={digitalHumanConsent} onChange={setDigitalHumanConsent} />
          )}
        </ParameterSection>
        {rest.length > 0 && (
          <ParameterSection icon={SlidersHorizontal} title={t("genAppFormMore")}>
            {rest.map((parameter) => declaredField(model, parameter))}
          </ParameterSection>
        )}
      </>
    );
  };

  return (
    <div
      className="relative grid min-h-0 flex-1 grid-cols-[240px_minmax(0,1fr)_300px] grid-rows-[minmax(0,1fr)] max-[1180px]:grid-cols-[220px_minmax(0,1fr)] max-[820px]:grid-cols-[minmax(0,1fr)]"
      style={{ gridTemplateColumns: columns }}
    >
      {/* 和对话页同一套(lib/useResizableSidebar):同一个形状不该有两份实现,
          而这边此前一条拖柄都没有 —— 右栏那些参数挤在 300px 里,长模型名一个都看不全。 */}
      {!singleColumn && (
        <div
          className={SIDEBAR_HANDLE_CLASS}
          style={{ left: handleOffset(panels.left) }}
          onPointerDown={panels.startDrag("left")}
        />
      )}
      {showRightPanel && (
        <div
          className={SIDEBAR_HANDLE_CLASS}
          style={{ right: handleOffset(panels.right) }}
          onPointerDown={panels.startDrag("right")}
        />
      )}
      {/* 和对话栏同一个组件:分组、拖进分组、搜索、批量删,两边一份实现。
          布局也照它 —— flex 列而不是定行数的 grid:搜索框是条件渲染的,行数会变。 */}
      <StudioIndex label={t("generationSessionsTitle")}>
        <SessionList
          kind="generation"
          workspaceId={workspace.id}
          sessions={sessions.data ?? []}
          loaded={sessions.isSuccess}
          activeSessionId={activeSession?.id ?? null}
          onSelect={(id) => {
            setSessionId(id);
            window.localStorage.setItem(sessionKey, id);
          }}
          onCreate={startNewSession}
          creating={false}
          toolbar={<CreateFilterRow value={filter} onChange={setFilter} />}
          emptyTitle={t(emptySessionsKey(filter))}
          extras={(session) => ({ badge: <KindBadge kind={session.kind} /> })}
          onDeleted={(ids) => {
            // 删掉的里面有正开着的那个,就把视图放下 —— 否则右边还停在一个已经不存在的会话上。
            if (sessionId && ids.includes(sessionId)) {
              setSessionId(null);
              window.localStorage.removeItem(sessionKey);
            }
            // 会话没了,它那些生成记录也不该继续挂在任务列表里。SessionList 只管会话这一层,
            // 连带要刷的东西由调用方说 —— 它不认识生成任务。
            void qc.invalidateQueries({ queryKey: ["generation-jobs", workspace.id] });
            void qc.invalidateQueries({ queryKey: ["jobs", workspace.id, "creation"] });
          }}
        />
      </StudioIndex>

      <section className="min-h-0 overflow-hidden bg-workspace-panel grid min-w-0 grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)_auto]">
        <div className="flex min-h-14 min-w-0 flex-wrap items-center gap-2 border-b border-divider px-4 py-1.5 max-[821px]:pl-14">
          {switcher}
          <Truncate className="flex-1 text-ui-sm font-medium">{activeSession?.title ?? t("generationNewSession")}</Truncate>
          {!readOnly && (
            <Button variant={parametersOpen ? "secondary" : "ghost"} size="sm" onClick={() => setParametersOpen(!parametersOpen)} aria-pressed={parametersOpen}><SlidersHorizontal />{t("generationEngineSettings")}</Button>
          )}
        </div>
        <div className="relative grid min-h-0 min-w-0">
        <div className="flex min-w-0 flex-col gap-3.5 overflow-y-auto overflow-x-hidden px-4 pb-2.5 pt-7" ref={stick.ref}>
          {/* 第一次打开一条会话、记录还没到:按这条会话的种类摆骨架(不闪「还没有生成任务」)。外壳和真的那一轮是同一套
              (TURN_* 那几个类、结果卡的框),记录到了原地换上,版面不跳。 */}
          {/* 只摆一轮:两轮的高度常常超出这一栏,贴底跟随会先把它滚到底下,记录到了又回到顶上 —— 那正是这次要消掉的那一下跳 */}
          {activeSession && sessionJobs.isLoading && ordered.length === 0 && (
            <GenerationTurnSkeleton kind={activeSession.kind ?? "image"} bubble="w-56" />
          )}
          {!(activeSession && sessionJobs.isLoading) && ordered.length === 0 && (
            <div className="m-auto">
              <EmptyState
                icon={<Sparkles size={22} />}
                title={t("noGenerationJobs")}
                body={
                  voicedChoice
                    ? t(voicedChoice.kind === "speech" ? "createSpeechEmptyHint" : "createPodcastEmptyHint")
                    : selectedPromptMode === "none" ? undefined : t(promptHintKey)
                }
              />
            </div>
          )}
          {ordered.map((generation) => {
            const voiced = isVoicedKind(generation.kind);
            const used = voiced ? null : findGenerationOption(modelOptions, generation.provider_profile_id ?? "", generation.kind, generation.model);
            return (
            <GenerationTurn
              key={generation.id}
              generation={generation}
              engineName={voiced ? voicedEngineName(generation, voicedOptions.options, t) : used ? namesOf(used) : null}
              voiced={voiced ? {
                title: voicedTitle(generation, voiceLabels),
                bubble: voicedBubbleText(generation, podcast.labelOf),
                onRescript: readOnly ? undefined : rescriptPodcast,
              } : undefined}
              option={used}
              job={jobs.data?.find((item) => item.id === generation.job_id) ?? null}
              gallery={sessionGallery}
              onStop={readOnly ? undefined : (jobId) => stopGeneration.mutate(jobId)}
              stopping={stopGeneration.isPending && stopGeneration.variables === generation.job_id}
              onRetrieve={readOnly ? undefined : () => retrieveAgain.mutate(generation.id)}
              retrieving={retrieveAgain.isPending && retrieveAgain.variables === generation.id}
              onRepeat={readOnly ? undefined : () => repeatAgain.mutate(generation.id)}
              repeating={repeatAgain.isPending && repeatAgain.variables === generation.id}
              workspaceId={workspace.id}
            />
            );
          })}
        </div>
        <JumpToLatest stick={stick} label={t("chatJumpToLatest")} newLabel={t("chatNewBelow")} />
        </div>
        {readOnly ? (
          // 同事共享来的会话:只能看。不摆一个点了会被拒的输入框,说清楚为什么、怎么办(自己开一条)。
          <p
            role="note"
            className="mx-auto mb-3.5 mt-1.5 flex w-[min(780px,calc(100%-32px))] items-start gap-2 rounded-lg border border-dashed border-border px-3 py-2.5 text-ui-sm leading-[1.55] text-muted-foreground"
          >
            <Eye size={14} className="mt-[3px] shrink-0" aria-hidden />
            {t("generationSessionReadOnly")}
          </p>
        ) : (
          <form
            data-toast-avoid=""
            className="mx-auto mb-3.5 mt-1.5 flex w-[min(780px,calc(100%-32px))] flex-col gap-1 rounded-lg border border-border bg-control px-2.5 pb-1.5 pl-3 pt-2.5 transition-colors duration-100 focus-within:border-ring"
            onSubmit={submit}
          >
            {/* 这一次带上的资产排在输入卡顶上 —— 和对话页的附件同一排、同一种小条(ComposerChips)。
                此前挑中的资产和「@ 资产」按钮自成一行,夹在正文和底栏中间(用户截图:位置很怪)。 */}
            {!voicedChoice && (
              <ComposerChips chips={entityMentionChips(mentionedEntities, setMentionedEntities)} className="px-0.5" />
            )}
            {/* 语音、播客:同一个输入卡,里面换成要念的字 / 播客的三档(ADR 0055) */}
            {voicedChoice?.kind === "speech" ? (
              <SpeechComposerField value={prompt} onChange={setPrompt} onSubmit={submit} composer={composer} />
            ) : voicedChoice?.kind === "podcast" ? (
              <PodcastComposerFields draft={podcast} text={prompt} setText={setPrompt} onSubmit={submit} composer={composer} />
            ) : selectedPromptMode === "none" ? (
              // 这个模型不收提示词(放大、抠图这类按素材出结果的工作流):不摆一个写了也不生效的框,
              // 说清楚该做什么 —— 挂素材、调参数,直接生成。
              <p className="m-0 min-h-11 px-0 py-0.5 pb-1.5 text-ui-sm leading-[1.55] text-muted-foreground">
                {t("genPromptNotUsed")}
              </p>
            ) : (
              <Textarea
                ref={composer}
                rows={3}
                className="max-h-[220px] min-h-11 w-full min-w-0 resize-none border-0 bg-transparent px-0 py-0.5 pb-1.5 text-ui-md leading-[1.55] shadow-none outline-none focus-visible:ring-0"
                value={prompt}
                aria-label={t("genPromptLabel")}
                placeholder={t(promptHintKey)}
                onChange={(event) => {
                  setPrompt(event.target.value);
                  event.target.style.height = "auto";
                  event.target.style.height = `${Math.min(event.target.scrollHeight, 220)}px`;
                }}
                onKeyDown={(event) => {
                  //: ⌘Enter / Ctrl+Enter 生成,回车换行 —— 和画板、音频格子同一个键(UC-04:一下回车就花一次钱太容易按出来)
                  if (isSubmitChord(event)) {
                    event.preventDefault();
                    submit(event);
                  }
                }}
              />
            )}
            {/* 底栏和对话页同一个排法:左边一排小按钮(引用、模板、优化),然后是模型;右边发送。 */}
            <div className="flex items-center justify-between gap-1.5 pt-0.5">
              <div className="flex min-w-0 items-center gap-1.5">
                {selectedModel && selectedModel.kind !== "audio" && (
                  <EntityMentionButton workspaceId={workspace.id} value={mentionedEntities} onChange={setMentionedEntities} />
                )}
                {selectedModel?.kind === "image" && selectedPromptMode !== "none" && (
                  <PromptTemplateButton onPick={(template) => setPrompt((current) => withTemplate(current, template))} />
                )}
                {selectedModel?.kind === "image" && selectedPromptMode !== "none" && (
                  <IconButton
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    // createGeneration 是**别的**操作在跑,那是 disable;自己在跑才是 loading。
                    disabled={!prompt.trim() || chatModelMissing || createGeneration.isPending}
                    loading={optimizePrompt.isPending}
                    onClick={() => optimizePrompt.mutate()}
                    label={t("optimizePrompt")}
                    disabledReason={chatModelMissing ? t("optimizePromptNeedsChatModel") : undefined}
                  >
                    <Wand2 size={14} />
                  </IconButton>
                )}
                {/* 模型是一个能点的东西(和对话页的模型选择器同一种样子):点开右边的「引擎参数」,焦点落到模型选择上;
                    栏开着时这枚按钮是「按下」的样子(和顶上那颗「引擎参数」一样),点它把模型那一块亮一下。 */}
                {chipName && (
                  //: 悬停说全名(按钮上的可能被截断)和点下去会去哪儿。
                  <Hint label={twoLayerTitle(chipName)} hint={t("generationEngineChipHint")}>
                    <button
                      type="button"
                      onClick={showEngineSettings}
                      aria-label={t("generationEngineSettings")}
                      aria-controls={enginePanelId}
                      data-engine-chip=""
                      data-active={panelOpen ? "" : undefined}
                      className="inline-flex h-7 min-w-0 max-w-[240px] cursor-pointer items-center gap-1 rounded-md border border-field-border bg-field px-2 text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:border-primary focus-visible:outline-none data-[active]:border-primary/40 data-[active]:bg-accent data-[active]:text-foreground"
                    >
                      <Truncate>{chipName.primary}</Truncate>
                      <SlidersHorizontal size={12} className="shrink-0 opacity-60" />
                    </button>
                  </Hint>
                )}
                {/* 会话记着的模型用不了:按钮上照样写它(标着需要升级 / 用不了),点开右栏看原因和出路 */}
                {!chipName && missingEngine && (
                  <Hint label={twoLayerTitle(missingModelNames(missingModel.missing, t))} hint={missingModel.missing?.reason ?? null}>
                    <button
                      type="button"
                      onClick={showEngineSettings}
                      aria-label={t("generationEngineSettings")}
                      aria-controls={enginePanelId}
                      data-engine-chip=""
                      data-missing=""
                      className="inline-flex h-7 min-w-0 max-w-[260px] cursor-pointer items-center gap-1 rounded-md border border-warning/40 bg-field px-2 text-xs text-warning transition-colors hover:text-foreground focus-visible:border-primary focus-visible:outline-none"
                    >
                      <TriangleAlert size={12} className="shrink-0" aria-hidden />
                      <Truncate>{missingModelLabel(missingModel.missing, t)}</Truncate>
                    </button>
                  </Hint>
                )}
                {/* 参数栏开着时,「一个模型都没有」由那边的提示条说,这里不再摆第二个入口。 */}
                {!(noGenerationModels && parametersOpen) && !missingEngine && (
                  <GenerationModelGate hasModel={Boolean(chipName)} loading={generationModelsLoading} section={settingsSection} />
                )}
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {/* 提交键说在输入框旁边:回车只是换行 */}
                {voicedCounter && (
                  <span
                    className={cn("text-ui-2xs tabular-nums text-muted-foreground", voicedCounter.over && "font-semibold text-destructive")}
                    data-voiced-count=""
                    aria-live="polite"
                  >
                    {voicedCounter.label}
                  </span>
                )}
                <span className="text-ui-2xs text-muted-foreground max-[640px]:hidden" data-submit-hint="">
                  {t("genSubmitHint").replace("{keys}", formatCombo(SUBMIT_COMBO))}
                </span>
                <IconButton
                  type="submit"
                  variant="default"
                  size="icon"
                  className="shrink-0 rounded-full"
                  label={t("generate")}
                  shortcut={formatCombo(SUBMIT_COMBO)}
                  disabled={voicedChoice ? !voicedCanSubmit : !canSubmitText || !selectedModel || !selectedAdapterAvailable}
                  loading={voicedChoice ? createVoiced.isPending : createGeneration.isPending}
                  disabledReason={missingEngine && !selectedModel ? t("genModelMissingCannotSend") : undefined}
                >
                  <Send size={15} />
                </IconButton>
              </div>
            </div>
          </form>
        )}
      </section>

      {/* 参数栏和对话页右侧的智能体检查器是同一件东西:同一侧、同为"若干块各自成组"。
          所以壳子也用同一个(InspectorCard)—— 标题行的字号字重、块与块之间的 gap-6、
          正文的 p-4,都跟着那边走,不再自成一套。 */}
      <aside
        ref={enginePanel}
        id={enginePanelId}
        className={cn(
          "flex min-h-0 min-w-0 flex-col border-l border-divider bg-workspace-panel",
          !panelOpen && "hidden",
          panelOpen && narrowLayout && "workspace-overlay absolute inset-y-0 right-0 z-30 w-[min(340px,100%)] shadow-xl",
        )}
        aria-label={t("generationEngineSettings")}
      >
        {/* 标题行**不跟着滚** —— 滚动挪到下面那层。此前整个 aside 是滚动容器,往下翻两栏,
            标题和那个关闭按钮就一起滚出视野。高度对齐左边工具栏的 min-h-14,两条分隔线连成一条。 */}
        <div className="flex min-h-14 shrink-0 items-center justify-between gap-2 border-b border-divider px-4">
          <h2 className="m-0 text-ui-sm font-semibold">{t("generationEngineSettings")}</h2>
          <IconButton variant="ghost" size="icon-xs" label={t("close")} onClick={() => setParametersOpen(false)}>
            <X />
          </IconButton>
        </div>

        <div className="grid min-h-0 min-w-0 flex-1 grid-cols-[minmax(0,1fr)] content-start gap-6 overflow-y-auto overflow-x-hidden p-4">
          {noGenerationModels && (
            <ConfigNotice
              message={t("generationNoModels")}
              actionLabel={t("wfGoConfigure")}
              section={settingsSection}
              className="items-center gap-[7px] rounded-lg px-[9px] py-2 text-ui-xs leading-[1.45]"
              textClassName="line-clamp-3"
              actionClassName="self-center"
            />
          )}
          {selectedModel && !selectedAdapterAvailable && (
            <div className="flex items-center gap-1.5 text-ui-xs text-destructive">
              <CircleAlert size={13} />
              {t("generationAdapterUnavailable").replace("{engine}", namesOf(selectedModel).primary)}
            </div>
          )}
          {/* 模型选择器**有模型就摆出来**,哪怕还没选中任何一个:没设默认时它显示「选择模型」等人选,
              而不是拿清单第一项顶上 —— 那样选中的就不是谁的选择(见 pickGenerationOption)。 */}
          {(pickerModelOptions.length > 0 || pickerVoicedOptions.length > 0) && (
            <div
              data-engine-section=""
              data-flash={engineFlash ? "" : undefined}
              className="-m-2 rounded-lg p-2 transition-colors duration-500 data-[flash]:bg-accent data-[flash]:duration-150"
            >
            <ParameterSection icon={Cpu} title={t("genSectionEngine")}>
              <ParameterField label={t("wfModelPreset")}>
                <div data-engine-picker="" className="contents">
                {/* 模型清单按能力分组,且**一定**是长清单 —— 直接给可搜索的那一版,不走阈值。
                    每行的图标撤了:它编码的是"图片还是视频",而分组标题已经说了同一件事,
                    搜索框在的时候那枚重复的小图标只是占掉了名字的位置。 */}
                <SearchableSelect
                  value={selectedModel?.value ?? voicedChoice?.value ?? ""}
                  missingLabel={missingEngine ? missingModelLabel(missingModel.missing, t) : null}
                  onValueChange={selectEngine}
                  options={[
                    ...modelGroups.flatMap((group) =>
                      group.models.map((model) => ({
                        value: model.value,
                        //: 有表单的工作流是一小组:小标题工作流名 + 连接名,下面「完整工作流」和每张表单(后端已经把它们排在一起)
                        ...generationPickerEntry(model, formed, t),
                        group: capabilityLabel(group.kind),
                      })),
                    ),
                    //: 语音(每个配音引擎)、播客(火山播客):引擎来自配音那一族,不进生成目录(ADR 0055)
                    ...pickerVoicedOptions.map((option) => ({
                      value: option.value,
                      ...voicedPickerEntry(option, t),
                      group: capabilityLabel(option.kind),
                    })),
                  ]}
                  placeholder={t("genPickModel")}
                  emptyText={t("cmdkEmpty")}
                  className={PARAMETER_CONTROL_CLASS}
                />
                </div>
                {missingEngine && (
                  <MissingModelNotice missing={missingModel.missing} pending={missingModel.pending} workspaceId={workspace.id}
                                      onPickAnother={pickAnotherModel} className="mt-1.5" />
                )}
                {/* 会话锁族:有记录的会话下拉只列同一族,说一句为什么、想换怎么办 */}
                {familyLocked && activeSession?.kind && (
                  <span className="mt-1 block text-ui-2xs leading-[1.45] text-muted-foreground" data-family-locked="">
                    {t("createFamilyLocked").replace("{kind}", capabilityLabel(activeSession.kind))}
                  </span>
                )}
              </ParameterField>
              {/* 选中的是某台 ComfyUI 上的一张工作流:在工作台里打开它(画布 + 模型库、缺失项、应用、运行,ADR 0038) */}
              {selectedModel?.plugin_instance_id && (
                <OpenInWorkbench
                  key={`${selectedModel.plugin_instance_id}:${selectedModel.model}`}
                  instanceId={selectedModel.plugin_instance_id}
                  instanceName={selectedModel.profile_name || selectedModel.provider}
                  path={selectedModel.group?.id ?? selectedModel.model}
                  workspaceId={workspace.id}
                />
              )}
            </ParameterSection>
            </div>
          )}
          {voicedChoice?.kind === "speech" && <SpeechSettings voice={speech} workspaceId={workspace.id} />}
          {voicedChoice?.kind === "podcast" && (
            <PodcastSettings draft={podcast} engine={voicedChoice.engine} workspaceId={workspace.id} />
          )}
          {/* 作者给这张工作流挑了一张表(精简表单):右栏就是那张表 —— 表上的项、表上的顺序、表上的名字,
              主提示词指向下面的输入框。和工作流库里那张表的「预览」说的是同一件事。 */}
          {selectedModel && selectedForm && appFormPanel(selectedModel, selectedForm)}
          {selectedModel && !selectedForm && (
            <>

              {/* 出片规格 = "出多大、出几张、出多久、带不带声" —— 看一眼就知道成片长什么样的那几栏。
                  怎么出(seed、反向提示词、各家自己加的开关)在下面那块。 */}
              <ParameterSection icon={Ratio} title={t("genSectionOutput")}>
                {/* 尺寸**不属于任何一支**:图像收 `1024x1024`,万相视频收 `832*480`,都是"出多大"。
                    此前它锁在 image 分支里,于是一个声明了 size 的视频模型连这一栏都不出现 ——
                    参数描述符说了话而界面没听。 */}
                {sizeField(selectedModel)}
                {isImageModel && numImagesField(selectedModel)}
                {supportsParameter(selectedModel, "resolution") && selectedResolutions.length > 0 && (
                  <ParameterField label={t("genResolution")}>
                    <Select
                      value={generationConfig.resolution}
                      onValueChange={(value) => {
                        const durations = durationChoices(selectedModel, value);
                        setGenerationConfig((current) => ({
                          ...current,
                          resolution: value,
                          durationSeconds: durations.length > 0 && !durations.includes(Number(current.durationSeconds))
                            ? String(durations[0])
                            : current.durationSeconds,
                        }));
                      }}
                    >
                      <SelectTrigger className={PARAMETER_CONTROL_CLASS}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {selectedResolutions.map((resolution) => (
                          <SelectItem key={resolution} value={resolution}>
                            {resolution}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </ParameterField>
                )}
                {!isImageModel && supportsParameter(selectedModel, "aspect_ratio") && selectedAspectRatios.length > 0 && (
                  <ParameterField label={t("genAspectRatio")}>
                    <Select value={generationConfig.aspectRatio} onValueChange={(value) => setConfigValue("aspectRatio", value)}>
                      <SelectTrigger className={PARAMETER_CONTROL_CLASS}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {selectedAspectRatios.map((ratio) => (
                          <SelectItem key={ratio} value={ratio}>
                            {ratio}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </ParameterField>
                )}
                {!isImageModel && supportsParameter(selectedModel, "duration_seconds") && (
                  <ParameterField
                    label={t("genDuration")}
                    hint={audioDurationRange ? `${audioDurationRange.min}–${audioDurationRange.max}s` : undefined}
                  >
                    {selectedDurations.length > 0 && !durationIsFreeInput ? (
                      <Select value={generationConfig.durationSeconds} onValueChange={(value) => setConfigValue("durationSeconds", value)}>
                        <SelectTrigger className={PARAMETER_CONTROL_CLASS}>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {selectedDurations.map((duration) => (
                            <SelectItem key={duration} value={String(duration)}>
                              {duration === -1 ? t("genDurationAuto") : `${duration}s`}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      <Input
                        className={PARAMETER_CONTROL_CLASS}
                        type="number"
                        aria-label={t("genDuration")}
                        min={audioDurationRange?.min}
                        max={audioDurationRange?.max}
                        // 时长空着 = 不发,让模型自己定(音频按歌词长短,视频用它自己的默认)。
                        placeholder={t("genDurationAuto")}
                        value={generationConfig.durationSeconds}
                        onChange={(event) => setConfigValue("durationSeconds", event.target.value)}
                      />
                    )}
                  </ParameterField>
                )}
                {/* 数字人(ADR 0028):成片长度跟着驱动音频走的模型不收时长,这一栏写明它跟着谁;
                    会截掉音频后半段的模型,所选时长短于音频时提醒。 */}
                {!isImageModel && durationFollowsRole(selectedModel) && (
                  <ParameterField label={t("genDuration")}>
                    <DurationFollowsNote role={durationFollowsRole(selectedModel)} />
                  </ParameterField>
                )}
                {!isImageModel && supportsParameter(selectedModel, "duration_seconds") && (
                  <TruncationHint
                    model={selectedModel}
                    frames={generationConfig.frames}
                    durationSeconds={generationConfig.durationSeconds}
                    bounds={durationRange(selectedModel) ?? {}}
                    onUseSourceLength={(seconds) => setConfigValue("durationSeconds", String(seconds))}
                  />
                )}
                {supportsInstrumental && (
                  <ParameterField label={t("genInstrumental")}>
                    <Select
                      value={generationConfig.instrumental ? "true" : "false"}
                      onValueChange={(value) =>
                        setGenerationConfig((current) => ({ ...current, instrumental: value === "true" }))
                      }
                    >
                      <SelectTrigger className={PARAMETER_CONTROL_CLASS} aria-label={t("genInstrumental")}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="false">{t("genWithVocals")}</SelectItem>
                        <SelectItem value="true">{t("genInstrumentalOnly")}</SelectItem>
                      </SelectContent>
                    </Select>
                  </ParameterField>
                )}
                {!isImageModel && supportsParameter(selectedModel, "generate_audio") && (
                  <ParameterField label={t("genGenerateAudio")}>
                    <Select
                      value={generationConfig.generateAudio ? "true" : "false"}
                      onValueChange={(value) =>
                        setGenerationConfig((current) => ({ ...current, generateAudio: value === "true" }))
                      }
                    >
                      <SelectTrigger className={PARAMETER_CONTROL_CLASS}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="true">{t("boardWithSound")}</SelectItem>
                        <SelectItem value="false">{t("boardMuted")}</SelectItem>
                      </SelectContent>
                    </Select>
                  </ParameterField>
                )}
              </ParameterSection>

              {/* 歌词:要唱的字,和提示词(怎么唱)分开。选了纯音乐就灰掉 —— 纯音乐没有歌词。 */}
              <ParameterSection icon={Music} title={t("genLyrics")}>
                {supportsLyrics && (
                  <LyricsField
                    value={generationConfig.lyrics}
                    onChange={(value) => setGenerationConfig((current) => ({ ...current, lyrics: value }))}
                    limit={lyricsLimit(selectedModel)}
                    disabled={supportsInstrumental && generationConfig.instrumental}
                  />
                )}
              </ParameterSection>

              {/* 挂进去的素材:首尾帧、参考图/视频/音频、要编辑或续写的那段片子。
                  它们都是"你给模型什么",和上面那块"模型给你什么"正好是两头。 */}
              <ParameterSection icon={Images} title={t("genSectionSources")}>
                {isImageModel && supportsReferenceImage && referenceImageField(selectedModel)}
                {supportsFirstFrame && keyframesField(selectedModel)}
                {videoInputRoles.map((role) => slotsField(selectedModel, role, t(VIDEO_INPUT_HINTS[role])))}
                {needsDigitalHumanConsent && (
                  <DigitalHumanConsent checked={digitalHumanConsent} onChange={setDigitalHumanConsent} />
                )}
                {/* 「参考」那一句只说一遍:三个参考控件挨在一起,每个都重复一次就成了噪音。 */}
                {videoReferenceRoles.map((role, index) => slotsField(selectedModel, role, index === 0 ? t("genReferenceHint") : undefined))}
                {/* 音频模型的输入:要配声的视频、参考 / 被翻唱的音频、图生音乐的图。同一个控件,
                    提示语换成音频上的意思。 */}
                {selectedAudioRoles.map((role) => slotsField(selectedModel, role, t(AUDIO_SOURCE_HINTS[role])))}
              </ParameterSection>

              {/* 调参:seed、反向提示词,以及各家自己加的开关和枚举。它们决定"怎么出",
                  多数时候不用动 —— 所以排在最后,而不是和尺寸、张数混在一起。 */}
              <ParameterSection icon={SlidersHorizontal} title={t("genSectionAdvanced")}>
                {/* 种子与反向提示词**不分种类**:描述符声明了就给控件(generationParameters 的 shared
                    那一段本来就不分种类地发它们)。 */}
                {supportsParameter(selectedModel, "seed") && seedField()}
                {supportsNegativePrompt && negativePromptField()}
                {booleanParameterKeys(selectedModel).filter((key) => !DEDICATED_BOOLEANS.has(key)).map((key) => {
                  const labelKey = GENERATION_BOOLEAN_LABELS[key];
                  return (
                    <ParameterField key={key} label={labelKey ? t(labelKey) : key}>
                      <Select
                        value={generationConfig.booleanParameters[key] ? "true" : "false"}
                        onValueChange={(value) => setGenerationConfig((current) => ({
                          ...current,
                          booleanParameters: { ...current.booleanParameters, [key]: value === "true" },
                        }))}
                      >
                        <SelectTrigger className={PARAMETER_CONTROL_CLASS}>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="true">{t("wfGenToggleOn")}</SelectItem>
                          <SelectItem value="false">{t("wfGenToggleOff")}</SelectItem>
                        </SelectContent>
                      </Select>
                    </ParameterField>
                  );
                })}
                {declaredParameters(selectedModel).map((parameter) => declaredField(selectedModel, parameter))}
                {parameterChoiceEntries(selectedModel).map(([key, choices]) => {
                  const labelKey = GENERATION_PARAMETER_LABELS[key];
                  const hintKey = GENERATION_PARAMETER_HINTS[key];
                  return (
                    <ParameterField key={key} label={labelKey ? t(labelKey) : key} hint={hintKey ? t(hintKey) : undefined}>
                      <Select
                        value={generationConfig.enumParameters[key] ?? capabilityString(selectedModel, `default_${key}`, choices[0] ?? "")}
                        onValueChange={(value) => setGenerationConfig((current) => ({
                          ...current,
                          enumParameters: { ...current.enumParameters, [key]: value },
                        }))}
                      >
                        <SelectTrigger className={PARAMETER_CONTROL_CLASS}>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {choices.map((choice) => <SelectItem key={choice} value={choice}>{choice}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </ParameterField>
                  );
                })}
              </ParameterSection>
            </>
          )}
        </div>
      </aside>
    </div>
  );
}

/**
 * 生成出来的那段视频。框按片子自己的比例(元数据回来之前先按 16:9),最高 420px —— 竖屏片子在框里左右留黑,
 * 不把气泡撑得一屏高。
 */
function GeneratedVideo({ assetId, onExpand }: { assetId: string; onExpand: (src: string) => void }) {
  const [ratio, setRatio] = React.useState(16 / 9);
  const src = assetFileUrl(assetId);
  return (
    <div
      data-generated-video={assetId}
      className={VIDEO_FRAME_CLASS}
      style={{ aspectRatio: ratio }}
    >
      <VideoPlayer
        key={assetId}
        assetSrc={src}
        onNaturalSize={(width, height) => setRatio(width / height)}
        onExpand={() => onExpand(src)}
        className="bg-[#05070a]"
      />
    </div>
  );
}

/**
 * 一轮生成的外壳:整轮、提示词那一行与气泡、结果那一行、图框、视频框。GenerationTurn 和首次加载的骨架(GenerationTurnSkeleton)**共用这几个类**,
 * 不各写一份 —— 此前骨架是一条 16px 高的细胶囊加一块 320 的方块,和真的气泡、结果卡对不上,记录一到整屏往下跳
 * (维护者:「实际位置似乎和真实的不一样」)。改外壳就改这里,两边一起变。
 */
const TURN_CLASS = "group/gen grid w-full max-w-[780px] shrink-0 gap-2.5 self-center";
const TURN_PROMPT_ROW_CLASS = "grid justify-items-end gap-1";
const TURN_PROMPT_BUBBLE_CLASS =
  "w-fit max-w-[min(560px,82%)] justify-self-end whitespace-pre-wrap break-words rounded-lg rounded-br bg-secondary px-3 py-[9px] text-ui-md leading-[1.65] text-foreground";
const TURN_RESULT_ROW_CLASS = "grid min-h-7 justify-items-start gap-[7px] pb-2 pt-0.5";
/**
 * 产出下面那一行元信息(模型 · 用时 · 费用)的外框,和 TurnMeta 摆出来的 `<div className="justify-self-start"><small …>` 同一串。
 * TurnMeta 归失败卡那一路(卡头里也用它,正在抽成共用组件),这里不去改它的写法;两边一字不差由 Skeletons.dom.test 钉着。
 */
const TURN_META_ROW_CLASS = "justify-self-start";
const TURN_META_CLASS = "flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 text-ui-xs text-muted-foreground";
/** 结果卡的框:图一行几张(画的是缩略图,320px 宽、最高 360px)、视频一格(最宽 560px、最高 420px,元数据回来之前按 16:9)。 */
const IMAGE_ROW_CLASS = "flex max-w-[min(720px,100%)] flex-wrap gap-1.5";
const IMAGE_FRAME_CLASS = "block rounded-lg border border-border";
const IMAGE_SINGLE_CLASS = "max-h-[360px] w-auto max-w-full";
const VIDEO_FRAME_CLASS = "max-h-[420px] w-full max-w-[min(560px,100%)] overflow-hidden rounded-lg border border-border";

/**
 * 第一次打开一条会话、记录还没到时的一轮:**按这条会话的种类**摆 —— 外壳是真的那几个类(见上),结果那一格是真卡片的框:
 * 图是一张缩略图那么大的方图(320px 加边框),视频是 16:9 的那一格,音乐、语音、播客是音频卡(和生成中的占位同一个壳,PendingAudioList),
 * 播客多一行对谈稿的按钮。提示词和脚注各占一行字。记录到了原地换上,不挪位置。
 */
function GenerationTurnSkeleton({ kind, bubble }: { kind: string; bubble: string }) {
  return (
    <article className={TURN_CLASS} data-generation-skeleton={kind} aria-hidden>
      <div className={TURN_PROMPT_ROW_CLASS}>
        <div className={TURN_PROMPT_BUBBLE_CLASS} data-skeleton-prompt="">
          <SkeletonLine className={bubble} />
        </div>
        {/* 真的那一轮下面有一行悬停才显形的脚注(复制 + 时间),透明但占高度:骨架也留着这一行 */}
        <MessageFooter content="" className="justify-end opacity-0" />
      </div>
      <div className={TURN_RESULT_ROW_CLASS}>
        {isAudibleKind(kind) ? (
          <>
            <PendingAudioList count={1} running />
            {kind === "podcast" && <PodcastDialogueSkeleton />}
          </>
        ) : kind === "video" ? (
          <div className={VIDEO_FRAME_CLASS} style={{ aspectRatio: 16 / 9 }} data-skeleton-frame="video">
            <Skeleton surface className="h-full w-full rounded-none" />
          </div>
        ) : (
          <div className={IMAGE_ROW_CLASS}>
            {/* 真的那张画的是缩略图(宽 320,后端 media/thumbnails.THUMBNAIL_WIDTH)加一圈边框;比例要等记录到了才知道,先按方图 */}
            <div className={cn(IMAGE_FRAME_CLASS, "max-w-full overflow-hidden")} data-skeleton-frame="image">
              <Skeleton surface className="aspect-square w-[320px] max-w-full rounded-none" />
            </div>
          </div>
        )}
        <div className={TURN_META_ROW_CLASS}>
          <small className={TURN_META_CLASS}>
            <SkeletonLine className="w-40" />
          </small>
        </div>
      </div>
    </article>
  );
}

/** 一条生成走到哪儿了。`stopped`:有人把它停下了(不是跑挂了,见后端 GenerationJobOut.stopped)。 */
type TurnStatus = "queued" | "running" | "succeeded" | "failed" | "stopped";

/** 停下之后多久之内还等它的账(插件停远端那一次 + 宽限,见后端 plugins.runtime.CANCEL_GRACE_SECONDS)。 */
const STOP_SETTLE_MS = 90_000;

/** 刚停下、账还没记上的那一条。 */
function settlingAfterStop(generation: GenerationJob): boolean {
  if (!generation.stopped || generation.cost_confidence || (generation.costs ?? []).length > 0) return false;
  return Date.now() - parseServerTime(generation.updated_at).getTime() < STOP_SETTLE_MS;
}

function turnStatus(generation: GenerationJob, job: JobSummary | null): TurnStatus {
  //: 任务已经落了「已取消」、记录还没抄下「已停止」(抄在落终态之后的收拾里,见后端 record_failure)的那一下,也是停下了。
  if (generation.stopped || job?.status === "cancelled") return "stopped";
  // job 行可能已被任务中心「清空已结束」删掉(记录长存、job_id 置空):有产物即成功;记录上记着失败原因、
  // 或者任务已经不在了,即失败;只有任务还在而列表没拉到时才视作排队中。
  const status =
    job?.status ?? (generation.result_asset_id ? "succeeded" : generation.job_id && !generation.error ? "queued" : "failed");
  return status === "queued" || status === "running" || status === "succeeded" ? status : "failed";
}

function GenerationTurn({
  generation,
  engineName: knownName,
  voiced,
  option,
  job,
  gallery,
  onStop,
  stopping,
  onRetrieve,
  retrieving,
  onRepeat,
  repeating,
  workspaceId,
}: {
  generation: GenerationJob;
  /** 用的哪条连接上的哪个模型,两层名字(ADR 0045):脚注写主名,副名(来自哪张工作流、哪台服务器)在悬停里。连接或模型
   *  已经不在选项里了是 null:问一下它叫什么、现在怎么了(「krea2-text-2-image 的表单 · 需要升级」),不露编号。 */
  engineName: TwoLayerName | null;
  /** 语音、播客的记录(ADR 0055):结果卡标题(音色名 / 播客主题)、气泡里写什么、「改稿再念」(只读的会话不给)。 */
  voiced?: { title: string; bubble: string; onRescript?: (turns: ScriptTurn[], speakers: string[]) => void };
  /** 这条用的那个模型(还在选项里的话):占位按它说的「一遍交回几份」摆。 */
  option: GenerationOption | null;
  job: JobSummary | null;
  gallery?: ImagePreviewItem[];
  /** 停下这一条(取消它的任务);只读的会话不给。 */
  onStop?: (jobId: string) => void;
  stopping?: boolean;
  /** 重新取回这一条(只在后端说 `retrievable` 时摆出来);只读的会话不给。 */
  onRetrieve?: () => void;
  retrieving?: boolean;
  /** 再来一次(只在后端说 `repeatable`、记着的模型还在时摆出来);只读的会话不给。 */
  onRepeat?: () => void;
  repeating?: boolean;
  /** 「去工作流库升级」开的是这个工作区里那个连接的工作流库 */
  workspaceId: string;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const { openImagePreview } = useImagePreview();
  const status = turnStatus(generation, job);
  //: 这条用的模型已经不在选项里:问它叫什么、现在怎么了 —— 脚注写「krea2-text-2-image 的表单 · 需要升级」,不写
  //: `plugin:dev.mosael.comfyui · krea2-text-2-image.json#app` 这种编号
  const gone = useMissingModel(knownName ? null : { provider_profile_id: generation.provider_profile_id ?? "",
                                                   model: generation.model, kind: generation.kind });
  const engineName = knownName ?? {
    primary: missingModelLabel(gone.missing, t),
    secondary: missingModelNames(gone.missing, t).secondary,
  };
  //: 这一条生成的**全部**产出。后端给 result_asset_ids(封面排第一);一次只出一份时它就是
  //: 那一份 —— 不为「一份」和「多份」各写一套渲染。
  const outputs = generation.result_asset_ids?.length
    ? generation.result_asset_ids
    : generation.result_asset_id
      ? [generation.result_asset_id]
      : [];
  const timestamp = generation.created_at ?? job?.created_at ?? null;
  const pending = status === "queued" || status === "running";
  // 节拍时钟:在跑、在排时每秒刷计时;空闲 30s 一拍让「x 分钟前」不冻住。
  // (轮询回包无变化时 react-query 不触发重渲,光靠轮询计时会停走。)
  const now = useNow(pending ? 1000 : 30_000);
  //: 音频可以只给歌词(或者给视频配声什么字都不给):气泡里就显示歌词,都没有时说「按素材生成」。
  const requestParameters = (generation.request.parameters ?? {}) as Record<string, unknown>;
  const prompt = voiced
    ? voiced.bubble
    : String(generation.request.prompt ?? "").trim() ||
      String(requestParameters.lyrics ?? "").trim() ||
      (generation.kind === "audio" ? t("genAudioFromSources") : "");
  //: 还没结束的那一条,已用多久写在进度那一行里;结束了才进脚注(用了多久)。
  const elapsed = pending ? elapsedSecondsBetween(timestamp, now) : null;
  const finishedSeconds = pending ? null : elapsedSecondsBetween(timestamp, job?.updated_at ?? generation.updated_at);
  const durationLabel =
    typeof finishedSeconds === "number" ? t("usageDuration").replace("{t}", formatElapsedSeconds(finishedSeconds)) : "";
  // 计费:与对话页同一套格式化(lib/money)。有已知费用显示金额 —— 每个币种一笔,不相加;
  // 有事件但无定价显示「未定价」;失败了没扣钱说「未扣费」(不是「费用 US$0.00」:没价的模型那笔 0 的币种是猜的)。
  // 停下的那一条同一句:服务商那边还没扣钱是「未扣费」,停晚了照样扣的照实写金额(见后端 runner._settle_after_cancel)。
  const costLabel =
    (generation.costs ?? []).length > 0
      ? t("usageCost").replace("{cost}", formatCosts(generation.costs, locale))
      : generation.cost_confidence === "unknown"
        ? t("usageCostUnknown")
        : generation.cost_confidence === "not_billed"
          ? t("usageCostNotBilled")
          : "";
  //: 没交回产出的那一条(停下的、跑挂了的)是一张卡:这一条的元信息(模型、用时、费用、时间)收进卡头右边,不在卡外另起一行,
  //: 时间也不再单独飘在提示词下面 —— 此前看不出那行小字和那个「30 分钟前」是谁的。
  const noOutput = outputs.length === 0 && (status === "stopped" || status === "failed");
  const meta = (
    <TurnMeta engineName={engineName} parts={[durationLabel, costLabel]} time={noOutput ? timestamp : null} />
  );
  return (
    <article className={TURN_CLASS} data-generation-status={status}>
      <div className={TURN_PROMPT_ROW_CLASS}>
        {/* 不收提示词的工作流(放大、抠图、一张不填字的 ComfyUI 图)这一轮没写字:不摆一个空气泡,时间照旧在 */}
        {prompt ? (
          <div className={TURN_PROMPT_BUBBLE_CLASS} data-generation-prompt="">
            {prompt}
          </div>
        ) : null}
        {/* 和对话页的用户气泡同一个脚注:复制 + 时间。此前这里只有一个裸 <time>,
            没法把提示词捞出来 —— 而提示词正是最常要复制去改一版再生成的东西。没交回产出的那一条,时间在卡头里。 */}
        {prompt || !noOutput ? (
          <MessageFooter
            content={prompt}
            className="justify-end opacity-0 transition-opacity duration-[120ms] group-hover/gen:opacity-100"
          >
            {noOutput ? null : <MessageTime iso={timestamp} />}
          </MessageFooter>
        ) : null}
        {/* `@` 到的资产挂了几张参考图、没挂上的为什么(ADR 0027)。全挂上了就什么都不写。 */}
        <EntityReceiptNote receipt={entityReceipt(generation.request)} />
        {voiced && <TruncatedNote generation={generation} />}
      </div>
      <div className={TURN_RESULT_ROW_CLASS}>
        {outputs.length > 0 && isAudibleKind(generation.kind) ? (
          //: 一次可能交回几首(Suno 一次两首):每一首一张卡,而不是只放封面那一首。语音、播客同一张卡(ADR 0055):
          //: 波形、真时长、下载、在素材库里打开;播客下面多一块对谈稿和「改稿再念」。
          <>
            <GeneratedAudioList assetIds={outputs} title={voiced?.title || prompt.split("\n")[0]?.slice(0, 60) || generation.model} />
            {generation.kind === "podcast" && (
              <PodcastDialogue assetId={outputs[0]} generation={generation} onRescript={voiced?.onRescript} />
            )}
          </>
        ) : generation.result_asset_id && generation.kind === "video" ? (
          //: 全站共用的播放器(不是原生 controls):右下角那颗「全屏」开的是同一个灯箱,和本会话的其他产出一起左右翻。
          <GeneratedVideo
            assetId={generation.result_asset_id}
            onExpand={(src) => openImagePreview({ src, title: String(generation.request.prompt ?? generation.model), video: true, gallery })}
          />
        ) : outputs.length > 0 ? (
          //: **照 result_asset_ids 出图,不是只出封面。** 图像接口的 n 选了几就出几张,
          //: 只画第一张的话,用户按 4 张付了钱、界面上只多出 1 张(另外 3 张在素材库里
          //: 躺着,而他不知道)。
          //:
          //: **按高度定尺寸,不按宽度铺满。** 此前多张时每张至少占半行、还会伸展:一张竖图(1080×1920)将近 500px 高,
          //: 单数的最后一张被拉成整行宽(维护者:「生成页面的图片可以稍微小一些 太大了」)。现在一张最高 360px,
          //: 多张时每张 220px 高、宽跟着比例走、不伸展,一行排得下几张排几张;点开看大图。
          <div className={IMAGE_ROW_CLASS}>
            {outputs.map((assetId) => (
              <IconButton
                unstyled
                key={assetId}
                type="button"
                label={t("imagePreviewTitle")}
                className={cn(
                  "cursor-zoom-in border-0 bg-transparent p-0 focus-visible:rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[3px] focus-visible:outline-ring",
                  "inline-block max-w-full shrink-0",
                )}
                onClick={() =>
                  openImagePreview({
                    src: assetPreviewUrl(assetId),
                    title: String(generation.request.prompt ?? generation.model),
                    gallery,
                  })
                }
              >
                <img
                  className={cn(
                    IMAGE_FRAME_CLASS,
                    outputs.length > 1 ? "h-[220px] w-auto max-w-full object-contain" : IMAGE_SINGLE_CLASS,
                  )}
                  src={assetThumbnailUrl(assetId)}
                  alt=""
                  loading="lazy"
                />
              </IconButton>
            ))}
          </div>
        ) : status === "stopped" ? (
          <GenerationStoppedCard meta={meta} />
        ) : status === "failed" ? (
          //: 原因读**生成记录自己**存的那份 —— 任务会被清掉,记录不会(见后端 generation.runner.record_failure)。
          //: 那一句人话、原文、认得出的原因都由后端出(error_summary / error_detail / error_hint,和画板格子同一个来源,见后端
          //: domain/failure_summary);能做什么也按后端说的:能不能照原样再来(repeatable)、能不能重新取回(retrievable)。
          //: 记着的模型用不了(knownName 是 null)时不摆「再来一次」—— 修法是升级的给「去工作流库升级」。
          <GenerationFailureCard
            summary={generation.error_summary ?? ""}
            detail={generation.error_detail ?? null}
            fix={generation.error_hint ?? null}
            copyText={generation.error ?? ""}
            meta={meta}
            repeat={onRepeat && generation.repeatable && knownName ? { run: onRepeat, pending: repeating } : undefined}
            retrieve={onRetrieve && generation.retrievable ? { run: onRetrieve, pending: retrieving } : undefined}
            upgrade={gone.missing?.upgrade && gone.missing.plugin_instance_id
              ? <UpgradeInLibraryButton instanceId={gone.missing.plugin_instance_id} workspaceId={workspaceId} />
              : undefined}
          />
        ) : (
          <GenerationProgress
            kind={generation.kind}
            expected={expectedOutputs(generation, option)}
            running={status === "running"}
            progress={job?.progress}
            message={job?.message ?? ""}
            elapsed={elapsed}
            onStop={onStop && generation.job_id ? () => onStop(generation.job_id!) : undefined}
            stopping={stopping}
          />
        )}
        {noOutput ? null : <div className="justify-self-start">{meta}</div>}
      </div>
    </article>
  );
}

/**
 * 一条生成的元信息:用的哪个模型(主名;副名 —— 来自哪张工作流、哪台服务器 —— 在悬停里)、用了多久、费用,没交回产出的那一条
 * 再带上时间(它在卡头里,提示词下面就不再摆)。成图、在跑的那一条摆在产出下面,停下的、跑挂了的摆在卡头右边。
 */
function TurnMeta({ engineName, parts, time }: { engineName: TwoLayerName; parts: string[]; time: string | null }) {
  const items: React.ReactNode[] = [
    <Hint key="engine" label={engineName.primary} hint={engineName.secondary || null}>
      <span data-engine-name="">{engineName.primary}</span>
    </Hint>,
    ...parts.filter(Boolean).map((part) => <span key={part}>{part}</span>),
    ...(time ? [<MessageTime key="time" iso={time} />] : []),
  ];
  return (
    <small className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 text-ui-xs text-muted-foreground" data-generation-meta="">
      {items.map((item, index) => (
        <React.Fragment key={index}>
          {index > 0 ? <span aria-hidden>·</span> : null}
          {item}
        </React.Fragment>
      ))}
    </small>
  );
}

/** 一次生成要交回的样子:几份、每份什么比例(宽 / 高)。占位按它摆,产出到了原地换掉,版面不跳。 */
type ExpectedOutputs = { count: number; ratio: number };

/** 占位最多摆几格:跑 4 遍 × 一遍 2 张就是 8 格,再多就只是一片灰。 */
const MAX_PLACEHOLDERS = 8;

/** 「宽x高」(`1024x1536`、`832*480`、`768×1024`)或画幅(`16:9`、`9:16 (Portrait)`)→ 宽 / 高;认不出就是 null。 */
function ratioOf(value: unknown): number | null {
  const found = /^\s*(\d+(?:\.\d+)?)\s*[x×*:]\s*(\d+(?:\.\d+)?)/i.exec(String(value ?? ""));
  if (!found) return null;
  const width = Number(found[1]);
  const height = Number(found[2]);
  return width > 0 && height > 0 ? width / height : null;
}

/**
 * 这一次会交回几份、长什么样:图像按请求的尺寸 / 画幅定比例(没给就是方的),份数 = 张数(或跑几遍)× 一遍交回几份
 * (模型说的,见 outputsPerRun);视频按画幅(没给 16:9);音频按一遍交回几首。
 */
function expectedOutputs(generation: GenerationJob, option: GenerationOption | null): ExpectedOutputs {
  const parameters = (generation.request.parameters ?? {}) as Record<string, unknown>;
  const ratio = ratioOf(parameters.size) ?? ratioOf(parameters.aspect_ratio) ?? (generation.kind === "video" ? 16 / 9 : 1);
  const perRun = outputsPerRun(option, parameters);
  const runs = generation.kind === "image" && typeof parameters.num_images === "number" ? Math.max(1, parameters.num_images) : 1;
  return { count: Math.min(MAX_PLACEHOLDERS, Math.max(1, runs * perRun)), ratio };
}

/**
 * 还没交回的那一条:在产出将要出现的位置**按它的样子**先占好(图按比例、几张摆几格,视频一格,音频和成品卡同一个壳),
 * 下面一行写清走到哪儿了 —— 排队中 / 生成中、进度、插件报的那一句(ComfyUI 的「KSampler 12/20 · 第 3/9 个节点」)、
 * 已用多久,和「停止」。
 *
 * 此前这里是一块平平的灰块,角上一句「生成中 35%」(维护者:「loading 的这个卡片 UI 也很丑」),而且停不下来。
 * 和画板上在跑的那一格同一套说法:在跑的扫光(<Skeleton surface>,铺满一整块表面的那一档)、顶上一条细进度;
 * 排队的不扫光(还没开始做),只摆淡淡的壳子和一枚钟。进度只写任务真报了的,不去猜一个数。
 */
function GenerationProgress({
  kind,
  expected,
  running,
  progress,
  message,
  elapsed,
  onStop,
  stopping,
}: {
  kind: string;
  expected: ExpectedOutputs;
  running: boolean;
  progress?: number;
  message: string;
  elapsed: number | null;
  onStop?: () => void;
  stopping?: boolean;
}) {
  const t = useI18n();
  const fraction = running && typeof progress === "number" && progress > 0 && progress < 1 ? progress : 0;
  const percent = fraction > 0 ? Math.round(fraction * 100) : null;
  const label = t(running ? "generating" : "genQueued");
  //: 插件报的那一句。和标题说的是同一句(「生成中」)就不重复
  const detail = message.trim() && message.trim() !== label ? message.trim() : "";
  return (
    <div
      role="status"
      aria-busy="true"
      aria-label={label}
      className="grid w-full max-w-[min(560px,100%)] gap-2"
      data-generation-pending={running ? "running" : "queued"}
    >
      {isAudibleKind(kind) ? (
        <PendingAudioList count={expected.count} running={running} />
      ) : (
        <PendingFrames kind={kind} expected={expected} running={running} fraction={fraction} />
      )}
      <div className="flex min-w-0 items-center gap-2 rounded-lg border border-border bg-control py-1 pl-3 pr-1">
        {running ? (
          <Loader2 size={13} className="shrink-0 animate-mosael-spin text-primary" aria-hidden />
        ) : (
          <Clock3 size={13} className="shrink-0 text-muted-foreground" aria-hidden />
        )}
        <span className={cn("shrink-0 text-ui-sm font-medium", running ? "text-primary" : "text-foreground")}>{label}</span>
        {percent !== null ? <span className="shrink-0 text-ui-sm tabular-nums text-primary">{percent}%</span> : null}
        <Truncate className="min-w-0 flex-1 text-ui-xs text-muted-foreground">{detail}</Truncate>
        {elapsed !== null ? (
          <span className="timecode shrink-0 text-ui-xs tabular-nums text-muted-foreground">
            {t(running ? "usageRunning" : "genQueuedFor").replace("{t}", formatElapsedSeconds(elapsed))}
          </span>
        ) : null}
        {onStop ? (
          <Hint label={t("genStopHint")}>
            <Button type="button" variant="outline" size="xs" className="shrink-0" loading={stopping} onClick={onStop}>
              <Square size={10} fill="currentColor" />
              {t("genStop")}
            </Button>
          </Hint>
        ) : null}
      </div>
    </div>
  );
}

/**
 * 图和视频的占位:按比例,图几张摆几格(和出图同一个尺寸规则:一张最高 360px,多张每张 220px 高),视频一格
 * (和成片同一个框:最宽 560px、最高 420px)。宽度按「高 × 比例」算、不超过这一栏,高跟着比例走。
 */
function PendingFrames({
  kind,
  expected,
  running,
  fraction,
}: {
  kind: string;
  expected: ExpectedOutputs;
  running: boolean;
  fraction: number;
}) {
  const many = kind !== "video" && expected.count > 1;
  const height = kind === "video" ? 420 : many ? 220 : 360;
  return (
    <div className="flex w-full flex-wrap gap-1.5" aria-hidden>
      {Array.from({ length: kind === "video" ? 1 : expected.count }, (_, index) => (
        <div
          key={index}
          className={cn(
            "relative grid shrink-0 place-items-center overflow-hidden rounded-lg border border-border",
            !running && "bg-[color-mix(in_srgb,var(--primary)_5%,transparent)]",
          )}
          style={{ aspectRatio: expected.ratio, width: `min(${Math.round(height * expected.ratio)}px, 100%)` }}
        >
          {running ? (
            <>
              <Skeleton surface className="absolute inset-0 h-full w-full rounded-none" />
              {fraction > 0 && (
                <div className="absolute inset-x-0 top-0 h-0.5 bg-primary/15">
                  <div className="h-full bg-primary transition-[width]" style={{ width: `${Math.round(fraction * 100)}%` }} />
                </div>
              )}
              {/* 一枚淡淡的图 / 片子:一眼看出这一格将来是什么,而不是一块没来由的灰板 */}
              {kind === "video" ? (
                <Film size={24} strokeWidth={1.5} className="relative text-muted-foreground/40" />
              ) : (
                <ImageIcon size={24} strokeWidth={1.5} className="relative text-muted-foreground/40" />
              )}
            </>
          ) : (
            <Clock3 size={18} className="text-primary/70" />
          )}
        </div>
      ))}
    </div>
  );
}

/**
 * 有人把它停下了(这里的「停止」、任务中心的取消、画板的停止):不是跑挂了,不摆红色的失败卡。
 * 花没花钱写在下面的脚注里,和别的记录同一句(「未扣费」或金额)。
 */
