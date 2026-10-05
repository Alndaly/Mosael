import { assetKeys } from "@/api/queryKeys";
import React from "react";
import { StudioIndex } from "@/components/layout/StudioIndex";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  Cpu,
  Eye,
  Images,
  Music,
  Ratio,
  SlidersHorizontal,
  CircleAlert,
  Copy,
  Loader2,
  Send,
  Sparkles,
  Wand2,
  X,
} from "lucide-react";
import { toast } from "sonner";

import {
  api,
  assetFileUrl,
  assetPreviewUrl,
  assetThumbnailUrl,
  entityReceipt,
  optimizeImagePrompt,
  type EntitySummary,
  type GenerationCreateResponse,
  type GenerationJob,
  type GenerationOption,
  type Job,
  type Workspace,
} from "@/api/client";
import type { components } from "@/api/generated/schema";
import { errorText } from "@/api/errorMessage";
import { JumpToLatest, useStickToBottom } from "@/features/agent/stickToBottom";
import { IconButton } from "@/components/ui/icon-button";
import { Skeleton } from "@/components/ui/skeleton";
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
import { useImagePreview } from "@/components/app/image-preview";
import { generationSessionSelectionKey } from "@/features/agent/sessionSelection";
import { useEffectiveChatModel } from "@/features/agent/effectiveModel";
import {
  DeclaredParameterControl,
  PARAMETER_CONTROL_CLASS,
  ParameterField,
  ParameterSection,
} from "@/components/generation/parameterPanel";
import { CustomSizePicker } from "@/components/generation/CustomSizePicker";
import { useGenerationOptions } from "@/lib/generationOptions";
import { elapsedSecondsBetween, formatElapsedSeconds, useNow } from "@/lib/time";
import { MessageFooter, MessageTime } from "@/features/agent/messageUsage";
import { formatCosts } from "@/lib/money";
import {
  aspectRatioOptions,
  booleanParameterKeys,
  capabilityBoolean,
  capabilityString,
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
  parameterChoiceEntries,
  pickGenerationOption,
  runsHint,
  supportsParameter,
  sourceLimit,
  exclusiveSourceGroups,
  hasEnoughText,
  promptMode,
  promptToSend,
  videoResolutionOptions,
  withTriggerWords,
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
  audioSourceRoles,
  lyricsLimit,
} from "@/features/ai-studio/audioGeneration";
import { SessionList } from "@/features/ai-studio/SessionList";
import { GenerationModelGate } from "@/features/ai-studio/GenerationModelGate";
import { AI_PANEL_BOUNDS } from "@/features/ai-studio/ChatWorkspace";
import { takeGenerationHandoff } from "@/lib/generationHandoff";
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
export const GENERATION_MEDIA = {
  visual: ["image", "video"],
  audio: ["audio"],
} as const satisfies Record<string, readonly string[]>;
export type GenerationMedium = keyof typeof GENERATION_MEDIA;

/**
 * 生成的样子和对话一样:左边会话,中间这条会话的来回,右边模型与参数。
 *
 * 同事共享来的会话**只能看**(后端 generation/sessions 定的规矩,`is_mine` 是它给的答案):输入区换成一句只读说明,
 * 模型与参数栏不开 —— 会话记着的是主人的连接,在这里换模型等于把自己的连接写进别人的会话。
 */
