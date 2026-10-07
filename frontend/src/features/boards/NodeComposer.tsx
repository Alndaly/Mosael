import type { NoteReference } from "@/api/domains/notes";
import { noteHref } from "@/lib/deepLink";
import React from "react";

import { PromptTemplateButton, withTemplate } from "@/components/app/PromptTemplates";
import { ArrowLeftRight, Plus, Sparkles } from "lucide-react";


import { type BoardItem, type GenerationOption, type SceneReferenceForm } from "@/api/client";
import { resolvedShot, SceneReferencePicker, sceneReferenceUses, useReferencedScene } from "@/features/boards/SceneReferencePicker";
import {
  collect,
  PromptEditor,
  restorePromptDocument,
  textDocument,
  type PromptDocument,
} from "@/features/boards/PromptEditor";
import { useSubmitting } from "@/features/boards/useSubmitting";
import { useAssetDetails, useMentionCandidates } from "@/lib/assetQueries";
import { useI18n } from "@/app/preferences";
import type { MessageKey } from "@/app/messages";
import { ROLE_COPY, SOURCE_ROLES, type SourceRole } from "@/lib/sourceFrames";
import { DigitalHumanConsent } from "@/components/generation/DigitalHumanConsent";
import { ParameterRow, declaredChoices } from "@/components/generation/parameterPanel";
import { IconButton } from "@/components/ui/icon-button";
import { CustomSizePicker } from "@/components/generation/CustomSizePicker";
import { ModelFilePicker } from "@/components/generation/ModelFilePicker";
import { Input } from "@/components/ui/input";
import { MenuContent, MenuItem } from "@/components/ui/menu";
import { OptionPicker, type PickerOption } from "@/components/ui/option-picker";
import { Popover, PopoverTrigger } from "@/components/ui/popover";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import {
  DURATION_UNSET,
  aspectRatioOptions,
  booleanParameterKeys,
  capabilityBoolean,
  capabilityString,
  declaredParameters,
  declaredParameterValue,
  defaultDuration,
  durationChoices,
  exclusiveSourceGroups,
  hasEnoughText,
  maxImages,
  countsRuns,
  outputsPerRun,
  runsHint,
  parameterChoiceEntries,
  pickGenerationOption,
  promptMode,
  sizeOptions,
  customSizeRule,
  sourceLabels,
  sourceLimit,
  supportsParameter,
  videoResolutionOptions,
  withTriggerWords,
} from "@/lib/generationCapabilities";
import { GENERATION_BOOLEAN_LABELS, GENERATION_PARAMETER_HINTS, GENERATION_PARAMETER_LABELS, generationParameterLabel } from "@/lib/generationParameterLabels";
import { formedGroups, generationOptionKeywords, generationOptionNames } from "@/lib/entryNames";
import { cn } from "@/lib/utils";
import { toPlainText } from "@/components/markdown/inlineSyntax";
import { BoardComposerShell } from "@/features/boards/BoardComposerShell";
import { SourceAssetSlotPreview } from "@/features/boards/SourceAssetSlotPreview";
import { AssetUploadStatus, fileKind, namedFile, useAssetUpload, wrongKindText } from "@/features/boards/assetUpload";
import { useFileDrop } from "@/lib/useFileDrop";
import { EntityThumb, matchEntities, useMentionableEntities } from "@/features/entities/EntityMention";
import { entityDisplayName } from "@/features/entities/entityMeta";

/**
 * 挂在节点**下方**的提示词面板 —— 「节点本身就是生成单元」这件事的那一半。
 *
 * ## 为什么不是「选中一项 → 点生成 → 另生一个」
 *
 * 那种做法把一次创作拆成了两个东西:一张写着想法的便签,和一张由它生成的图。用户真正在做的
 * 是**一件事** —— 「我要一张这样的图」。写提示词、挑模型、看结果、改一个字再试一次,
 * 都围着同一个格子转。拆成两个之后,改提示词要回到便签、看结果要看另一张,而它们之间
 * 只有一根线证明有关系。
 *
 * 所以:放下一个**空槽**,底下就挂着这块面板;写完提交,槽里就地变成图。改一版还是同一个格子。
 *
 * ## 位置和样子
 *
 * 外框、位置、底栏和发送键都由画板面板的壳摆(BoardComposerShell):它用 NodeToolbar 挂在节点下方,
 * 平移缩放时自己跟着节点走。这块面板是那个壳的样板 —— 写字、配音、剪一段、能力的面板都长成它这样。
 */
/** 模型和参数共用选择控件;参数在弹层中显示独立标签。 */
function Pick({
  value,
  onChange,
  options,
  label,
  icon,
  className,
  allowFreeValue,
  placeholder,
  hint,
  ariaLabel,
}: {
  value: string;
  onChange: (next: string) => void;
  options: PickerOption[];
  label?: string;
  /** 不摆标签(工具行里)时读屏念的名字。 */
  ariaLabel?: string;
  /** 值左侧的装饰图标。**交给 OptionPicker 画在触发器里面** —— 见那边的注释:
   *  包在外面就成了两个盒子,hover 和焦点环各高亮一个,而且左右内边距对不齐。 */
  icon?: React.ReactNode;
  className?: string;
  /**
   * 目录**声明了这一项、但没给可选值**时怎么办。
   *
   * 默认是消失 —— 对"这个模型根本没有这一项"来说是对的。但还有另一种处境:这条通道发得出
   * 这一项,只是没人验证过这个模型收哪些取值(中转上的新型号最常见)。那时候消失等于说
   * "没有这一项",而替它编一个清单(1024x1024 / 720p / 16:9)等于替用户做了选择,还会被
   * 原样提交 —— 两种都在说假话。
   *
   * 开了这个之后渲染成自由输入:**摆出来,但在用户填之前不带任何值**。见 ADR 0015。
   */
  allowFreeValue?: boolean;
  placeholder?: string;
  /** 悬停在标签上看到的全文(原始的「节点 · 输入名」这类)。 */
  hint?: string;
}) {
  if (options.length === 0 && !allowFreeValue) return null;
  const control = options.length === 0 ? (
    <Input
      value={value}
      onChange={(event) => onChange(event.target.value)}
      aria-label={label}
      placeholder={placeholder}
      size="sm"
      className="w-full min-w-0 text-ui-xs"
    />
  ) : (
    /* 选项一多自动换成可搜索的那一版(阈值在 OptionPicker 里)—— 模型清单动辄十几项,
       而且名字之间只差一个数字,靠滚是这个界面上最慢的动作。 */
    <OptionPicker
      value={value}
      onChange={onChange}
      options={options}
      ariaLabel={label ?? ariaLabel}
      icon={icon}
      placeholder={placeholder}
      size="sm"
      /* 带标签的排在设置弹层里,要撑满自己那一格,**和旁边的输入框同一个样子**(有边框的字段,
         和全应用的表单一家):此前下拉是无边框的深色填充、输入框是描边的浅底,并排时像两种控件。
         不带标签的活在工具行里,**按内容取宽** —— 撑满会把箭头顶到行尾,名字和箭头之间空出一大片。 */
      className={cn(
        "min-w-0 gap-1 text-ui-xs",
        label
          ? "w-full"
          : "w-auto max-w-full border-0 bg-transparent px-2 text-muted-foreground shadow-none transition-colors hover:bg-secondary",
        className,
      )}
    />
  );
  return label ? <ParameterRow label={label} title={hint}>{control}</ParameterRow> : control;
}

/** 区间时长仍用紧凑 Pick，但把 min..max 的每个合法整数都列出来。
 * 不能只把两个端点当枚举，那会把 Seedance 4–15 秒中间的 10 个合法值藏掉。 */
export function durationRangeOptions(range: { min: number; max: number }): { value: string; label: string }[] {
  const min = Math.ceil(range.min);
  const max = Math.floor(range.max);
  if (!Number.isFinite(min) || !Number.isFinite(max) || max < min) return [];
  return Array.from({ length: max - min + 1 }, (_, index) => {
    const seconds = min + index;
    return { value: String(seconds), label: `${seconds}s` };
  });
}

/** 角色的中文名 —— 和 AI 工作台共用那一份(lib/sourceFrames.ROLE_COPY),
 *  不在这里再抄一张表。 */
/** ROLE_COPY 里存的是 i18n 的 key,**不是**给人看的字 —— 不过一遍 t() 就会把
 *  「genFirstFrame」原样挂到提示上。 */
/** 一个角色收哪一类素材。**只此一处** —— 选择器开哪一类、上游哪种产出能自动挂进来,
 *  都问它;分散写两遍的话,加一个角色就会有一边忘记改。 */
export function roleAccepts(role: string): "image" | "video" | "audio" {
  //: **从 ROLE_COPY 的 accept 推**,不自己再列一张表。那里每个角色都写了文件选择器收什么
  //: (`image/*` / `video/*` / `audio/*`)—— 那就是「这个角色收哪类素材」本身。
  //:
  //: 此前这里是「参考视频→视频、参考音频→音频、**其余一律图片**」。八个角色里那条兜底判错了
  //: 三个:source_video(源视频)、first_clip(首段)是视频,driving_audio(驱动音频)是音频。
  //: 判错的后果是正文里 @ 一段视频,它会被当成图片去找槽位 —— 要么落到参考图上(厂商当场拒),
  //: 要么一个槽都找不到,那份素材**根本没发出去**,而提示词里还写着它的名字。
  const accept = ROLE_COPY[role as SourceRole]?.accept ?? "image/*";
  if (accept.startsWith("video/")) return "video";
  if (accept.startsWith("audio/")) return "audio";
  return "image";
}

/**
 * 这个模型有哪几种「生成方式」。
 *
 * **不是手写的二选一** —— 首尾帧和参考素材互斥是厂商的硬约束,后端已经在描述符的
 * `exclusive_source_groups` 里声明过了(火山原话:first/last frame content cannot be
 * mixed with reference media content)。界面只是把那份声明画成一个开关:多写一份
 * 「哪些方式」的表,换个模型就会对不上。
 *
 * 只留这个模型真认的角色;剩不下角色的组直接不出现。不足两组就没得选,返回空 =「不显示开关」。
 */
/**
 * 「参数」弹层里**会出现哪几块**。按 key 回一个清单,而不是回一个 boolean。
 *
 * 按钮的显隐和弹层的内容必须出自**同一处**。分开写的结果已经见过了:10 个图片模型里 8 个的
 * `parameter_keys` 是空的(gemini 那几族、手填的别名、gemma4…),而互斥输入组只有一组时
 * `sourceModes` 也回空 —— 于是每一个条件块都是 false,点开「参数」是一个只有标题的空盒子。
 * 这正是这个仓库一直在消灭的那种"点了没反应"。
 *
 * 回清单还有第二个用处:弹层按它渲染,新增一块参数时**漏掉按钮那一侧**这件事不可能发生。
 */
export function generationSettingBlocks(
  model: GenerationOption | null,
  options: { modes: number; durations: number },
): string[] {
  const blocks: string[] = [];
  if (options.modes > 0) blocks.push("mode");
  for (const key of ["aspect_ratio", "resolution", "size"]) {
    if (supportsParameter(model, key)) blocks.push(key);
  }
  //: 门槛是"声明了这一项",不是"有可选值"。没有可选值时它渲染成自由输入 —— 那也是一格,
  //: 漏掉它会让「参数」按钮在只剩自由输入项时不出现,于是那些项点不开(显隐和内容共用这份清单)。
  if (supportsParameter(model, "duration_seconds")) blocks.push("duration_seconds");
  blocks.push(...booleanParameterKeys(model).filter((key) => key !== "generate_audio"));
  blocks.push(...parameterChoiceEntries(model).map(([key]) => key));
  //: 模型自己声明的参数(插件生成供应商的每张工作流一套)也是一块 —— 否则 ComfyUI 那些
  //: 采样器、步数只在 AI 工作台里调得了,画板上的同一个模型少了一截。
  blocks.push(...declaredParameters(model).map((parameter) => parameter.key));
  if (supportsParameter(model, "generate_audio")) blocks.push("generate_audio");
  return blocks;
}

export function sourceModes(model: GenerationOption | null): { key: string; roles: string[] }[] {
  const groups = exclusiveSourceGroups(model)
    .map((roles) => roles.filter((role) => supportsParameter(model, role)))
    .filter((roles) => roles.length > 0)
    .map((roles) => ({ key: roles[0], roles }));
  return groups.length >= 2 ? groups : [];
}

/** 这一组在界面上叫什么。**从组成员推**,不另立一张表 —— 表会和描述符各走各的。 */
/** 这一组角色叫什么。**回的是 i18n 的 key** —— 这个名字要出现在参数行的下拉里。 */
export function modeLabel(roles: string[]): MessageKey {
  return roles.some((role) => role.endsWith("_frame")) ? "boardModeKeyframes" : "boardModeReference";
}

/**
 * 提交时要发出去的输入素材:**槽位挂的 + 正文里 @ 到的**。
 *
 * 两条规矩,错了都不报错:
 *
 *  · **同一份不发两遍。** 有些厂商会把重复的那一份也算进参考图的份数,挂到上限就直接拒了 ——
 *    而用户看到的只是一句英文报错,他并不知道自己"挂了两次"。
 *  · **落不下的就不发。** 正文里的 @ 没有角色,得找一个收得下它的槽;一个都没有(比如
 *    这个模型不认参考视频)就跳过,硬塞会被描述符校验当场拒掉,连带整次生成都发不出去。
 */
export function mergeSourceAssets(
  attached: { role: string; assetId: string }[],
  mentioned: string[],
  library: { id: string; kind: string }[],
  slots: { role: string; limit: number }[],
): { asset_id: string; role: string }[] {
  const out = attached.map((one) => ({ asset_id: one.assetId, role: one.role }));
  const seen = new Set(out.map((one) => one.asset_id));
  //: 每个角色已经占了几份。**槽位里挂着的先算进去** —— 首帧只收一份而槽位里已经有一张时,
  //: 正文里再 @ 一张图,它不该也变成首帧。
  const used = new Map<string, number>();
  for (const one of out) used.set(one.role, (used.get(one.role) ?? 0) + 1);
  for (const assetId of mentioned) {
    if (seen.has(assetId)) continue;
    const kind = library.find((asset) => asset.id === assetId)?.kind;
    //: **找一个收得下、而且还装得下的槽。** 只看类型不看份数的话,@ 三张图会一起挂到同一个
    //: 只收一份的角色上 —— 后端照描述符校验,把**整次生成**拒掉,而用户看到的只是一句
    //: 「首帧最多 1 份」:他并不觉得自己在设首帧,他只是在句子里提了三张图。
    const slot = slots.find((one) => roleAccepts(one.role) === kind && (used.get(one.role) ?? 0) < one.limit);
    if (!slot) continue;
    seen.add(assetId);
    used.set(slot.role, (used.get(slot.role) ?? 0) + 1);
    out.push({ asset_id: assetId, role: slot.role });
  }
  return out;
}

/** 这个模型认哪几种输入素材、各能挂几份。
 *
 * **认不认看 supportsParameter(描述符的 parameter_keys),能挂几份才看 sourceLimit。**
 * sourceLimit 对没声明的角色兜底返回 1,拿它当支持判定用的话,图片模型也会长出首尾帧槽。
 * `names` 是这个角色的槽位按顺序叫什么(描述符的 `source_labels`,ADR 0038 §4):第 i 份素材的提示用第 i 个名字。
 */
export function sourceSlots(
  model: GenerationOption | null,
  /** 当前生成方式的角色。给了就只出这一组 —— 互斥的另一组同时摆出来,挂满了才在提交时被拒。 */
  activeRoles?: string[],
): { role: string; limit: number; names: string[] }[] {
  if (!model) return [];
  //: **八个角色全在这儿**,由描述符筛。此前只列了前五个 —— 于是声明了源视频/首段/驱动音频的
  //: 模型(比如万相的视频重绘)在画板上一个对应的格子都没有,那几种能力等于用不了。
  //: 顺序就是出格子的顺序:先首尾帧,再参考,最后那三种整段素材。
  return SOURCE_ROLES.filter((role) => supportsParameter(model, role))
    .filter((role) => !activeRoles || activeRoles.includes(role))
    .map((role) => ({ role, limit: sourceLimit(model, role), names: sourceLabels(model, role) }));
}

/**
 * 这一组角色能不能收成**一个**格子。
 *
 * 判据不是「这是不是全能参考」—— 按模式名写死会变成第二张要跟着描述符走的表。判据是
 * **这组里每种媒体类型只出现一次**:那样一份素材归哪个角色由它自己的类型唯一决定,用户
 * 没有可选的余地,而三个长得一模一样、只靠 tooltip 区分的虚线框就只是在让他猜。
 *
 * 同类型有两个角色时必须分开,那时候格子数量是真的在表达信息:
 *
 *   · 首尾帧 —— 两个都是图片,而且有方向(哪一张是开头);
 *   · 视频编辑 / 续写 —— reference_video 与 source_video / first_clip 都是视频。
 *
 * 各类型的份数上限**按模型各不相同**(9/3/3 只是火山与 MiniMax 恰好一致),所以合并之后
 * 「还能加几份」要按 slot.limit 现算,不能在文案里写死数字。
 */
export function mergeableSourceSlots<T extends { role: string }>(slots: T[]): T[] | null {
  if (slots.length < 2) return null;
  const kinds = slots.map((slot) => roleAccepts(slot.role));
  return new Set(kinds).size === kinds.length ? slots : null;
}