export function GenerateWorkspace({
  workspace,
  medium,
  switcher,
}: {
  workspace: Workspace;
  medium: GenerationMedium;
  switcher?: React.ReactNode;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const qc = useQueryClient();
  
  const panels = useSidePanels("generation", AI_PANEL_BOUNDS);
  const narrowLayout = useMediaMatch("(max-width: 1180px)");
  const singleColumn = useMediaMatch("(max-width: 820px)");
  const [parametersOpen, setParametersOpen] = React.useState(() => !narrowLayout);
  const kinds = GENERATION_MEDIA[medium];
  //: 两页各记各的「上次开着哪条」—— 同一个键的话,切到另一页会先落在一条不属于它的会话上。
  const sessionKey = `${generationSessionSelectionKey(workspace.id)}.${medium}`;
  const [sessionId, setSessionId] = React.useState<string | null>(() => window.localStorage.getItem(sessionKey));
  const [prompt, setPrompt] = React.useState("");
  //: 这一次 `@` 到的资产(ADR 0027):提示词描述和参考图由服务端按所选模型收得下的张数挂上。
  const [mentionedEntities, setMentionedEntities] = React.useState<EntitySummary[]>([]);
  const [modelId, setModelId] = React.useState<string | null>(null);
  const [generationConfig, setGenerationConfig] = React.useState<GenerationConfig>(() => defaultGenerationConfig(null));
  

  const sessions = useQuery({
    //: 键以 ["generation-sessions", 工作区] 开头:会话列表、共享菜单按这个前缀失效,两页一起刷。
    queryKey: ["generation-sessions", workspace.id, medium],
    queryFn: () =>
      api<GenerationSession[]>(
        `/api/generation/sessions?workspace_id=${workspace.id}${kinds.map((kind) => `&kind=${kind}`).join("")}`,
      ),
  });
  //: 这一页的几种生成各拉一份选项(音频和图像、视频是同一条管线,ADR 0022;只是不在同一页)。
  const generationOptions = useGenerationOptions(kinds);
  const jobs = useQuery({
    queryKey: ["jobs", workspace.id, "ai_generation"],
    queryFn: () => api<Job[]>(`/api/jobs?workspace_id=${workspace.id}&kind=ai_generation`),
    refetchInterval: (query) =>
      query.state.data?.some((job) => job.status === "queued" || job.status === "running") ? 1000 : false,
    refetchOnWindowFocus: true,
  });
  const activeSession =
    (sessions.data ?? []).find((session) => session.id === sessionId) ?? (sessions.data ?? [])[0] ?? null;
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
      return query.state.data?.some((generation) => generation.job_id && activeJobIds.has(generation.job_id)) ? 1000 : false;
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
  const sessionOption =
    activeSession?.provider_profile_id && activeSession.model && activeSession.kind
      ? findGenerationOption(modelOptions, activeSession.provider_profile_id, activeSession.kind, activeSession.model)
      : null;
  //: 这次挑的 → 会话记着的 → 用户设的默认(先这一页的第一种,没有就这一页随便哪一种的默认)→ 没有。
  //: **不拿第一项顶上**:没设默认时选择器显示「选择模型」,等人选(见 pickGenerationOption)。
  const selectedModel =
    (modelId ? optionByValue.get(modelId) : null) ??
    sessionOption ??
    pickGenerationOption(modelOptions, { kind: kinds[0] }) ??
    pickGenerationOption(modelOptions);
  const generationModelsLoading = generationOptions.pending;
  //: 这一页的几种生成一个模型都没有。选项在后端就只列启用连接下启用的模型(provider_models.models_for_capability),
  //: 所以「没配置」只有这一种样子 —— 不再拿设置页的连接列表另判一遍「选中的这个配没配」:
  //: 那一判只在连接列表还没到或取失败时为真,表现为提示条一闪、或一直挂着。
  const noGenerationModels = modelOptions.length === 0 && !generationModelsLoading;
  //: 去配置时落到哪一页:选中的模型是哪种能力就去哪种;一个都没选时看会话记着的能力,再没有才去图像。
  const settingsSection = `providers:${selectedModel?.kind ?? activeSession?.kind ?? kinds[0]}`;
  const selectedAdapterAvailable = selectedModel?.adapter_available ?? false;
  const selectedSizes = sizeOptions(selectedModel);
  const selectedCustomSize = customSizeRule(selectedModel);
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
  const promptHintKey =
    selectedPromptMode === "none"
      ? "genPromptNotUsed"
      : selectedPromptMode === "optional"
        ? "promptPlaceholderOptional"
        : isAudioModel
          ? "audioPromptPlaceholder"
          : "promptPlaceholder";
  const supportsLyrics = isAudioModel && supportsParameter(selectedModel, "lyrics");
  const supportsInstrumental = isAudioModel && supportsParameter(selectedModel, "instrumental");
  const selectedAudioRoles = audioSourceRoles(selectedModel);
  const supportsNegativePrompt = supportsParameter(selectedModel, "negative_prompt");
  const supportsReferenceImage = supportsParameter(selectedModel, "reference_image");
  const supportsFirstFrame = selectedModel?.kind === "video" && supportsParameter(selectedModel, "first_frame");
  // 尾帧:首尾帧一起给 = 让模型从一张图动到另一张图。只有描述符声明了的模型才出这个控件 ——
  // 控件跟着描述符走,不按 kind 写死(见 docs/CONVENTIONS 那条棘轮)。
  const supportsLastFrame = selectedModel?.kind === "video" && supportsParameter(selectedModel, "last_frame");
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
    const handoff = takeGenerationHandoff(kinds);
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
    for (const model of modelOptions) {
      grouped.set(model.kind, [...(grouped.get(model.kind) ?? []), model]);
    }
    const known = ["image", "video", "audio"];
    return [...known, ...[...grouped.keys()].filter((kind) => !known.includes(kind))]
      .filter((kind) => (grouped.get(kind) ?? []).length > 0)
      .map((kind) => ({ kind, models: grouped.get(kind) ?? [] }));
  }, [modelOptions]);
  const capabilityLabel = (kind: string) =>
    kind === "image" ? t("capImage") : kind === "video" ? t("capVideo") : kind === "audio" ? t("capAudio") : kind;
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
    const option = optionByValue.get(value);
    if (!option || readOnly) return;
    setModelId(value);
    if (activeSession) {
      updateSessionEngine.mutate({
        id: activeSession.id,
        provider_profile_id: option.provider_profile_id,
        model: option.model,
        kind: option.kind,
      });
    }
  };

  //: 新会话记着种类:它决定会话在哪一页(见 GENERATION_MEDIA)。
  const newSessionKind = selectedModel?.kind ?? kinds[0];
  const createSession = useMutation({
    mutationFn: () =>
      api<GenerationSession>("/api/generation/sessions", {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspace.id, kind: newSessionKind }),
      }),
    onSuccess: (created) => {
      setSessionId(created.id);
      window.localStorage.setItem(sessionKey, created.id);
      void qc.invalidateQueries({ queryKey: ["generation-sessions", workspace.id] });
    },
  });
  const ordered = React.useMemo(() => sessionJobs.data ?? [], [sessionJobs.data]);
  // 会话画廊:点开任意一张图,可左右翻看本会话的全部图片产出。
  //: **每条生成摊平成它的全部产出** —— 一次出四张时,画廊里就该有四张;只收封面的话,
  //: 用户左右翻着翻着会发现刚看到的那三张翻不到。
  const sessionGallery = React.useMemo(
    () =>
      ordered
        .filter((generation) => generation.kind === "image")
        .flatMap((generation) => {
          const ids = generation.result_asset_ids?.length
            ? generation.result_asset_ids
            : generation.result_asset_id
              ? [generation.result_asset_id]
              : [];
          return ids.map((assetId) => ({
            src: assetPreviewUrl(assetId),
            title: String(generation.request.prompt ?? generation.model),
          }));
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
        if (modelId && selectedModel) {
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
      provider_profile_id: string;
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

  //: 一条任务落了终态就重拉这条会话的记录:成功的带回产出,失败的带回**记录自己存的**失败原因
  //: (生成记录在任务失败那一刻抄下它,任务之后会被清掉,见后端 generation.runner.record_failure)。
  const settledCount = (jobs.data ?? []).filter((job) => job.status === "succeeded" || job.status === "failed").length;
  React.useEffect(() => {
    if (settledCount > 0) {
      void qc.invalidateQueries({ queryKey: assetKeys.everywhere() });
      void qc.invalidateQueries({ queryKey: ["generation-jobs", workspace.id, activeSession?.id] });
      void qc.invalidateQueries({ queryKey: ["generation-sessions", workspace.id] });
    }
  }, [settledCount, qc, workspace.id, activeSession?.id]);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (readOnly || !canSubmitText || !selectedModel || !selectedAdapterAvailable || createGeneration.isPending) return;
    if (needsDigitalHumanConsent && !digitalHumanConsent) {
      toast.error(t("genDigitalHumanConsentNeeded"));
      return;
    }
    stick.scrollToBottom(); // 自己发的消息一定要看得见
    createGeneration.mutate();
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
          onCreate={() => createSession.mutate()}
          creating={createSession.isPending}
          onDeleted={(ids) => {
            // 删掉的里面有正开着的那个,就把视图放下 —— 否则右边还停在一个已经不存在的会话上。
            if (sessionId && ids.includes(sessionId)) {
              setSessionId(null);
              window.localStorage.removeItem(sessionKey);
            }
            // 会话没了,它那些生成记录也不该继续挂在任务列表里。SessionList 只管会话这一层,
            // 连带要刷的东西由调用方说 —— 它不认识生成任务。
            void qc.invalidateQueries({ queryKey: ["generation-jobs", workspace.id] });
            void qc.invalidateQueries({ queryKey: ["jobs", workspace.id, "ai_generation"] });
          }}
        />
      </StudioIndex>

      <section className="min-h-0 overflow-hidden bg-workspace-panel grid min-w-0 grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)_auto]">
        <div className="flex min-h-14 min-w-0 flex-wrap items-center gap-2 border-b border-divider px-4 py-1.5 max-[821px]:pl-14">
          {switcher}
          <Truncate className="flex-1 text-ui-sm font-medium">{activeSession?.title}</Truncate>
          {!readOnly && (
            <Button variant={parametersOpen ? "secondary" : "ghost"} size="sm" onClick={() => setParametersOpen(!parametersOpen)} aria-pressed={parametersOpen}><SlidersHorizontal />{t("generationEngineSettings")}</Button>
          )}
        </div>
        <div className="relative grid min-h-0 min-w-0">
        <div className="flex min-w-0 flex-col gap-3.5 overflow-y-auto overflow-x-hidden px-4 pb-2.5 pt-7" ref={stick.ref}>
          {/* First load: skeleton turns instead of flashing the "no jobs yet" empty state. */}
          {activeSession && sessionJobs.isLoading && ordered.length === 0 && (
            <div className="flex flex-col gap-3.5" aria-hidden>
              {[0, 1].map((i) => (
                <div key={i} className="flex flex-col gap-2">
                  <Skeleton className="h-4 w-44 self-end rounded-full" />
                  <Skeleton className="aspect-square w-full max-w-[320px] rounded-lg" />
                </div>
              ))}
            </div>
          )}
          {!(activeSession && sessionJobs.isLoading) && ordered.length === 0 && (
            <div className="m-auto">
              <EmptyState icon={<Sparkles size={22} />} title={t("noGenerationJobs")} body={selectedPromptMode === "none" ? undefined : t(promptHintKey)} />
            </div>
          )}
          {ordered.map((generation) => (
            <GenerationTurn
              key={generation.id}
              generation={generation}
              job={jobs.data?.find((item) => item.id === generation.job_id) ?? null}
              gallery={sessionGallery}
            />
          ))}
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
            className="mx-auto mb-3.5 mt-1.5 flex w-[min(780px,calc(100%-32px))] flex-col gap-1 rounded-lg border border-border bg-control px-2.5 pb-1.5 pl-3 pt-2.5 transition-colors duration-100 focus-within:border-ring"
            onSubmit={submit}
          >
            {/* 这一次带上的资产排在输入卡顶上 —— 和对话页的附件同一排、同一种小条(ComposerChips)。
                此前挑中的资产和「@ 资产」按钮自成一行,夹在正文和底栏中间(用户截图:位置很怪)。 */}
            <ComposerChips chips={entityMentionChips(mentionedEntities, setMentionedEntities)} className="px-0.5" />
            {selectedPromptMode === "none" ? (
              // 这个模型不收提示词(放大、抠图这类按素材出结果的工作流):不摆一个写了也不生效的框,
              // 说清楚该做什么 —— 挂素材、调参数,直接生成。
              <p className="m-0 min-h-11 px-0 py-0.5 pb-1.5 text-ui-sm leading-[1.55] text-muted-foreground">
                {t("genPromptNotUsed")}
              </p>
            ) : (
              <Textarea
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
                  if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
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
                {/* 模型是一个能点的东西(和对话页的模型选择器同一种样子):点开右边的「模型与参数」。
                    此前它是一枚点不动的标签,要换模型得去找右上角那个按钮。 */}
                {selectedModel && (
                  //: 悬停说全名(按钮上的可能被截断)和点下去会去哪儿。
                  <Hint label={selectedModel.label} hint={t("generationEngineSettings")}>
                    <button
                      type="button"
                      onClick={() => setParametersOpen(true)}
                      aria-label={t("generationEngineSettings")}
                      className="inline-flex h-7 min-w-0 max-w-[240px] cursor-pointer items-center gap-1 rounded-md border border-field-border bg-field px-2 text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:border-primary focus-visible:outline-none"
                    >
                      <Truncate>{selectedModel.label}</Truncate>
                      <SlidersHorizontal size={12} className="shrink-0 opacity-60" />
                    </button>
                  </Hint>
                )}
                {/* 参数栏开着时,「一个模型都没有」由那边的提示条说,这里不再摆第二个入口。 */}
                {!(noGenerationModels && parametersOpen) && (
                  <GenerationModelGate hasModel={Boolean(selectedModel)} loading={generationModelsLoading} section={settingsSection} />
                )}
              </div>
              <IconButton
                type="submit"
                variant="default"
                size="icon"
                className="shrink-0 rounded-full"
                label={t("generate")}
                disabled={!canSubmitText || !selectedModel || !selectedAdapterAvailable} loading={createGeneration.isPending}
              >
                <Send size={15} />
              </IconButton>
            </div>
          </form>
        )}
      </section>

      {/* 参数栏和对话页右侧的智能体检查器是同一件东西:同一侧、同为"若干块各自成组"。
          所以壳子也用同一个(InspectorCard)—— 标题行的字号字重、块与块之间的 gap-6、
          正文的 p-4,都跟着那边走,不再自成一套。 */}
      <aside
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
              {t("generationAdapterUnavailable").replace("{engine}", `${selectedModel.provider} · ${selectedModel.model}`)}
            </div>
          )}
          {/* 模型选择器**有模型就摆出来**,哪怕还没选中任何一个:没设默认时它显示「选择模型」等人选,
              而不是拿清单第一项顶上 —— 那样选中的就不是谁的选择(见 pickGenerationOption)。 */}
          {modelOptions.length > 0 && (
            <ParameterSection icon={Cpu} title={t("genSectionEngine")}>
              <ParameterField label={t("wfModelPreset")}>
                {/* 模型清单按能力分组,且**一定**是长清单 —— 直接给可搜索的那一版,不走阈值。
                    每行的图标撤了:它编码的是"图片还是视频",而分组标题已经说了同一件事,
                    搜索框在的时候那枚重复的小图标只是占掉了名字的位置。 */}
                <SearchableSelect
                  value={selectedModel?.value ?? ""}
                  onValueChange={selectEngine}
                  options={modelGroups.flatMap((group) =>
                    group.models.map((model) => ({
                      value: model.value,
                      label: model.label,
                      group: capabilityLabel(group.kind),
                    })),
                  )}
                  placeholder={t("genPickModel")}
                  emptyText={t("cmdkEmpty")}
                  className={PARAMETER_CONTROL_CLASS}
                />
              </ParameterField>
            </ParameterSection>
          )}
          {selectedModel && (
            <>

              {/* 出片规格 = "出多大、出几张、出多久、带不带声" —— 看一眼就知道成片长什么样的那几栏。
                  怎么出(seed、反向提示词、各家自己加的开关)在下面那块。 */}
              <ParameterSection icon={Ratio} title={t("genSectionOutput")}>
                {/* 尺寸**不属于任何一支**:图像收 `1024x1024`,万相视频收 `832*480`,都是"出多大"。
                    此前它锁在 image 分支里,于是一个声明了 size 的视频模型连这一栏都不出现 ——
                    参数描述符说了话而界面没听。 */}
                {supportsParameter(selectedModel, "size") && selectedSizes.length > 0 && selectedCustomSize && (
                  /* 推荐的几档、手填的也收(ComfyUI 的工作流) */
                  <ParameterField label={t("genSize")}>
                    <CustomSizePicker
                      value={generationConfig.size}
                      onChange={(value) => setConfigValue("size", value)}
                      options={selectedSizes}
                      minimum={selectedCustomSize.minimum}
                      ariaLabel={t("genSize")}
                      className={PARAMETER_CONTROL_CLASS}
                    />
                  </ParameterField>
                )}
                {supportsParameter(selectedModel, "size") && selectedSizes.length > 0 && !selectedCustomSize && (
                  <ParameterField label={t("genSize")}>
                    <Select value={generationConfig.size} onValueChange={(value) => setConfigValue("size", value)}>
                      <SelectTrigger className={PARAMETER_CONTROL_CLASS}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {selectedSizes.map((size) => (
                          <SelectItem key={size} value={size}>
                            {size}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </ParameterField>
                )}
                {isImageModel && supportsParameter(selectedModel, "num_images") && (
                  // ComfyUI 的工作流「张数」是跑几遍:标签换成「跑几遍」,下面说清一遍出几张、一共几张(见 runsHint)。
                  <ParameterField
                    label={generationParameterLabel("num_images", selectedModel, t)}
                    hint={countsRuns(selectedModel)
                      ? runsHint(t, selectedModel, generationParameters(selectedModel, generationConfig),
                        Math.max(1, Math.min(maxImages(selectedModel), Number(generationConfig.numImages) || 1)))
                      : undefined}
                  >
                    <Input
                      className={PARAMETER_CONTROL_CLASS}
                      type="number"
                      min={1}
                      max={maxImages(selectedModel)}
                      value={generationConfig.numImages}
                      onChange={(event) => setConfigValue("numImages", event.target.value)}
                    />
                  </ParameterField>
                )}
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
                {isImageModel && supportsReferenceImage && (
                  // 图像的参考图和视频那边**是同一件事**,所以用同一个控件:一行缩略图、一次能选
                  // 多张、上限读描述符(seedream 4 十四张、qwen 三张、gpt-image 十六张)。
                  // 此前这里自成一套 —— 单张、老样式,于是同一个"参考图"在两个 tab 里长得不一样,
                  // 能挂的份数也不一样,而那个差别纯粹是没人来改。
                  <div className="grid gap-1.5">
                    <FrameSlotField
                      role="reference_image"
                      slots={generationConfig.frames.reference_image}
                      limit={sourceLimit(selectedModel, "reference_image")}
                      onChange={(slots) =>
                        setGenerationConfig((current) => ({
                          ...current,
                          frames: { ...current.frames, reference_image: slots },
                          // 手挑了图就不再"用上一张结果" —— 两个都开着的话,发出去的是哪张
                          // 全看代码顺序,而界面上两处都亮着。
                          usePreviousImage: slots.some((one) => one.assetId || one.url.trim())
                            ? false
                            : current.usePreviousImage,
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
                )}
                {supportsFirstFrame && (
                  <KeyframePairField
                    first={generationConfig.frames.first_frame}
                    last={generationConfig.frames.last_frame}
                    showLast={supportsLastFrame}
                    onChange={({ first, last }) =>
                      setGenerationConfig((current) => ({
                        ...current,
                        frames: { ...current.frames, first_frame: first, last_frame: last },
                      }))
                    }
                    workspaceId={workspace.id}
                    hint={supportsLastFrame ? t("genLastFrameHint") : t("genKeyframeHint")}
                    disabled={lockedRoles.has("first_frame")}
                    disabledReason={t("genSourceGroupsExclusive")}
                  />
                )}
                {videoInputRoles.map((role) => (
                  <FrameSlotField
                    key={role}
                    role={role}
                    slots={generationConfig.frames[role]}
                    limit={sourceLimit(selectedModel, role)}
                    onChange={(slots) => setFrames(role, slots)}
                    workspaceId={workspace.id}
                    hint={t(VIDEO_INPUT_HINTS[role])}
                    disabled={lockedRoles.has(role)}
                    disabledReason={t("genSourceGroupsExclusive")}
                  />
                ))}
                {needsDigitalHumanConsent && (
                  <DigitalHumanConsent checked={digitalHumanConsent} onChange={setDigitalHumanConsent} />
                )}
                {videoReferenceRoles.map((role, index) => (
                  <FrameSlotField
                    key={role}
                    role={role}
                    slots={generationConfig.frames[role]}
                    limit={sourceLimit(selectedModel, role)}
                    onChange={(slots) => setFrames(role, slots)}
                    workspaceId={workspace.id}
                    // 这一句只说一遍:三个参考控件挨在一起,每个都重复一次就成了噪音。
                    hint={index === 0 ? t("genReferenceHint") : undefined}
                    disabled={lockedRoles.has(role)}
                    disabledReason={t("genSourceGroupsExclusive")}
                  />
                ))}
                {/* 音频模型的输入:要配声的视频、参考 / 被翻唱的音频、图生音乐的图。同一个控件,
                    提示语换成音频上的意思。 */}
                {selectedAudioRoles.map((role) => (
                  <FrameSlotField
                    key={role}
                    role={role}
                    slots={generationConfig.frames[role]}
                    limit={sourceLimit(selectedModel, role)}
                    onChange={(slots) => setFrames(role, slots)}
                    workspaceId={workspace.id}
                    hint={t(AUDIO_SOURCE_HINTS[role])}
                  />
                ))}
              </ParameterSection>

              {/* 调参:seed、反向提示词,以及各家自己加的开关和枚举。它们决定"怎么出",
                  多数时候不用动 —— 所以排在最后,而不是和尺寸、张数混在一起。 */}
              <ParameterSection icon={SlidersHorizontal} title={t("genSectionAdvanced")}>
                {/* 种子与反向提示词**不分种类**:描述符声明了就给控件(generationParameters 的 shared
                    那一段本来就不分种类地发它们)。 */}
                {supportsParameter(selectedModel, "seed") && (
                  <ParameterField label={t("genSeed")}>
                    <Input
                      className={PARAMETER_CONTROL_CLASS}
                      type="number"
                      placeholder="auto"
                      value={generationConfig.seed}
                      onChange={(event) => setConfigValue("seed", event.target.value)}
                    />
                  </ParameterField>
                )}
                {supportsNegativePrompt && (
                  <ParameterField label={t("genNegativePrompt")}>
                    <Input
                      className={PARAMETER_CONTROL_CLASS}
                      value={generationConfig.negativePrompt}
                      onChange={(event) => setConfigValue("negativePrompt", event.target.value)}
                    />
                  </ParameterField>
                )}
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
                {declaredParameters(selectedModel).map((parameter) => (
                  <ParameterField
                    key={parameter.key}
                    // 宿主认得的参数名(人声、曲名……)按界面语言说;插件自己的参数用插件给的名字。
                    label={GENERATION_PARAMETER_LABELS[parameter.key] ? t(GENERATION_PARAMETER_LABELS[parameter.key]) : parameter.label}
                    title={toPlainText(parameter.description) || undefined}
                  >
                    {parameter.modelFolder && selectedModel?.plugin_instance_id && parameter.options.length > 0 ? (
                      /* 选模型文件的那一格:缩略图、底模、触发词来自这个连接的模型库,选中 LoRA 能一键加触发词 */
                      <ModelFilePicker
                        parameter={parameter}
                        instanceId={selectedModel.plugin_instance_id}
                        value={generationConfig.declared[parameter.key] ?? ""}
                        onChange={(value) =>
                          setGenerationConfig((current) => ({
                            ...current,
                            declared: { ...current.declared, [parameter.key]: value },
                          }))
                        }
                        onUseTriggers={(words) => setPrompt((current) => withTriggerWords(current, words))}
                        className={PARAMETER_CONTROL_CLASS}
                      />
                    ) : (
                      <DeclaredParameterControl
                        parameter={parameter}
                        value={generationConfig.declared[parameter.key] ?? ""}
                        onChange={(value) =>
                          setGenerationConfig((current) => ({
                            ...current,
                            declared: { ...current.declared, [parameter.key]: value },
                          }))
                        }
                      />
                    )}
                  </ParameterField>
                ))}
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

function GenerationTurn({
  generation,
  job,
  gallery,
}: {
  generation: GenerationJob;
  job: Job | null;
  gallery?: Array<{ src: string; title?: string }>;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const { openImagePreview } = useImagePreview();
  // job 行可能已被任务中心「清空已结束」删掉(记录长存、job_id 置空):有产物即成功;记录上记着失败原因、
  // 或者任务已经不在了,即失败;只有任务还在而列表没拉到时才视作排队中。
  const status =
    job?.status ??
    (generation.result_asset_id ? "succeeded" : generation.job_id && !generation.error ? "queued" : "failed");
  //: 这一条生成的**全部**产出。后端给 result_asset_ids(封面排第一);一次只出一份时它就是
  //: 那一份 —— 不为「一份」和「多份」各写一套渲染。
  const outputs = generation.result_asset_ids?.length
    ? generation.result_asset_ids
    : generation.result_asset_id
      ? [generation.result_asset_id]
      : [];
  const timestamp = generation.created_at ?? job?.created_at ?? null;
  const isRunning = status === "running";
  const isFinished = status === "succeeded" || status === "failed";
  // 节拍时钟:运行中每秒刷计时;空闲 30s 一拍让「x 分钟前」不冻住。
  // (轮询回包无变化时 react-query 不触发重渲,光靠轮询计时会停走。)
  const now = useNow(isRunning ? 1000 : 30_000);
  //: 音频可以只给歌词(或者给视频配声什么字都不给):气泡里就显示歌词,都没有时说「按素材生成」。
  const requestParameters = (generation.request.parameters ?? {}) as Record<string, unknown>;
  const prompt =
    String(generation.request.prompt ?? "").trim() ||
    String(requestParameters.lyrics ?? "").trim() ||
    (generation.kind === "audio" ? t("genAudioFromSources") : "");
  const durationSeconds = isRunning
    ? elapsedSecondsBetween(timestamp, now)
    : isFinished
      ? elapsedSecondsBetween(timestamp, job?.updated_at ?? generation.updated_at)
      : null;
  const durationLabel =
    typeof durationSeconds === "number"
      ? t(isRunning ? "usageRunning" : "usageDuration").replace("{t}", formatElapsedSeconds(durationSeconds))
      : "";
  // 计费:与对话页同一套格式化(lib/money)。有已知费用显示金额 —— 每个币种一笔,不相加;
  // 有事件但无定价显示「未定价」。
  const costLabel =
    (generation.costs ?? []).length > 0
      ? t("usageCost").replace("{cost}", formatCosts(generation.costs, locale))
      : generation.cost_confidence === "unknown"
        ? t("usageCostUnknown")
        : "";
  return (
    <article className="group/gen grid w-full max-w-[780px] shrink-0 gap-2.5 self-center">
      <div className="grid justify-items-end gap-1">
        <div className="w-fit max-w-[min(560px,82%)] justify-self-end whitespace-pre-wrap break-words rounded-lg rounded-br bg-secondary px-3 py-[9px] text-ui-md leading-[1.65] text-foreground">
          {prompt}
        </div>
        {/* 和对话页的用户气泡同一个脚注:复制 + 时间。此前这里只有一个裸 <time>,
            没法把提示词捞出来 —— 而提示词正是最常要复制去改一版再生成的东西。 */}
        <MessageFooter
          content={prompt}
          className="justify-end opacity-0 transition-opacity duration-[120ms] group-hover/gen:opacity-100"
        >
          <MessageTime iso={timestamp} />
        </MessageFooter>
        {/* `@` 到的资产挂了几张参考图、没挂上的为什么(ADR 0027)。全挂上了就什么都不写。 */}
        <EntityReceiptNote receipt={entityReceipt(generation.request)} />
      </div>
      <div className="grid min-h-7 justify-items-start gap-[7px] pb-2 pt-0.5">
        {outputs.length > 0 && generation.kind === "audio" ? (
          //: 一次可能交回几首(Suno 一次两首):每一首一个播放器,而不是只放封面那一首。
          <GeneratedAudioList assetIds={outputs} title={prompt.split("\n")[0]?.slice(0, 60) || generation.model} />
        ) : generation.result_asset_id && generation.kind === "video" ? (
          <video
            className="block max-h-[420px] w-full max-w-[min(560px,100%)] rounded-lg border border-border bg-[#05070a]"
            src={assetFileUrl(generation.result_asset_id)}
            poster={assetThumbnailUrl(generation.result_asset_id)}
            controls
            preload="metadata"
          />
        ) : outputs.length > 0 ? (
          //: **照 result_asset_ids 出图,不是只出封面。** 图像接口的 n 选了几就出几张,
          //: 只画第一张的话,用户按 4 张付了钱、界面上只多出 1 张(另外 3 张在素材库里
          //: 躺着,而他不知道)。
          //:
          //: **按高度定尺寸,不按宽度铺满。** 此前多张时每张至少占半行、还会伸展:一张竖图(1080×1920)将近 500px 高,
          //: 单数的最后一张被拉成整行宽(维护者:「生成页面的图片可以稍微小一些 太大了」)。现在一张最高 360px,
          //: 多张时每张 220px 高、宽跟着比例走、不伸展,一行排得下几张排几张;点开看大图。
          <div className={cn("flex max-w-[min(720px,100%)] flex-wrap gap-1.5")}>
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
                    "block rounded-lg border border-border",
                    outputs.length > 1 ? "h-[220px] w-auto max-w-full object-contain" : "max-h-[360px] w-auto max-w-full",
                  )}
                  src={assetThumbnailUrl(assetId)}
                  alt=""
                  loading="lazy"
                />
              </IconButton>
            ))}
          </div>
        ) : status === "failed" ? (
          //: 原因读**生成记录自己**存的那份 —— 任务会被清掉,记录不会(见后端 generation.runner.record_failure)。
          <GenerationFailureCard error={generation.error ?? ""} />
        ) : status === "running" ? (
          <GeneratingTile kind={generation.kind} progress={job?.progress} />
        ) : (
          <span className="inline-flex items-center gap-1.5 py-2 text-ui-sm text-muted-foreground">
            <Loader2 size={13} className="animate-mosael-spin" /> {t("genQueued")}
          </span>
        )}
        <small className="flex flex-wrap items-center gap-2 justify-self-start text-ui-xs text-muted-foreground [&_span+span:before]:mr-2 [&_span+span:before]:content-['·']">
          <span>
            {generation.provider} · {generation.model}
          </span>
          {durationLabel ? <span>{durationLabel}</span> : null}
          {costLabel ? <span>{costLabel}</span> : null}
        </small>
      </div>
    </article>
  );
}

/**
 * 正在生成的那一条:在产出将要出现的位置先铺一块扫光占位,左下角写「生成中」和进度。
 *
 * 此前这里只有一行「转圈 + 生成中」—— 产出出来时版面从一行字跳成一张大图。占位先占住
 * 产出的位置(视频按 16:9,其余按首屏加载时那块方形),出图时原地换掉。
 * 进度只在任务真的报了(`job.progress` > 0)时才写;没报就不写,不去猜一个数。
 */
function GeneratingTile({ kind, progress }: { kind: string; progress?: number }) {
  const t = useI18n();
  const percent = typeof progress === "number" && progress > 0 ? Math.round(progress * 100) : null;
  return (
    <div
      role="status"
      aria-busy="true"
      className={cn(
        "relative w-full overflow-hidden rounded-lg",
        kind === "video"
          ? "aspect-video max-w-[min(560px,100%)]"
          : kind === "audio"
            ? "h-16 max-w-[min(560px,100%)]"
            : "aspect-square max-w-[240px]",
      )}
    >
      <Skeleton className="absolute inset-0 rounded-lg" />
      <span className="absolute inset-x-0 bottom-0 flex items-center gap-1.5 px-3 pb-2.5 pt-1.5 text-ui-xs">
        <span className="font-semibold text-primary">{t("generating")}</span>
        {percent !== null ? <span className="tabular-nums text-muted-foreground">{percent}%</span> : null}
      </span>
    </div>
  );
}

function GenerationFailureCard({ error }: { error: string }) {
  const t = useI18n();
  const [copied, setCopied] = React.useState(false);
  const summary = React.useMemo(() => generationErrorSummary(error, t("genFailed")), [error, t]);
  const copy = () => {
    if (!error) return;
    void navigator.clipboard?.writeText(error);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };

  return (
    <div className="grid w-[min(560px,100%)] gap-2 rounded-lg border border-[color-mix(in_srgb,var(--destructive)_34%,var(--border))] bg-[color-mix(in_srgb,var(--destructive)_7%,var(--card))] px-3 py-2.5">
      <div className="flex min-w-0 items-start gap-2 text-destructive">
        <CircleAlert size={14} className="mt-0.5 shrink-0" />
        <div className="grid min-w-0 gap-0.5">
          <strong className="text-ui-sm leading-[1.35] text-destructive">{t("generationFailedTitle")}</strong>
          <span className="[overflow-wrap:anywhere] text-ui-sm leading-[1.55] text-[color-mix(in_srgb,var(--destructive)_82%,var(--foreground))]">
            {summary}
          </span>
        </div>
      </div>
      {error ? (
        <div className="flex items-start justify-between gap-2">
          <details className="min-w-0 text-ui-xs text-muted-foreground">
            <summary className="w-fit cursor-pointer list-none after:ml-1 after:inline-block after:content-['›'] [&::-webkit-details-marker]:hidden">
              {t("generationErrorDetail")}
            </summary>
            <pre className="mt-[7px] max-h-40 max-w-full overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border bg-[color-mix(in_srgb,var(--background)_72%,var(--card))] p-2 font-mono text-ui-xs leading-normal text-muted-foreground">
              {error}
            </pre>
          </details>
          <Button type="button" variant="ghost" size="sm" className="h-6 shrink-0 px-[7px] text-ui-xs" onClick={copy}>
            {copied ? <Check size={12} /> : <Copy size={12} />}
            {copied ? t("copied") : t("copyMessage")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function generationErrorSummary(error: string, fallback: string): string {
  const text = error.trim();
  if (!text) return fallback;
  const bodyMatch = text.match(/body:\s*(\{.*\})\s*$/s);
  if (bodyMatch) {
    try {
      const parsed = JSON.parse(bodyMatch[1]) as { error?: { message?: unknown }; message?: unknown };
      const message = parsed.error?.message ?? parsed.message;
      if (typeof message === "string" && message.trim()) return trimErrorSummary(message);
    } catch {
      // Fall through to text cleanup.
    }
  }
  const messageMatch = text.match(/"message"\s*:\s*"([^"]+)"/);
  if (messageMatch?.[1]) return trimErrorSummary(messageMatch[1]);
  const beforeDetails = text
    .replace(/^失败\s*·\s*/i, "")
    .split(" For more information check:")[0]
    .split("; body:")[0]
    .trim();
  return trimErrorSummary(beforeDetails || fallback);
}

function trimErrorSummary(value: string): string {
  return value.replace(/\s+/g, " ").trim().slice(0, 150);
}