/**
 * 参考素材栏先展示已经挂上的内容，再展示尚可添加的角色。
 *
 * 角色的原始顺序仍决定自动分配和提交语义；这里只调整展示。首尾帧是有方向的固定序列，不能因为
 * 尾帧先填就把它搬到首帧前面。参考图/视频/音频没有方向，已连接的音频若排在两个通用 `+` 后面，
 * 看起来就像前两份素材加载失败。
 */
export function prioritizeFilledSourceSlots<T extends { role: string }>(
  slots: T[],
  sources: { role: string; assetId: string }[],
): T[] {
  if (slots.some((slot) => slot.role.endsWith("_frame"))) return slots;
  const filledRoles = new Set(sources.map((source) => source.role));
  return [
    ...slots.filter((slot) => filledRoles.has(slot.role)),
    ...slots.filter((slot) => !filledRoles.has(slot.role)),
  ];
}

/**
 * 把上游节点的产出自动挂到槽位上,按槽位顺序、各自的份数上限来。
 *
 * 连了线却还要再挂一遍素材,那条线就只是根装饰。类别对不上的跳过(视频挂不进首帧),
 * 装不下的也跳过 —— 宁可少挂一张,也不要把用户没连的东西塞进去。
 */
export function autoAssign(
  slots: { role: string; limit: number }[],
  upstream: { assetId: string; kind: string; itemId?: string }[],
): SlotSource[] {
  const taken = new Set<string>();
  const out: SlotSource[] = [];
  for (const slot of slots) {
    for (const one of upstream) {
      if (out.filter((x) => x.role === slot.role).length >= slot.limit) break;
      if (taken.has(one.assetId) || one.kind !== roleAccepts(slot.role)) continue;
      taken.add(one.assetId);
      //: 顺着线挂上的记下是从哪一格来的 —— 线断了、上游换了素材,服务端存的时候把它摘掉。
      out.push({ role: slot.role, assetId: one.assetId, ...(one.itemId ? { from: one.itemId } : {}) });
    }
  }
  return out;
}

/** 槽位里挂着的一份。`from`:顺着哪一格连过来的线挂上的(手动挂的没有)。 */
export type SlotSource = { role: string; assetId: string; from?: string };

/**
 * 连进来、这个模型却**一份都挂不上**的素材种类:现在这种生成方式没有收它的槽(`elsewhere`:换一种生成方式收得下)。
 *
 * 此前这种素材悄悄不挂(见 autoAssign):一格图连到只收提示词的模型上(比如读图节点在 ComfyUI 里旁路了的工作流),
 * 点生成照样跑,图没用上,哪儿都没说 —— 用户只能当成「明明能参考图片,这里却不行」。挂满了、自己摘掉的不算:
 * 那是收得下、只是这一次没用。
 */
export function unusedUpstreamKinds(
  model: GenerationOption | null,
  activeRoles: string[] | undefined,
  upstream: { kind: string }[],
): { kind: "image" | "video" | "audio"; elsewhere: boolean }[] {
  if (!model) return [];
  const now = new Set<string>(sourceSlots(model, activeRoles).map((slot) => roleAccepts(slot.role)));
  const anyMode = new Set<string>(sourceSlots(model).map((slot) => roleAccepts(slot.role)));
  const kinds = [...new Set(upstream.map((one) => one.kind))].filter(
    (kind): kind is "image" | "video" | "audio" => (kind === "image" || kind === "video" || kind === "audio") && !now.has(kind),
  );
  return kinds.map((kind) => ({ kind, elsewhere: anyMode.has(kind) }));
}

const UNUSED_UPSTREAM_COPY: Record<"image" | "video" | "audio", { model: MessageKey; mode: MessageKey }> = {
  image: { model: "boardUpstreamUnusedImage", mode: "boardUpstreamUnusedModeImage" },
  video: { model: "boardUpstreamUnusedVideo", mode: "boardUpstreamUnusedModeVideo" },
  audio: { model: "boardUpstreamUnusedAudio", mode: "boardUpstreamUnusedModeAudio" },
};

/**
 * 上游连了这些东西时,默认该用哪种生成方式。
 *
 * 照 TapNow 的直觉:**连一张图 = 拿它当首帧**(最常见的图生视频),连两张以上就说明用户
 * 想要的是「像这些」而不是「从这张开始」,于是切到参考。装不下的组不选。
 */
export function defaultMode(
  modes: { key: string; roles: string[] }[],
  model: GenerationOption | null,
  upstream: { assetId: string; kind: string }[],
): string {
  if (modes.length === 0) return "";
  const fits = (mode: { roles: string[] }) =>
    autoAssign(sourceSlots(model, mode.roles), upstream).length;
  const keyframe = modes.find((mode) => mode.roles.some((role) => role.endsWith("_frame")));
  if (upstream.length === 1 && keyframe && fits(keyframe) === 1) return keyframe.key;
  //: 挂得下最多张的那组胜出;都挂不下就维持第一组。
  const best = modes.reduce((a, b) => (fits(b) > fits(a) ? b : a));
  return fits(best) > 0 ? best.key : modes[0].key;
}

/**
 * 「+」槽收拖上来的文件:悬着的时候框亮起来,松手交给 `onFiles`(收不收、挂哪个槽由面板判)。
 * 收不了的也交过去 —— 由面板说为什么,而不是松手之后什么都不发生。
 */
function SlotDrop({ onFiles, children }: { onFiles: (files: File[]) => void; children: React.ReactNode }) {
  const drop = useFileDrop(onFiles);
  return (
    <span
      {...drop.handlers}
      data-slot-drop={drop.active ? "active" : ""}
      className={cn("inline-flex shrink-0 rounded-md", drop.active && "ring-2 ring-primary ring-offset-1 ring-offset-background")}
    >
      {children}
    </span>
  );
}

function roleLabel(t: ReturnType<typeof useI18n>, role: string): string {
  const key = ROLE_COPY[role as SourceRole]?.label;
  return key ? t(key as Parameters<typeof t>[0]) : role;
}

/** 一个角色的第 `index` 格叫什么:模型给了槽位名字(`source_labels`)就是「参考图 · 人物」,没给就是角色名。 */
function slotLabel(t: ReturnType<typeof useI18n>, slot: { role: string; names?: string[] }, index: number): string {
  const named = slot.names?.[index];
  return named ? `${roleLabel(t, slot.role)} · ${named}` : roleLabel(t, slot.role);
}

export function NodeComposer({
  item,
  models,
  busy,
  onSubmit,
  onPickAsset,
  upstream,
  upstreamTexts,
  upstreamDocuments,
  upstreamEntities,
  upstreamScene,
  workspaceId,
  onFormChange,
}: {
  item: BoardItem;
  /** 这种能力下可选的模型。空数组 = 还没配 —— 那时该说清楚,而不是给一个点了没反应的按钮。 */
  models: GenerationOption[];
  busy: boolean;
  onSubmit: (input: {
    prompt: string;
    provider: string;
    providerProfileId: string;
    model: string;
    parameters: Record<string, unknown>;
    sourceAssets: { asset_id: string; role: string }[];
    /** 正文里 `@` 到的资产(ADR 0027)。连进来的资产格不在这里 —— 服务端按连线取。 */
    entityIds: string[];
    /** 连进来的 3D 场景怎么用(ADR 0029);没连场景时不给。 */
    sceneReference?: SceneReferenceForm;
    /** 挂了驱动音频(数字人)时,本人勾上的「已取得画面中人物的授权」。 */
    digitalHumanConsent: boolean;
    form: NonNullable<BoardItem["form"]>;
    //: 交回请求的 Promise:按钮转到它落地为止(见 useSubmitting),连点只发一次。
  }) => Promise<unknown>;
  /** 每一次编辑都写回节点，而不是留在面板组件的临时 state 里。 */
  onFormChange: (form: NonNullable<BoardItem["form"]>) => void;
  /** 挂输入素材时开选择器 —— 和画布上「换一份」用的是同一个。 */
  onPickAsset: (kind: "image" | "video" | "audio", place: (assetId: string) => void) => void;
  /** **连到这个节点上的上游产出**,按连线顺序。它们会自动挂进当前生成方式的槽位 ——
   *  连了线还要再挂一遍素材的话,那条线就只是根装饰。 */
  upstream?: { assetId: string; kind: string }[];
  /** 上游**便签**给的文字。一张写着描述的便签连过来,意思是「照这段话画」—— 它不是参考图
   *  (便签根本没有图),而是提示词本身。 */
  upstreamTexts?: { itemId: string; text: string }[];
  /** 连进这一格的文档格给的文档。这里只把它们摆在上面那一排(哪一篇、哪一版);正文由服务端按连线交给模型
   *  (boards.actions.upstream_documents),不拼进提示词。 */
  upstreamDocuments?: NoteReference[];
  /** 连进这一格的资产格引用的资产(ADR 0027)。生成时服务端按连线把它们当成 `@` 了一样挂上;
   *  这里只用来把它们排在 `@` 菜单的「连进来的」那一组。 */
  upstreamEntities?: string[];
  /** 连进这一格的 3D 场景格给的场景(ADR 0029)。生成时服务端现渲它的一个镜头当参考;这里挑镜头和用法。 */
  upstreamScene?: string;
  /** `@` 引用素材时去哪个工作区找。 */
  workspaceId: string;
}) {
  const t = useI18n();
  const saved = item.form ?? {};
  const [prompt, setPrompt] = React.useState(saved.prompt ?? item.text ?? "");
  const [promptDocument, setPromptDocument] = React.useState<PromptDocument | undefined>(
    saved.prompt_document as PromptDocument | undefined,
  );
  const [sceneReference, setSceneReference] = React.useState<SceneReferenceForm>(
    saved.scene_reference ?? { shot_id: "", use: "composition" },
  );
  const [picked, setPicked] = React.useState(
    saved.provider_profile_id && saved.model ? `${saved.provider_profile_id}:${saved.model}` : "",
  );

  const options = React.useMemo(
    () => models.filter((model) => model.kind === item.kind),
    [models, item.kind],
  );
  //: 存着的那个 → 用户设的默认 → 没有(显示「选择模型」,发不出去)。**不拿第一项顶上**:清单按连接名
  //: 排序,第一项不是谁的选择(见 pickGenerationOption)。
  const current = pickGenerationOption(options, {
    saved: picked ? (model) => `${model.provider_profile_id}:${model.model}` === picked : null,
  });
  //: 显示的就是**实际要用的**那一个。存着的模型不在清单里(被删了、那条通道停了、不再被认成这种生成)
  //: 时 current 已经落到默认或空,选择器不能还挂着那个不存在的值 —— 显示的和发出去的不是同一个模型。
  //: 有表单的那几张工作流:完整工作流的副名写「完整工作流」(ADR 0045)
  const formed = React.useMemo(() => formedGroups(options), [options]);
  const modelValue = current ? `${current.provider_profile_id}:${current.model}` : "";

  //: 每一项的默认值都**从描述符取**(default_* 那几条),而不是前端挑一个 —— 后端那份才是
  //: 对着真机核过的。换模型时跟着换,所以用 key 重挂而不是 useState 记着上一个模型的值。
  const savedParameters = saved.parameters ?? {};
  const [ratio, setRatio] = React.useState(() => String(savedParameters.aspect_ratio ?? capabilityString(current, "default_aspect_ratio", aspectRatioOptions(current)[0] ?? "")));
  const [resolution, setResolution] = React.useState(() => String(savedParameters.resolution ?? capabilityString(current, "default_resolution", videoResolutionOptions(current)[0] ?? "")));
  const [size, setSize] = React.useState(() => String(savedParameters.size ?? capabilityString(current, "default_size", sizeOptions(current)[0] ?? "")));
  //: 尺寸只是推荐值(ComfyUI 的工作流):下拉里也能手填「宽x高」
  const customSize = customSizeRule(current);
  const [duration, setDuration] = React.useState(() => Number(savedParameters.duration_seconds ?? defaultDuration(current)));
  const durations = durationChoices(current, resolution);
  const [audio, setAudio] = React.useState(() =>
    savedParameters.generate_audio === undefined
      ? capabilityBoolean(current, "default_generate_audio")
      : Boolean(savedParameters.generate_audio),
  );
  const booleanKeys = booleanParameterKeys(current).filter((key) => key !== "generate_audio");
  const [booleanParameters, setBooleanParameters] = React.useState<Record<string, boolean>>(() =>
    Object.fromEntries(
      booleanKeys.map((key) => [
        key,
        savedParameters[key] === undefined
          ? capabilityBoolean(current, `default_${key}`)
          : Boolean(savedParameters[key]),
      ]),
    ),
  );
  const enumEntries = parameterChoiceEntries(current);
  const [enumParameters, setEnumParameters] = React.useState<Record<string, string>>(() =>
    Object.fromEntries(enumEntries.map(([key, choices]) => [
      key,
      String(savedParameters[key] ?? capabilityString(current, `default_${key}`, choices[0] ?? "")),
    ])),
  );
  //: 模型自己声明的参数里**用户动过的**那些(控件原文)。没动过的不存、不发(ADR 0015)。
  const [declared, setDeclared] = React.useState<Record<string, string>>(() =>
    Object.fromEntries(
      declaredParameters(current)
        .filter((parameter) => savedParameters[parameter.key] !== undefined)
        .map((parameter) => [parameter.key, String(savedParameters[parameter.key])]),
    ),
  );
  const [count, setCount] = React.useState(Number(savedParameters.num_images ?? 1));
  React.useEffect(() => {
    if (durations.length > 0 && !durations.includes(duration)) setDuration(durations[0]);
  }, [durations, duration]);
  //: 挂上去的输入素材,按角色分。**角色和上限都由描述符说了算** —— 参考图九张还是三张、
  //: 认不认尾帧,每个模型不一样;写死一套的话换个模型就要么少给要么超限。
  const [sources, setSources] = React.useState<SlotSource[]>(() =>
    (saved.source_assets ?? []).map((one) => ({ role: one.role, assetId: one.asset_id, ...(one.from ? { from: one.from } : {}) })),
  );

  //: 「生成方式」= 描述符里那几个互斥分组。摆出来的槽只属于当前这一组 —— 两组同时摆着,
  //: 用户挂满了才会在提交时被拒。
  const feed = React.useMemo(() => upstream ?? [], [upstream]);
  const texts = React.useMemo(() => upstreamTexts ?? [], [upstreamTexts]);
  const modes = React.useMemo(() => sourceModes(current), [current]);
  const [mode, setMode] = React.useState(saved.mode ?? "");
  const activeMode = modes.find((one) => one.key === mode) ?? modes[0] ?? null;
  //: 这个模型有没有可调参数。**按钮和弹层共用它** —— 见 generationSettingBlocks 的说明。
  const settingBlocks = React.useMemo(
    () => generationSettingBlocks(current, { modes: modes.length, durations: durations.length }),
    [current, modes.length, durations.length],
  );

  //: 这个模型认哪几种输入素材,各能挂几份。首尾帧和参考图**分属互斥的两组**(厂商硬约束),
  //: 描述符里已经声明过 —— 这里只按它出格子,不自己判。
  const slots = React.useMemo(
    () => sourceSlots(current, activeMode?.roles),
    [current, activeMode],
  );
  const displaySlots = React.useMemo(
    () => prioritizeFilledSourceSlots(slots, sources),
    [slots, sources],
  );

  //: 每种媒体类型只出现一次时收成一个格子 —— 见 mergeableSourceSlots。首尾帧、视频编辑那种
  //: 同类型两个角色的组合仍旧一格一个,那时候格子数量是真的在表达信息。
  const mergedSlots = React.useMemo(() => mergeableSourceSlots(displaySlots), [displaySlots]);
  const [addOpen, setAddOpen] = React.useState(false);

  /**
   * 本地文件**直接挂进槽**(拖到「+」上、面板里 ⌘V,见 assetUpload):挑第一个这几个槽收得下的文件(按它自己的种类
   * 找还有空位的那个角色),传进素材库、挂上去。一个都收不下就就地说一句,不传。
   */
  const upload = useAssetUpload(workspaceId);
  const attachFiles = (files: File[], roles: readonly string[]) => {
    const open = roles.filter((role) => {
      const limit = slots.find((slot) => slot.role === role)?.limit ?? 0;
      return sources.filter((one) => one.role === role).length < limit;
    });
    for (const file of files) {
      const role = open.find((one) => roleAccepts(one) === fileKind(file));
      if (!role) continue;
      upload.start(file, (asset) => setSources((all) => [...all, { role, assetId: asset.id }]));
      return;
    }
    const kinds = new Set(roles.map(roleAccepts));
    const [only] = kinds;
    if (files[0]) upload.reject(wrongKindText(t, files[0], kinds.size === 1 && only ? only : "media"));
  };
  const pasteIntoSlots = (event: React.ClipboardEvent) => {
    const files = Array.from(event.clipboardData?.files ?? []);
    if (!files.length || !slots.length) return;
    event.preventDefault();
    attachFiles(files.map(namedFile), slots.map((slot) => slot.role));
  };

  //: 换模型、换方式、或者上游连线变了 —— 都重新照上游挂一遍。
  //:
  //: 这三件事任一变化,原来挂着的东西就可能已经不属于现在这组槽位了(尾帧换到参考组里
  //: 没有对应的槽),留着它只会在提交时被后端拒。手动增删在下一次变化前一直有效。
  const feedKey = `${modelValue}|${activeMode?.key ?? ""}|${feed.map((one) => one.assetId).join(",")}`;
  const lastFeed = React.useRef(saved.source_assets?.length ? feedKey : "");
  React.useEffect(() => {
    if (lastFeed.current === feedKey) return;
    lastFeed.current = feedKey;
    setSources(autoAssign(sourceSlots(current, activeMode?.roles), feed));
  }, [feedKey, current, activeMode, feed]);

  /**
   * 上游便签的文字**填进提示词**。
   *
   * 连一张写着描述的便签到图片上,意思就是「照这段话画」—— 让用户再把那段字抄一遍,那条线
   * 就白连了。但**不覆盖他自己写的**:只有输入框还空着、或者里面正好是上一次自动填进去的
   * 那段时才替换;他改过或删掉之后就不再回填(那本身就是一次表态)。
   */
  //:
  //: **正文和文档一起换。** 提示词框照文档画(document 优先于 value):只换 prompt 的话,框里
  //: 还是旧的那份文档(比如删空之后留下的空段落),填进去的字看不见,提交出去的却是它。
  //: **上一次自动填进去的那段存在表单上**(`form.prefilled`),不记在面板里:重新选中这一格时面板是新挂的,记在
  //: 面板里的话一挂就忘了 —— 上游改了字,重新选中下游,提示词还停在旧的那段。
  const textKey = texts.map((one) => `${one.itemId}:${one.text}`).join("|");
  /** 把选中 LoRA 的触发词接进提示词:接在最后一段末尾,**不重建文档** —— 重建会把 `@` 过的素材抹成纯文字。 */
  const appendTriggers = (words: string[]) => {
    const next = withTriggerWords(prompt, words);
    if (next === prompt) return;
    const added = next.slice(prompt.replace(/[\s,，]+$/u, "").length);
    const base = promptDocument ?? textDocument(prompt);
    const blocks = (base.content ?? []).filter((block) => (block.content ?? []).length > 0);
    const last = blocks[blocks.length - 1];
    setPrompt(next);
    setPromptDocument(
      last
        ? { ...base, content: [...blocks.slice(0, -1), { ...last, content: [...(last.content ?? []), { type: "text", text: added }] }] }
        : textDocument(next),
    );
  };
  const [prefilled, setPrefilled] = React.useState(saved.prefilled ?? "");
  const promptNow = React.useRef(prompt);
  promptNow.current = prompt;
  const prefilledNow = React.useRef(prefilled);
  prefilledNow.current = prefilled;
  React.useEffect(() => {
    const joined = texts.map((one) => one.text).join("\n\n");
    if (!joined || joined === prefilledNow.current) return;
    const current = promptNow.current;
    if (current.trim() === "" || current === prefilledNow.current) {
      setPrompt(joined);
      setPromptDocument(textDocument(joined));
      setMentioned([]);
    }
    setPrefilled(joined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [textKey]);

  /**
   * `@` 引用素材的候选。**挑中的挂到槽位上,不写进提示词** —— 正文里留着「@猫.png」的话,
   * 模型会把这几个字当成描述念出来。
   *
   * 只列这个模型**收得下**的类别:它一个视频槽都没有的时候,把视频列出来等于让用户选一个
   * 挂不上去的东西。
   */
  //: 在服务端按这几种、敲的字搜(见 useMentionCandidates):提示词编辑器每次 query 变了问一次,等它回来再画菜单。
  const accepted = React.useMemo(() => new Set(slots.map((slot) => roleAccepts(slot.role))), [slots]);
  const acceptedKinds = React.useMemo(() => [...accepted].sort(), [accepted]);
  const candidates = useMentionCandidates(workspaceId, acceptedKinds);

  //: 正文里 chip 引用到的素材。它们和上面那排槽位是**两件事**:槽位挂的是首帧/参考这种
  //: 有角色的位置,而 chip 是「我在这句话里指的是这张图」。提交时两边都进 source_assets。
  const [mentioned, setMentioned] = React.useState<string[]>(saved.mentioned_asset_ids ?? []);
  //: 正文里 `@` 到的资产(ADR 0027):它们的提示词描述和参考图由服务端挂上,这里只记是哪几个。
  const [mentionedEntities, setMentionedEntities] = React.useState<string[]>(saved.mentioned_entity_ids ?? []);
  const mentionable = useMentionableEntities(workspaceId);
  const entityCandidates = React.useCallback(
    (query: string) => matchEntities(mentionable.data, query).slice(0, 6),
    [mentionable.data],
  );
  //: 槽位里挂着的和正文里 @ 到的那几份,按 id 取:槽位的预览要真实种类,恢复 chip 要名字,分到哪个槽要种类。
  const referencedIds = React.useMemo(
    () => [...sources.map((one) => one.assetId), ...mentioned],
    [sources, mentioned],
  );
  const referenced = useAssetDetails(referencedIds);
  const assetKindById = React.useMemo(
    () => new Map([...referenced.byId.values()].map((asset) => [asset.id, asset.kind])),
    [referenced.byId],
  );
  React.useEffect(() => {
    if (promptDocument || mentioned.length === 0 || !referenced.settled || referenced.byId.size === 0) return;
    const restored = restorePromptDocument(prompt, mentioned, [...referenced.byId.values()]);
    if (collect(restored as { content?: unknown[] }).length > 0) setPromptDocument(restored);
  }, [promptDocument, prompt, mentioned, referenced]);

  //: 上游变了就重挑一次默认方式:一张图 = 首帧,多张 = 参考(TapNow 的那套直觉)。
  //: 用户自己点过之后,这条不再插手 —— touched 记着这件事。
  const touched = React.useRef(Boolean(saved.mode));
  const feedIds = feed.map((one) => one.assetId).join(",");
  React.useEffect(() => {
    if (touched.current || modes.length === 0) return;
    setMode(defaultMode(modes, current, feed));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [feedIds, modes.length]);

  //: 点下去立刻转、落地就停(**失败也要停** —— 否则那个圈会一直转下去)。见 useSubmitting。
  const { submitting, run } = useSubmitting();
  const working = submitting || busy;

  //: 这个模型有没有张数(`num_images`):有才摆「N×」、才发。没声明的模型(视频、没有 batch_size 的 ComfyUI 工作流)
  //: 发了也会被校验拦下 —— 和 AI 工作台同一个判据。
  const batches = supportsParameter(current, "num_images") && maxImages(current) > 1;
  const formParameters = React.useMemo(() => {
    const parameters: Record<string, unknown> = {};
    if (supportsParameter(current, "aspect_ratio") && ratio) parameters.aspect_ratio = ratio;
    if (supportsParameter(current, "resolution") && resolution) parameters.resolution = resolution;
    if (supportsParameter(current, "size") && size) parameters.size = size;
    //: **0 = 未设置,不发。** 此前这里无条件发,而目录没给时长时界面会编一个 5 出来 ——
    //: 用户没选过时长,成片却是 5 秒。见 ADR 0015 与 lib/generationCapabilities.DURATION_UNSET。
    if (supportsParameter(current, "duration_seconds") && duration !== DURATION_UNSET) {
      parameters.duration_seconds = duration;
    }
    // 布尔值必须显式发送两边。只在 true 时发送会让“静音”落回供应商默认；Evolink
    // Seedance 2.5 的默认恰好是有声，于是 UI 显示静音、成片却带声音。
    if (supportsParameter(current, "generate_audio")) parameters.generate_audio = audio;
    for (const key of booleanKeys) parameters[key] = booleanParameters[key] ?? capabilityBoolean(current, `default_${key}`);
    for (const [key, choices] of enumEntries) {
      const value = enumParameters[key] ?? capabilityString(current, `default_${key}`, choices[0] ?? "");
      if (value) parameters[key] = value;
    }
    for (const parameter of declaredParameters(current)) {
      const value = declaredParameterValue(parameter, declared[parameter.key] ?? "");
      if (value !== undefined) parameters[parameter.key] = value;
    }
    if (batches && count > 1) parameters.num_images = count;
    return parameters;
  }, [current, ratio, resolution, size, duration, audio, booleanKeys, booleanParameters, enumEntries, enumParameters, declared, count, batches]);
  //: 张数为 1 时一次交回几份(ComfyUI 一张工作流几个保存节点;「结果取自」选了一个就是 1)。「N×」上显示的是
  //: 这一次会落出几格(= 这个数 × 张数),和画板一次摆好的占位一样多。
  const perRun = outputsPerRun(current, formParameters);
  const runs = countsRuns(current);

  const editableForm = React.useMemo<NonNullable<BoardItem["form"]>>(
    () => ({
      prompt,
      prompt_document: promptDocument,
      ...(prefilled ? { prefilled } : {}),
      provider: current?.provider ?? saved.provider,
      provider_profile_id: current?.provider_profile_id ?? saved.provider_profile_id,
      model: current?.model ?? saved.model,
      mode: activeMode?.key ?? mode,
      parameters: formParameters,
      source_assets: sources.map((one) => ({ asset_id: one.assetId, role: one.role, ...(one.from ? { from: one.from } : {}) })),
      mentioned_asset_ids: mentioned,
      ...(mentionedEntities.length > 0 || saved.mentioned_entity_ids ? { mentioned_entity_ids: mentionedEntities } : {}),
      ...(upstreamScene || saved.scene_reference ? { scene_reference: sceneReference } : {}),
    }),
    [prompt, promptDocument, prefilled, current, saved.provider, saved.provider_profile_id, saved.model, activeMode, mode, formParameters, sources, mentioned, mentionedEntities, saved.mentioned_entity_ids, upstreamScene, saved.scene_reference, sceneReference],
  );
  const serializedForm = React.useMemo(() => JSON.stringify(editableForm), [editableForm]);
  const lastSavedForm = React.useRef(JSON.stringify(item.form ?? {}));
  React.useEffect(() => {
    if (serializedForm === lastSavedForm.current) return;
    lastSavedForm.current = serializedForm;
    onFormChange(JSON.parse(serializedForm) as NonNullable<BoardItem["form"]>);
  }, [serializedForm, onFormChange]);

  //: 这个模型对提示词的要求(见 promptMode):不收的不摆编辑器、发空串;可以不写的,空着也能跑。
  const currentPromptMode = promptMode(current);
  //: 连了 3D 场景:这个模型收得下哪几种用法(一种都没有时发不出去 —— 服务端照连线一定会现渲它)。
  const sceneUses = sceneReferenceUses(current, item.kind);
  const sceneUse = sceneUses.includes(sceneReference.use) ? sceneReference.use : sceneUses[0];
  const referencedScene = useReferencedScene(workspaceId, upstreamScene);
  //: 这次用哪个镜头(挑过的还在场景里 / 只有一个镜头)。好几个镜头却没挑、场景还没查到时发不出去 —— 服务端不猜镜头。
  const sceneShot = resolvedShot(referencedScene, sceneReference.shot_id);
  const sceneReady = !upstreamScene || (sceneUses.length > 0 && Boolean(referencedScene) && Boolean(sceneShot));
  //: 挂了驱动音频 = 数字人生成:要勾上授权才发得出去(后端生成漏斗同一条)。不存进格子的表单 —— 每次发都要本人勾。
  //: 按**发出去的**那一份判:正文里 `@` 到的一段音频也会落进驱动音频的槽(见 mergeSourceAssets)。
  const [digitalHumanConsent, setDigitalHumanConsent] = React.useState(false);
  const outgoingSources = mergeSourceAssets(sources, currentPromptMode === "none" ? [] : mentioned, [...referenced.byId.values()], slots);
  const needsDigitalHumanConsent = outgoingSources.some((one) => one.role === "driving_audio");
  const canSend =
    Boolean(current) && hasEnoughText(current, prompt) && sceneReady && (!needsDigitalHumanConsent || digitalHumanConsent);

  const send = () => {
    //: 不收提示词的模型:编辑器里残留的字(换模型之前写的)不跟着发出去。
    const text = currentPromptMode === "none" ? "" : prompt.trim();
    if (!canSend || !current || working) return;
    //: 只发这个模型**认的**那几项 —— 多发一项会被校验器当场拦下(它照描述符判)。
    const parameters = formParameters;
    //: 槽位挂的 + 正文里 @ 到的,都要发出去。**同一份素材不发两遍** —— 有些厂商会把
    //: 重复的那一份也算进参考图的份数,挂到上限就直接拒了。正文里的 @ 没有角色,
    //: 落到第一个收得下它的槽上(通常就是参考图)。
    //: 编辑器藏起来时,里面残留的 @ 也不算数 —— 用户看不见的引用不该发出去。
    const sourceAssets = outgoingSources;
    //: 只发用户写的那句。正文里写的是名字,而模型收到的是一串没有名字的素材 —— 那段「参考图 1 = 创作者.png」的
    //: 对照,和连进来的文档正文,都由后端按连线补给模型(见 boards.actions.generate_on_board),不拼进这里:拼进来的话
    //: 生成记录上存的就是拼过的字,AI 工作台的用户气泡会把文档正文当成他说的话画出来。
    run(() =>
      onSubmit({
        prompt: text,
        provider: current.provider,
        providerProfileId: current.provider_profile_id,
        model: current.model,
        parameters,
        sourceAssets,
        entityIds: mentionedEntities,
        ...(upstreamScene && sceneUse ? { sceneReference: { shot_id: sceneShot, use: sceneUse } } : {}),
        digitalHumanConsent: needsDigitalHumanConsent && digitalHumanConsent,
        form: editableForm,
      }),
    );
  };

  //: 换模型:每一项参数回到新模型描述符里的默认值,生成方式交还给「按上游挑」。
  const pickModel = (next: string) => {
    setPicked(next);
    const target = options.find((one) => `${one.provider_profile_id}:${one.model}` === next) ?? null;
    setRatio(capabilityString(target, "default_aspect_ratio", aspectRatioOptions(target)[0] ?? ""));
    setResolution(capabilityString(target, "default_resolution", videoResolutionOptions(target)[0] ?? ""));
    setSize(capabilityString(target, "default_size", sizeOptions(target)[0] ?? ""));
    setDuration(defaultDuration(target));
    setAudio(capabilityBoolean(target, "default_generate_audio"));
    setBooleanParameters(Object.fromEntries(
      booleanParameterKeys(target)
        .filter((key) => key !== "generate_audio")
        .map((key) => [key, capabilityBoolean(target, `default_${key}`)]),
    ));
    setEnumParameters(Object.fromEntries(
      parameterChoiceEntries(target).map(([key, choices]) => [
        key,
        capabilityString(target, `default_${key}`, choices[0] ?? ""),
      ]),
    ));
    setDeclared({});
    setCount(1);
    setMode("");
    touched.current = false;
  };

  //: 连进来的资产格引用的资产。生成时服务端按连线把它们当成 `@` 了一样挂上(提示词描述 + 参考图),
  //: 所以这里**摆出来**:连了一个人物进来却什么都看不到,就像连线没起作用。
  const linkedEntities = (upstreamEntities ?? []).flatMap((id) => mentionable.data?.find((one) => one.id === id) ?? []);

  //: 连进来却用不上的素材:就地说一句,不让那根线看起来像是起了作用(见 unusedUpstreamKinds)。
  const unused = unusedUpstreamKinds(current, activeMode?.roles, feed);

  //: 上面那一排:连进来的资产、挂上的参考素材(按模型声明出的槽)和连进来的文档。
  const upstreamChips =
    slots.length > 0 || upstreamDocuments?.length || linkedEntities.length || upstreamScene || unused.length ? (
      <>
        {unused.map(({ kind, elsewhere }) => (
          <span
            key={kind}
            role="status"
            data-upstream-unused={kind}
            className="inline-flex min-h-8 max-w-full items-center rounded-md bg-warning/10 px-2 py-1 text-ui-xs leading-snug text-warning"
          >
            {t(elsewhere ? UNUSED_UPSTREAM_COPY[kind].mode : UNUSED_UPSTREAM_COPY[kind].model)}
          </span>
        ))}
        {upstreamScene && (
          <SceneReferencePicker
            scene={referencedScene}
            uses={sceneUses}
            value={sceneReference}
            onChange={setSceneReference}
          />
        )}
        {mergedSlots ? (
          <>
            {mergedSlots.flatMap((slot) =>
              sources
                .filter((one) => one.role === slot.role)
                .map((one, index) => {
                  const kind = assetKindById.get(one.assetId);
                  return (
                    <SourceAssetSlotPreview
                      key={one.assetId}
                      assetId={one.assetId}
                      kind={kind === "image" || kind === "video" || kind === "audio" ? kind : roleAccepts(slot.role)}
                      label={slotLabel(t, slot, index)}
                      onRemove={() => setSources((all) => all.filter((x) => x.assetId !== one.assetId))}
                    />
                  );
                }),
            )}
            {mergedSlots.some(
              (slot) => sources.filter((one) => one.role === slot.role).length < slot.limit,
            ) && (
              // **一个**加号,不是三个。一份素材归哪个角色由它自己的类型唯一决定
              // (mergeableSourceSlots 保证了这一点),所以让用户先在三个长得一样、
              // 只靠 tooltip 区分的虚线框之间选,等于让他猜一件他不需要知道的事。
              // 份数上限按模型各不相同,所以「还能加几份」在这里现算,不写进文案。
              <Popover open={addOpen} onOpenChange={setAddOpen}>
                <SlotDrop onFiles={(files) => attachFiles(files, mergedSlots.map((slot) => slot.role))}>
                  <PopoverTrigger asChild>
                    <IconButton
                      unstyled
                      type="button"
                      label={t("boardAddSource")}
                      aria-haspopup="menu"
                      className="grid h-8 w-8 shrink-0 cursor-pointer place-items-center rounded-md border border-dashed border-border-strong text-muted-foreground transition-colors hover:border-primary hover:text-foreground"
                    >
                      <Plus size={13} />
                    </IconButton>
                  </PopoverTrigger>
                </SlotDrop>
                <MenuContent label={t("boardAddSource")} align="start">
                  <p className="m-0 px-2.5 pb-1.5 pt-1 text-ui-xs leading-[1.5] text-muted-foreground">
                    {t("boardAddSourceHint")}
                  </p>
                  {mergedSlots.map((slot) => {
                    const left = slot.limit - sources.filter((one) => one.role === slot.role).length;
                    return (
                      <MenuItem
                        key={slot.role}
                        label={roleLabel(t, slot.role)}
                        hint={left > 0 ? t("boardSourceRemaining").replace("{n}", String(left)) : t("boardSourceFull")}
                        disabled={left <= 0}
                        onClick={() => {
                          setAddOpen(false);
                          onPickAsset(roleAccepts(slot.role), (assetId) =>
                            setSources((all) => [...all, { role: slot.role, assetId }]),
                          );
                        }}
                      />
                    );
                  })}
                </MenuContent>
              </Popover>
            )}
          </>
        ) : (
          displaySlots.map((slot, index) => {
          // 首尾帧和参考素材**分属互斥的两组**(厂商硬约束,描述符里声明着)——
          // 组与组之间给一道竖线,否则一排虚线框读起来像五个平级的槽。
          const previous = displaySlots[index - 1]?.role;
          const groupChanged =
            previous !== undefined &&
            previous.endsWith("_frame") !== slot.role.endsWith("_frame");
          const mine = sources.filter((one) => one.role === slot.role);
          return (
            <React.Fragment key={slot.role}>
              {groupChanged && <span aria-hidden className="mx-1 h-5 w-px shrink-0 bg-border" />}
              {index > 0 && slot.role === "last_frame" && (
                // 首帧和尾帧之间那个交换 —— 摆反了是最常见的手误,而重挂两次很烦。
                <IconButton
                  unstyled
                  type="button"
                  label={t("boardSwapFrames")}
                  className="grid h-6 w-6 cursor-pointer place-items-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground"
                  onClick={() =>
                    setSources((current) =>
                      current.map((one) =>
                        one.role === "first_frame"
                          ? { ...one, role: "last_frame" }
                          : one.role === "last_frame"
                            ? { ...one, role: "first_frame" }
                            : one,
                      ),
                    )
                  }
                >
                  <ArrowLeftRight size={12} />
                </IconButton>
              )}
              {mine.map((one, index) => {
                const label = slotLabel(t, slot, index);
                // 素材库数据到了以后以真实类型为准；首屏尚未取回时按角色兜底。两条信息都来自
                // 同一份领域契约，旧表单里即使没存 kind 也不会退回“全部当图片”。
                const kind = assetKindById.get(one.assetId);
                const previewKind = kind === "image" || kind === "video" || kind === "audio"
                  ? kind
                  : roleAccepts(slot.role);
                return (
                  <SourceAssetSlotPreview
                    key={one.assetId}
                    assetId={one.assetId}
                    kind={previewKind}
                    label={label}
                    onRemove={() => setSources((all) => all.filter((x) => x.assetId !== one.assetId))}
                  />
                );
              })}
              {mine.length < slot.limit && (
                <SlotDrop onFiles={(files) => attachFiles(files, [slot.role])}>
                  <IconButton
                    unstyled
                    type="button"
                    label={slotLabel(t, slot, mine.length)}
                    onClick={() =>
                      onPickAsset(roleAccepts(slot.role), (assetId) =>
                        setSources((all) => [...all, { role: slot.role, assetId }]),
                      )
                    }
                    className="grid h-8 w-8 shrink-0 cursor-pointer place-items-center rounded-md border border-dashed border-border-strong text-muted-foreground transition-colors hover:border-primary hover:text-foreground"
                  >
                    <Plus size={13} />
                  </IconButton>
                </SlotDrop>
              )}
            </React.Fragment>
          );
          })
        )}
        {linkedEntities.map((entity) => (
          <Hint key={entity.id} label={t("boardLinkedEntityHint")}>
            <span
              data-linked-entity={entity.id}
              className="inline-flex h-8 max-w-[14rem] shrink-0 items-center gap-1.5 rounded-md bg-primary/10 pl-1 pr-2 text-ui-xs text-primary"
            >
              <EntityThumb entity={entity} className="h-6 w-6 rounded-sm" />
              <Truncate>{entityDisplayName(entity)}</Truncate>
            </span>
          </Hint>
        ))}
        {upstreamDocuments?.map((doc) => (
          <Hint key={doc.note_id} label={t("documentOpen")}>
            <a
              href={noteHref(doc.note_id)}
              className="min-w-0 max-w-full rounded-md bg-primary/10 px-2 py-1 text-ui-xs text-primary"
            >
              <Truncate>{t("boardKindDocument")} · {doc.title || t("documentUntitled")} · v{doc.revision}</Truncate>
            </a>
          </Hint>
        ))}
        <AssetUploadStatus upload={upload} className="basis-full" />
      </>
    ) : null;

  return (
    <BoardComposerShell
      nodeId={item.id}
      name="generate"
      width="lg"
      upstream={upstreamChips}
      onPaste={pasteIntoSlots}
      bar={
        options.length === 0 ? (
          // 没有可用模型时说清楚 —— 给一个点了没反应的按钮比什么都不给更糟。
          <span className="px-1 text-ui-2xs text-muted-foreground">{t("boardNoGenerationModel")}</span>
        ) : (
          <>
            {/* 生图不知道怎么写:挑一个模板接在提示词后面(和 AI 工作台同一份,components/app/PromptTemplates)。 */}
            {item.kind === "image" && (
              <PromptTemplateButton
                onPick={(template) => {
                  //: 接成新的一段,**不重建文档**:重建的话提示词里 `@` 过的素材会被抹成纯文字、引用丢掉。
                  const base = promptDocument ?? textDocument(prompt);
                  const blocks = (base.content ?? []).filter((block) => (block.content ?? []).length > 0);
                  setPrompt(withTemplate(prompt, template));
                  setPromptDocument({ ...base, content: [...blocks, { type: "paragraph", content: [{ type: "text", text: template }] }] });
                }}
              />
            )}
            {/* 上限而不是 flex-1:模型名短的时候这一格就该短。名字长了在上限处截断,
                而不是把「参数」推到行尾 —— 它和模型是一组,该挨着。 */}
            <Pick
              className="max-w-[min(15rem,45%)]"
              icon={<Sparkles size={12} className="shrink-0 text-muted-foreground" />}
              value={modelValue}
              placeholder={t("genPickModel")}
              onChange={pickModel}
              options={options.map((one) => {
                //: 两层名字(ADR 0045):主名是这一项自己的(表单标题 / 工作流名),副名说来自哪张工作流、哪台服务器;
                //: 同一张工作流的表单入口挂在完整工作流下面。按主名、工作流名、文件名、连接名都搜得到。
                const names = generationOptionNames(one, formed, t);
                return {
                  value: `${one.provider_profile_id}:${one.model}`,
                  label: names.primary,
                  description: names.secondary,
                  keywords: generationOptionKeywords(one),
                  indent: one.group?.entry === "form",
                };
              })}
            />
            {/* **分开两种零。**「这个模型确实没有可调参数」就不摆按钮;「我们不认识这个模型」
                (手填的别名、经另一条中转配的同一个模型)要说出来 —— 静默地什么都不显示,
                用户会以为这个模型就是没参数。显隐和弹层内容共用 settingBlocks。 */}
            {settingBlocks.length === 0 && current?.capabilities_known === false && (
              <Truncate className="px-1 text-ui-2xs text-muted-foreground">
                {t("boardGenerationUnknownParams")}
              </Truncate>
            )}
          </>
        )
      }
      settings={
        options.length > 0 && settingBlocks.length > 0
          ? {
              content: (
                <>
                  {/* 生成方式排第一格:它决定上面那排槽位是首尾帧还是参考,后面几项都在它之下。 */}
                {modes.length > 0 && (
                  <Pick
                    label={t("boardGenerationMode")}
                    value={activeMode?.key ?? ""}
                    onChange={(next) => {
                      touched.current = true;
                      setMode(next);
                    }}
                    options={modes.map((one) => ({ value: one.key, label: t(modeLabel(one.roles)) }))}
                  />
                )}
                {supportsParameter(current, "aspect_ratio") && (
                  <Pick
                    label={t("wfGenAspectRatio")}
                    value={ratio}
                    onChange={setRatio}
                    options={aspectRatioOptions(current).map((one) => ({ value: one, label: one }))}
                    allowFreeValue
                    placeholder={t("genValueUnknownPlaceholder")}
                  />
                )}
                {supportsParameter(current, "resolution") && (
                  <Pick
                    label={t("wfGenResolution")}
                    value={resolution}
                    onChange={(next) => {
                      setResolution(next);
                      const nextDurations = durationChoices(current, next);
                      if (nextDurations.length > 0 && !nextDurations.includes(duration)) setDuration(nextDurations[0]);
                    }}
                    options={videoResolutionOptions(current).map((one) => ({ value: one, label: one }))}
                    allowFreeValue
                    placeholder={t("genValueUnknownPlaceholder")}
                  />
                )}
                {supportsParameter(current, "size") && (customSize ? (
                  /* 推荐的几档、手填的也收(ComfyUI 的工作流):下拉里多一个输入框 */
                  <ParameterRow label={t("wfGenSize")}>
                    <CustomSizePicker
                      value={size}
                      onChange={setSize}
                      options={sizeOptions(current)}
                      minimum={customSize.minimum}
                      ariaLabel={t("wfGenSize")}
                      size="sm"
                      className="w-full min-w-0 text-ui-xs"
                    />
                  </ParameterRow>
                ) : (
                  <Pick
                    label={t("wfGenSize")}
                    value={size}
                    onChange={setSize}
                    options={sizeOptions(current).map((one) => ({ value: one, label: one }))}
                    allowFreeValue
                    placeholder={t("genValueUnknownPlaceholder")}
                  />
                ))}
                {supportsParameter(current, "duration_seconds") && durations.length === 0 && (
                  /* 声明了时长、却没有可选值也没有区间 —— 摆一个自由输入,而不是消失。
                     值仍然是 0(未设置),用户不填就不提交。 */
                  <Pick
                    label={t("wfGenDuration")}
                    value={duration > 0 ? String(duration) : ""}
                    onChange={(next) => setDuration(Number(next) || DURATION_UNSET)}
                    options={[]}
                    allowFreeValue
                    placeholder={t("genValueUnknownPlaceholder")}
                  />
                )}
                {supportsParameter(current, "duration_seconds") && durations.length > 0 && (
                  <Pick
                    label={t("wfGenDuration")}
                    value={String(duration)}
                    onChange={(next) => setDuration(Number(next))}
                    options={durations.map((one) => ({
                      value: String(one),
                      label: one === -1 ? t("genDurationAuto") : `${one}s`,
                    }))}
                  />
                )}
                {booleanKeys.map((key) => {
                  const labelKey = GENERATION_BOOLEAN_LABELS[key];
                  return (
                    <Pick
                      key={key}
                      label={labelKey ? t(labelKey) : key}
                      value={booleanParameters[key] ? "on" : "off"}
                      onChange={(next) => setBooleanParameters((values) => ({ ...values, [key]: next === "on" }))}
                      options={[
                        { value: "on", label: t("wfGenToggleOn") },
                        { value: "off", label: t("wfGenToggleOff") },
                      ]}
                    />
                  );
                })}
                {enumEntries.map(([key, choices]) => {
                  const labelKey = GENERATION_PARAMETER_LABELS[key];
                  const hintKey = GENERATION_PARAMETER_HINTS[key];
                  return (
                    <Pick
                      key={key}
                      label={labelKey ? t(labelKey) : key}
                      hint={hintKey ? t(hintKey) : undefined}
                      value={enumParameters[key] ?? capabilityString(current, `default_${key}`, choices[0] ?? "")}
                      onChange={(next) => setEnumParameters((values) => ({ ...values, [key]: next }))}
                      options={choices.map((choice) => ({
                        value: choice,
                        label: choice,
                      }))}
                    />
                  );
                })}
                {declaredParameters(current).map((parameter) => {
                  const fallback = parameter.defaultValue === undefined ? "" : String(parameter.defaultValue);
                  const listed = parameter.type === "boolean" || parameter.options.length > 0;
                  const choices = declaredChoices(parameter, t);
                  if (parameter.modelFolder && current?.plugin_instance_id && parameter.options.length > 0) {
                    /* 选模型文件的那一格:缩略图、底模、触发词来自这个连接的模型库;选中 LoRA 能把触发词接进提示词 */
                    return (
                      <ParameterRow
                        key={parameter.key}
                        label={parameter.label}
                        title={parameter.description ? `${parameter.label} — ${toPlainText(parameter.description)}` : parameter.label}
                      >
                        <ModelFilePicker
                          parameter={parameter}
                          instanceId={current.plugin_instance_id}
                          size="sm"
                          ariaLabel={parameter.label}
                          className="w-full min-w-0 gap-1 text-ui-xs"
                          value={declared[parameter.key] ?? ""}
                          onChange={(next) => setDeclared((values) => ({ ...values, [parameter.key]: next }))}
                          onUseTriggers={appendTriggers}
                        />
                      </ParameterRow>
                    );
                  }
                  return (
                    <Pick
                      key={parameter.key}
                      label={parameter.label}
                      hint={parameter.description ? `${parameter.label} — ${toPlainText(parameter.description)}` : parameter.label}
                      value={listed ? choices.shown(declared[parameter.key] ?? "") : (declared[parameter.key] ?? "")}
                      onChange={(next) =>
                        setDeclared((values) => ({ ...values, [parameter.key]: listed ? choices.stored(next) : next }))
                      }
                      options={listed ? choices.options : []}
                      allowFreeValue
                      placeholder={fallback || t("genDeclaredDefaultNone")}
                    />
                  );
                })}
              {supportsParameter(current, "generate_audio") && (
                    <Pick
                      label={t("boardGenerationSound")}
                      value={audio ? "on" : "off"}
                      onChange={(next) => setAudio(next === "on")}
                      options={[
                        { value: "on", label: t("boardWithSound") },
                        { value: "off", label: t("boardMuted") },
                      ]}
                    />
              )}
                </>
              ),
            }
          : null
      }
      trailing={
        options.length > 0 && batches ? (
          // ComfyUI 的工作流「张数」是跑几遍(countsRuns):悬停说清一遍出几张、这次一共几张,每一档的副标题写跑几遍。
          <Hint label={runs ? generationParameterLabel("num_images", current, t) : undefined} hint={runs ? runsHint(t, current, formParameters, count) : undefined}>
          <span className="flex w-14 items-center rounded-md transition-colors hover:bg-secondary">
            {/* 数是**这一次会落出几格**(跑一遍交回几份 × 张数),不是发出去的张数:一张工作流两个结果节点时选「4×」
                是跑 2 遍、一共 4 格 —— 和其他模型上「N×」的意思一样(落出 N 格),副标题说清跑几遍 / 每个节点几张。 */}
            <Pick
              ariaLabel={t("boardOutputCount")}
              value={String(count)}
              onChange={(next) => setCount(Number(next))}
              options={Array.from({ length: maxImages(current) }, (_, index) => ({
                value: String(index + 1),
                label: `${(index + 1) * perRun}×`,
                ...(runs
                  ? { description: t("boardOutputsRuns").replace("{count}", String(index + 1)) }
                  : perRun > 1 ? { description: t("boardOutputsPerNode").replace("{count}", String(index + 1)) } : {}),
              }))}
            />
          </span>
          </Hint>
        ) : null
      }
      send={
        options.length > 0
          ? { label: t("boardGenerate"), onSend: send, disabled: !canSend || busy, working, shortcut: true }
          : null
      }
    >
      {currentPromptMode === "none" ? (
        // 这个模型不收提示词(放大、抠图这类按素材出结果的工作流):不摆一个写了也不生效的编辑器。
        <p className="m-0 px-1 py-2 text-ui-sm text-muted-foreground">{t("genPromptNotUsed")}</p>
      ) : (
        <PromptEditor
          value={prompt}
          document={promptDocument}
          onChange={(next, assets, document, entityIds) => {
            setPrompt(next);
            setMentioned(assets);
            setPromptDocument(document);
            setMentionedEntities(entityIds);
          }}
          placeholder={t(
            currentPromptMode === "optional"
              ? "boardPromptPlaceholderOptional"
              : slots.length > 0
                ? "boardPromptPlaceholderMention"
                : "boardPromptPlaceholder",
          )}
          candidates={candidates}
          //: 连进这个节点的那几份排最前,并单独给一个「已连接」筛选钮 —— 刚接进来的那张,
          //: 正是这句话十有八九要指的东西。
          linked={feed.map((one) => one.assetId)}
          //: 资产库里的人物 / 场景 / 道具也在同一个 `@` 菜单里;连进来的资产格排在最前。
          entities={entityCandidates}
          linkedEntities={upstreamEntities}
          onSubmit={send}
          emptyHint={() => (slots.length === 0 ? t("boardNoSourceSlots") : "")}
        />
      )}
      {needsDigitalHumanConsent && (
        <DigitalHumanConsent checked={digitalHumanConsent} onChange={setDigitalHumanConsent} />
      )}
    </BoardComposerShell>
  );
}
