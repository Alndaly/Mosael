import React from "react";
import { NodeToolbar, Position } from "@xyflow/react";
import { ArrowLeftRight, ArrowUp, Loader2, Plus, Sparkles, Volume2, VolumeX, X } from "lucide-react";

import { useQuery } from "@tanstack/react-query";

import { assetFileUrl, assetThumbnailUrl, listAssets, type Asset, type BoardItem, type GenerationModel } from "@/api/client";
import { useImagePreview } from "@/components/app/image-preview";
import { PromptEditor } from "@/features/boards/PromptEditor";
import { useSubmitting } from "@/features/boards/useSubmitting";
import { useI18n } from "@/app/preferences";
import type { MessageKey } from "@/app/messages";
import { ROLE_COPY, type SourceRole } from "@/features/ai-studio/sourceFrames";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  aspectRatioOptions,
  capabilityNumber,
  exclusiveSourceGroups,
  capabilityString,
  durationOptions,
  maxImages,
  sizeOptions,
  sourceLimit,
  supportsParameter,
  videoResolutionOptions,
} from "@/lib/generationCapabilities";
import { cn } from "@/lib/utils";

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
 * ## 位置
 *
 * 用 NodeToolbar 挂在节点下方 —— 它渲染在 React Flow 的视口层里,平移缩放时自己跟着节点走。
 * 自己算坐标的话,画布一动它就飘(这个仓库在 @ 引用菜单上踩过一次)。
 */
/** 参数行里的一格。样子统一:没有边框、只有文字,点开才是下拉 —— 一行摆五六个带框的
 *  控件会把面板撑成一张表单,而这里要的是一句话:「首尾帧 · 16:9 · 480p · 5s」。 */
function Pick({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (next: string) => void;
  options: { value: string; label: string }[];
}) {
  if (options.length === 0) return null;
  return (
    <Select value={value} onValueChange={onChange}>
      {/* 不出下拉箭头:一行里五六个箭头是纯噪音,而这一行读起来该像「16:9 · 480p · 5s」。
          点开仍然是完整的下拉。 */}
      <SelectTrigger className="h-6 w-auto gap-0 border-0 bg-transparent px-1 text-ui-2xs text-muted-foreground shadow-none focus:ring-0 data-[state=open]:text-foreground [&>svg]:hidden">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((one) => (
          <SelectItem key={one.value} value={one.value}>
            {one.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** 角色的中文名 —— 和 AI 工作台共用那一份(features/ai-studio/sourceFrames.ROLE_COPY),
 *  不在这里再抄一张表。 */
/** ROLE_COPY 里存的是 i18n 的 key,**不是**给人看的字 —— 不过一遍 t() 就会把
 *  「genFirstFrame」原样挂到提示上。 */
/** 一个角色收哪一类素材。**只此一处** —— 选择器开哪一类、上游哪种产出能自动挂进来,
 *  都问它;分散写两遍的话,加一个角色就会有一边忘记改。 */
export function roleAccepts(role: string): "image" | "video" | "audio" {
  if (role === "reference_video") return "video";
  if (role === "reference_audio") return "audio";
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
export function sourceModes(model: GenerationModel | null): { key: string; roles: string[] }[] {
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
/**
 * 提示词末尾那段「谁是第几张」。
 *
 * **模型收到的是一串没有名字的图。** 用户在正文里写「把 创作者.png 里的人放到 街景.jpg」——
 * 那两个名字对他有意义,对模型只是两个词:它拿到的是 `image: [url, url]`,一个文件名都没有。
 * 一两张时还能靠顺序猜,而这个界面本来就是让人 @ 很多张的。
 *
 * 所以把对应关系明写出来。三个判断:
 *
 * 1. **附在末尾,不改用户写的字。** 在正文里把名字替换成「图1」会动他的句子,而且他再打开
 *    这一格时看到的就不是自己写的东西了;后端存的节点文字是 `prompt[:120]`,附在末尾也就
 *    不会挤掉那一截。
 * 2. **按角色分组编号。** 适配器是按角色过滤成一串的(比如 seedream 的
 *    `payload["image"] = 参考图那几个`),所以「第几张」只在同一个角色里才有意义 ——
 *    跨角色连着数会把首帧算成参考图的第一张。
 * 3. **重名要能分开。** 同名的两份素材在这段说明里也是两个词,不编号的话它等于没说。
 */
export function referenceLegend(
  sources: { asset_id: string; role: string }[],
  library: { id: string; name?: string | null; original_filename?: string | null }[],
  label: (role: string) => string,
): string {
  const byRole = new Map<string, string[]>();
  for (const one of sources) {
    const asset = library.find((item) => item.id === one.asset_id);
    const name = String(asset?.name || asset?.original_filename || "").trim();
    //: 认不出名字的不写进来 —— 「参考图 2 = 」比不写更糟。
    if (!name) continue;
    byRole.set(one.role, [...(byRole.get(one.role) ?? []), name]);
  }
  const lines: string[] = [];
  for (const [role, names] of byRole) {
    lines.push(names.map((name, at) => `${label(role)} ${at + 1} = ${name}`).join("; "));
  }
  return lines.join("\n");
}

export function mergeSourceAssets(
  attached: { role: string; assetId: string }[],
  mentioned: string[],
  library: { id: string; kind: string }[],
  slots: { role: string; limit: number }[],
): { asset_id: string; role: string }[] {
  const out = attached.map((one) => ({ asset_id: one.assetId, role: one.role }));
  const seen = new Set(out.map((one) => one.asset_id));
  for (const assetId of mentioned) {
    if (seen.has(assetId)) continue;
    const kind = library.find((asset) => asset.id === assetId)?.kind;
    const slot = slots.find((one) => roleAccepts(one.role) === kind);
    if (!slot) continue;
    seen.add(assetId);
    out.push({ asset_id: assetId, role: slot.role });
  }
  return out;
}

/** 这个模型认哪几种输入素材、各能挂几份。
 *
 * **认不认看 supportsParameter(描述符的 parameter_keys),能挂几份才看 sourceLimit。**
 * sourceLimit 对没声明的角色兜底返回 1,拿它当支持判定用的话,图片模型也会长出首尾帧槽。
 */
export function sourceSlots(
  model: GenerationModel | null,
  /** 当前生成方式的角色。给了就只出这一组 —— 互斥的另一组同时摆出来,挂满了才在提交时被拒。 */
  activeRoles?: string[],
): { role: string; limit: number }[] {
  if (!model) return [];
  return (["first_frame", "last_frame", "reference_image", "reference_video", "reference_audio"] as const)
    .filter((role) => supportsParameter(model, role))
    .filter((role) => !activeRoles || activeRoles.includes(role))
    .map((role) => ({ role, limit: sourceLimit(model, role) }));
}

/**
 * 把上游节点的产出自动挂到槽位上,按槽位顺序、各自的份数上限来。
 *
 * 连了线却还要再挂一遍素材,那条线就只是根装饰。类别对不上的跳过(视频挂不进首帧),
 * 装不下的也跳过 —— 宁可少挂一张,也不要把用户没连的东西塞进去。
 */
export function autoAssign(
  slots: { role: string; limit: number }[],
  upstream: { assetId: string; kind: string }[],
): { role: string; assetId: string }[] {
  const taken = new Set<string>();
  const out: { role: string; assetId: string }[] = [];
  for (const slot of slots) {
    for (const one of upstream) {
      if (out.filter((x) => x.role === slot.role).length >= slot.limit) break;
      if (taken.has(one.assetId) || one.kind !== roleAccepts(slot.role)) continue;
      taken.add(one.assetId);
      out.push({ role: slot.role, assetId: one.assetId });
    }
  }
  return out;
}

/**
 * 上游连了这些东西时,默认该用哪种生成方式。
 *
 * 照 TapNow 的直觉:**连一张图 = 拿它当首帧**(最常见的图生视频),连两张以上就说明用户
 * 想要的是「像这些」而不是「从这张开始」,于是切到参考。装不下的组不选。
 */
export function defaultMode(
  modes: { key: string; roles: string[] }[],
  model: GenerationModel | null,
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

function roleLabel(t: ReturnType<typeof useI18n>, role: string): string {
  const key = ROLE_COPY[role as SourceRole]?.label;
  return key ? t(key as Parameters<typeof t>[0]) : role;
}

export function NodeComposer({
  item,
  models,
  busy,
  onSubmit,
  onPickAsset,
  upstream,
  upstreamTexts,
  workspaceId,
}: {
  item: BoardItem;
  /** 这种能力下可选的模型。空数组 = 还没配 —— 那时该说清楚,而不是给一个点了没反应的按钮。 */
  models: GenerationModel[];
  busy: boolean;
  onSubmit: (input: {
    prompt: string;
    provider: string;
    model: string;
    parameters: Record<string, unknown>;
    sourceAssets: { asset_id: string; role: string }[];
  }) => void;
  /** 挂输入素材时开选择器 —— 和画布上「换一份」用的是同一个。 */
  onPickAsset: (kind: "image" | "video", place: (assetId: string) => void) => void;
  /** **连到这个节点上的上游产出**,按连线顺序。它们会自动挂进当前生成方式的槽位 ——
   *  连了线还要再挂一遍素材的话,那条线就只是根装饰。 */
  upstream?: { assetId: string; kind: string }[];
  /** 上游**便签**给的文字。一张写着描述的便签连过来,意思是「照这段话画」—— 它不是参考图
   *  (便签根本没有图),而是提示词本身。 */
  upstreamTexts?: { itemId: string; text: string }[];
  /** `@` 引用素材时去哪个工作区找。 */
  workspaceId: string;
}) {
  const t = useI18n();
  const { openImagePreview } = useImagePreview();
  const [prompt, setPrompt] = React.useState(item.text ?? "");
  const [picked, setPicked] = React.useState("");

  const options = React.useMemo(
    () => models.filter((model) => model.kind === item.kind),
    [models, item.kind],
  );
  const current = options.find((model) => `${model.provider}/${model.model}` === picked) ?? options[0] ?? null;
  const modelValue = picked || (current ? `${current.provider}/${current.model}` : "");

  //: 每一项的默认值都**从描述符取**(default_* 那几条),而不是前端挑一个 —— 后端那份才是
  //: 对着真机核过的。换模型时跟着换,所以用 key 重挂而不是 useState 记着上一个模型的值。
  const durations = durationOptions(current);
  const [ratio, setRatio] = React.useState(() => capabilityString(current, "default_aspect_ratio", aspectRatioOptions(current)[0] ?? ""));
  const [resolution, setResolution] = React.useState(() => capabilityString(current, "default_resolution", videoResolutionOptions(current)[0] ?? ""));
  const [size, setSize] = React.useState(() => capabilityString(current, "default_size", sizeOptions(current)[0] ?? ""));
  const [duration, setDuration] = React.useState(() => capabilityNumber(current, "default_duration_seconds", durations[0] ?? 5));
  const [audio, setAudio] = React.useState(false);
  const [count, setCount] = React.useState(1);
  //: 挂上去的输入素材,按角色分。**角色和上限都由描述符说了算** —— 参考图九张还是三张、
  //: 认不认尾帧,每个模型不一样;写死一套的话换个模型就要么少给要么超限。
  const [sources, setSources] = React.useState<{ role: string; assetId: string }[]>([]);

  //: 「生成方式」= 描述符里那几个互斥分组。摆出来的槽只属于当前这一组 —— 两组同时摆着,
  //: 用户挂满了才会在提交时被拒。
  const feed = React.useMemo(() => upstream ?? [], [upstream]);
  const texts = React.useMemo(() => upstreamTexts ?? [], [upstreamTexts]);
  const modes = React.useMemo(() => sourceModes(current), [current]);
  const [mode, setMode] = React.useState("");
  const activeMode = modes.find((one) => one.key === mode) ?? modes[0] ?? null;

  //: 这个模型认哪几种输入素材,各能挂几份。首尾帧和参考图**分属互斥的两组**(厂商硬约束),
  //: 描述符里已经声明过 —— 这里只按它出格子,不自己判。
  const slots = React.useMemo(
    () => sourceSlots(current, activeMode?.roles),
    [current, activeMode],
  );

  //: 换模型、换方式、或者上游连线变了 —— 都重新照上游挂一遍。
  //:
  //: 这三件事任一变化,原来挂着的东西就可能已经不属于现在这组槽位了(尾帧换到参考组里
  //: 没有对应的槽),留着它只会在提交时被后端拒。手动增删在下一次变化前一直有效。
  const feedKey = `${modelValue}|${activeMode?.key ?? ""}|${feed.map((one) => one.assetId).join(",")}`;
  const lastFeed = React.useRef("");
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
  const textKey = texts.map((one) => `${one.itemId}:${one.text}`).join("|");
  const filled = React.useRef("");
  React.useEffect(() => {
    const joined = texts.map((one) => one.text).join("\n\n");
    if (!joined || joined === filled.current) return;
    setPrompt((current) => (current.trim() === "" || current === filled.current ? joined : current));
    filled.current = joined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [textKey]);

  /**
   * `@` 引用素材的候选。**挑中的挂到槽位上,不写进提示词** —— 正文里留着「@猫.png」的话,
   * 模型会把这几个字当成描述念出来。
   *
   * 只列这个模型**收得下**的类别:它一个视频槽都没有的时候,把视频列出来等于让用户选一个
   * 挂不上去的东西。
   */
  //: **面板一开就预取**,不等到敲下 @ 才拉。插件是在每次按键时问一次候选的:等到那一刻
  //: 才发请求的话,第一次敲 @ 手上是空的 —— 菜单不出,用户得再多敲一个字它才冒出来。
  const library = useQuery({
    queryKey: ["assets", workspaceId],
    queryFn: () => listAssets(workspaceId),
    enabled: slots.length > 0,
  });
  const accepted = React.useMemo(() => new Set(slots.map((slot) => roleAccepts(slot.role))), [slots]);
  const candidates = React.useCallback(
    (query: string) => {
      const needle = query.trim().toLowerCase();
      return (library.data ?? [])
        .filter((asset: Asset) => accepted.has(asset.kind as "image" | "video" | "audio"))
        .filter(
          (asset: Asset) =>
            !needle || `${asset.name ?? ""} ${asset.original_filename ?? ""}`.toLowerCase().includes(needle),
        )
        .slice(0, 8);
    },
    [library.data, accepted],
  );

  //: 正文里 chip 引用到的素材。它们和上面那排槽位是**两件事**:槽位挂的是首帧/参考这种
  //: 有角色的位置,而 chip 是「我在这句话里指的是这张图」。提交时两边都进 source_assets。
  const [mentioned, setMentioned] = React.useState<string[]>([]);

  //: 上游变了就重挑一次默认方式:一张图 = 首帧,多张 = 参考(TapNow 的那套直觉)。
  //: 用户自己点过之后,这条不再插手 —— touched 记着这件事。
  const touched = React.useRef(false);
  const feedIds = feed.map((one) => one.assetId).join(",");
  React.useEffect(() => {
    if (touched.current || modes.length === 0) return;
    setMode(defaultMode(modes, current, feed));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [feedIds, modes.length]);

  //: 点下去立刻转、落地就停(**失败也要停** —— 否则那个圈会一直转下去)。见 useSubmitting。
  const { submitting, run } = useSubmitting();
  const working = submitting || busy;

  const send = () => {
    const text = prompt.trim();
    if (!text || !current || working) return;
    //: 只发这个模型**认的**那几项 —— 多发一项会被校验器当场拦下(它照描述符判)。
    const parameters: Record<string, unknown> = {};
    if (supportsParameter(current, "aspect_ratio") && ratio) parameters.aspect_ratio = ratio;
    if (supportsParameter(current, "resolution") && resolution) parameters.resolution = resolution;
    if (supportsParameter(current, "size") && size) parameters.size = size;
    if (supportsParameter(current, "duration_seconds")) parameters.duration_seconds = duration;
    if (current.capabilities?.supports_audio && audio) parameters.generate_audio = true;
    if (maxImages(current) > 1 && count > 1) parameters.num_images = count;
    //: 槽位挂的 + 正文里 @ 到的,都要发出去。**同一份素材不发两遍** —— 有些厂商会把
    //: 重复的那一份也算进参考图的份数,挂到上限就直接拒了。正文里的 @ 没有角色,
    //: 落到第一个收得下它的槽上(通常就是参考图)。
    const sourceAssets = mergeSourceAssets(sources, mentioned, library.data ?? [], slots);
    //: 正文里写的是名字,而模型收到的是一串没有名字的图 —— 末尾补一段对应关系(见 referenceLegend)。
    //: 角色名走 ROLE_COPY —— 和 AI 工作台、工作流面板同一份,不在这儿再抄一张表。
    const legend = referenceLegend(sourceAssets, library.data ?? [], (role) =>
      t(ROLE_COPY[role as SourceRole]?.label ?? "genReferenceImage"),
    );
    run(() =>
      onSubmit({
        prompt: legend ? `${text}\n\n${t("boardPromptLegend")}${legend}` : text,
        provider: current.provider,
        model: current.model,
        parameters,
        sourceAssets,
      }),
    );
  };

  return (
    <NodeToolbar nodeId={item.id} isVisible position={Position.Bottom} offset={12}>
      <div className="nodrag nopan nowheel relative w-[420px] rounded-xl border border-border-strong bg-panel p-2 shadow-[var(--shadow-panel)]">
        {/* 输入素材:图片是一排参考图(可多张),视频是首帧 ⇄ 尾帧。**格子按模型声明出** ——
            见 slots 那段。挂满上限就不再给 + ,免得点了才被校验器拦下。 */}
        {slots.length > 0 && (
          // 槽位行和提示词之间给一道界:上面挂的是**素材**,下面写的是**话**,两件事。
          <div className="mb-1.5 flex flex-wrap items-center gap-1 border-b border-border px-1 pb-1.5">
            {slots.map((slot, index) => {
              // 首尾帧和参考素材**分属互斥的两组**(厂商硬约束,描述符里声明着)——
              // 组与组之间给一道竖线,否则一排虚线框读起来像五个平级的槽。
              const previous = slots[index - 1]?.role;
              const groupChanged =
                previous !== undefined &&
                previous.endsWith("_frame") !== slot.role.endsWith("_frame");
              const mine = sources.filter((one) => one.role === slot.role);
              return (
                <React.Fragment key={slot.role}>
                  {groupChanged && <span aria-hidden className="mx-1 h-5 w-px shrink-0 bg-border" />}
                  {index > 0 && slot.role === "last_frame" && (
                    // 首帧和尾帧之间那个交换 —— 摆反了是最常见的手误,而重挂两次很烦。
                    <button
                      type="button"
                      aria-label={t("boardSwapFrames")}
                      title={t("boardSwapFrames")}
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
                    </button>
                  )}
                  {mine.map((one) => (
                    // 点图看大图,叉叉才是移除。**两件事分开** —— 挂上去之后最想做的是
                    // 「确认一下挂对了没有」,而此前点一下就把它摘掉了:想看清楚,反而弄丢了。
                    <span key={one.assetId} className="group/thumb relative shrink-0">
                      <button
                        type="button"
                        title={`${roleLabel(t, slot.role)} —— ${t("boardOpenLarge")}`}
                        onClick={() =>
                          openImagePreview({ src: assetFileUrl(one.assetId), title: roleLabel(t, slot.role) })
                        }
                        className="block h-8 w-8 cursor-zoom-in overflow-hidden rounded-md border border-border transition-colors hover:border-border-strong"
                      >
                        <img src={assetThumbnailUrl(one.assetId)} alt="" className="h-full w-full object-cover" />
                      </button>
                      <button
                        type="button"
                        aria-label={`${t("boardRemove")}${roleLabel(t, slot.role)}`}
                        title={t("boardRemove")}
                        onClick={() => setSources((all) => all.filter((x) => x.assetId !== one.assetId))}
                        //: 悬浮才出。常驻的话,这一排小图上会挂满一圈叉,比图本身还显眼。
                        className="absolute -right-1 -top-1 grid h-4 w-4 cursor-pointer place-items-center rounded-full border border-border bg-panel text-muted-foreground opacity-0 shadow-sm transition-opacity hover:border-destructive hover:text-destructive group-hover/thumb:opacity-100"
                      >
                        <X size={9} />
                      </button>
                    </span>
                  ))}
                  {mine.length < slot.limit && (
                    <button
                      type="button"
                      title={roleLabel(t, slot.role)}
                      onClick={() =>
                        onPickAsset(roleAccepts(slot.role) === "video" ? "video" : "image", (assetId) =>
                          setSources((all) => [...all, { role: slot.role, assetId }]),
                        )
                      }
                      className="grid h-8 w-8 shrink-0 cursor-pointer place-items-center rounded-md border border-dashed border-border-strong text-muted-foreground transition-colors hover:border-primary hover:text-foreground"
                    >
                      <Plus size={13} />
                    </button>
                  )}
                </React.Fragment>
              );
            })}
          </div>
        )}

        {/* 提示词。`@` 在**表单内部**引用素材,菜单跟着光标走 —— 和工作流的上游引用同一套
            机件(TipTap + 共用的 useSuggestionMenu)。自己判 @ 的那一版栽在输入法上:
            中文选词时按回车会被菜单当成「选中候选」吃掉,候选词上不了屏。 */}
        <PromptEditor
          value={prompt}
          onChange={(next, assets) => {
            setPrompt(next);
            setMentioned(assets);
          }}
          placeholder={t(slots.length > 0 ? "boardPromptPlaceholderMention" : "boardPromptPlaceholder")}
          candidates={candidates}
          onSubmit={send}
          emptyHint={() => (slots.length === 0 ? t("boardNoSourceSlots") : "")}
        />
        {/* 参数行:**按这个模型声明的来**,不写死。
            后端描述符已经说清楚了每个模型认哪几项(aspect_ratio / resolution /
            duration_seconds / size / num_images / generate_audio),这里照着出控件 ——
            换一个模型,这一行自己就变了。写死的话每接一个新模型都要回来改一次,
            而漏改不会报错,只会让那一项永远调不了。 */}
        {/* 底部一行分三段:**它是谁**(模型)、**怎么生成**(参数)、**发出去**(次数 + 提交)。
            参数收进**一个胶囊**里而不是并排六个下拉 —— 它们是同一个决定的几个侧面
            (「首尾帧 · 16:9 · 480p · 5s」读起来是一句话),各自带框会让这一行像一张表单。
            胶囊整体有 hover 态,里面每一格点开才是下拉。 */}
        <div className="flex items-center gap-1 border-t border-border pt-1.5">
          {options.length === 0 ? (
            // 没有可用模型时说清楚 —— 给一个点了没反应的按钮比什么都不给更糟。
            <span className="px-1 text-ui-2xs text-muted-foreground">{t("boardNoGenerationModel")}</span>
          ) : (
            <>
              <span className="flex min-w-0 shrink items-center gap-0.5 rounded-full px-1 transition-colors hover:bg-secondary">
                <Sparkles size={12} className="shrink-0 text-muted-foreground" />
                <Pick value={modelValue} onChange={setPicked} options={options.map((one) => ({ value: `${one.provider}/${one.model}`, label: one.model }))} />
              </span>

              <span aria-hidden className="h-3.5 w-px shrink-0 bg-border" />

              <span className="flex min-w-0 shrink items-center gap-0 rounded-full px-1 transition-colors hover:bg-secondary">
                {/* 生成方式排第一格:它决定上面那排槽位是首尾帧还是参考,后面几项都在它之下。 */}
                {modes.length > 0 && (
                  <Pick
                    value={activeMode?.key ?? ""}
                    onChange={(next) => {
                      touched.current = true;
                      setMode(next);
                    }}
                    options={modes.map((one) => ({ value: one.key, label: t(modeLabel(one.roles)) }))}
                  />
                )}
                {supportsParameter(current, "aspect_ratio") && (
                  <Pick value={ratio} onChange={setRatio} options={aspectRatioOptions(current).map((one) => ({ value: one, label: one }))} />
                )}
                {supportsParameter(current, "resolution") && (
                  <Pick value={resolution} onChange={setResolution} options={videoResolutionOptions(current).map((one) => ({ value: one, label: one }))} />
                )}
                {supportsParameter(current, "size") && (
                  <Pick value={size} onChange={setSize} options={sizeOptions(current).map((one) => ({ value: one, label: one }))} />
                )}
                {supportsParameter(current, "duration_seconds") && durations.length > 0 && (
                  <Pick value={String(duration)} onChange={(next) => setDuration(Number(next))} options={durations.map((one) => ({ value: String(one), label: `${one}s` }))} />
                )}
              </span>

              {/* **出声与否是一项独立的配置**,不是那串参数里的一格 —— 它决定成片有没有
                  声音,和「多大、多长」不是一类事。所以拆出来自成一段,并且写成 有声/静音
                  两个字:一个喇叭图标读起来像预览的静音键,而它其实是在配置**要不要生成**。 */}
              {Boolean(current?.capabilities?.supports_audio) && (
                <>
                  <span aria-hidden className="h-3.5 w-px shrink-0 bg-border" />
                  <span className="flex shrink-0 items-center gap-0.5 rounded-full px-1 transition-colors hover:bg-secondary">
                    {audio ? (
                      <Volume2 size={12} className="shrink-0 text-muted-foreground" />
                    ) : (
                      <VolumeX size={12} className="shrink-0 text-muted-foreground" />
                    )}
                    <Pick
                      value={audio ? "on" : "off"}
                      onChange={(next) => setAudio(next === "on")}
                      options={[
                        { value: "on", label: t("boardWithSound") },
                        { value: "off", label: t("boardMuted") },
                      ]}
                    />
                  </span>
                </>
              )}

              <span className="ml-auto flex shrink-0 items-center gap-1">
                {maxImages(current) > 1 && (
                  <span className="flex items-center rounded-full px-1 transition-colors hover:bg-secondary">
                    <Pick
                      value={String(count)}
                      onChange={(next) => setCount(Number(next))}
                      options={Array.from({ length: maxImages(current) }, (_, index) => ({
                        value: String(index + 1),
                        label: `${index + 1}×`,
                      }))}
                    />
                  </span>
                )}
                <button
                  type="button"
                  aria-label={t("boardGenerate")}
                  title={`${t("boardGenerate")}  ⌘↵`}
                  disabled={!prompt.trim() || !current || busy}
                  onClick={send}
                  className={cn(
                    "grid h-7 w-7 shrink-0 place-items-center rounded-full transition-colors",
                    !prompt.trim() || !current || busy
                      ? "cursor-not-allowed bg-secondary text-muted-foreground"
                      : "cursor-pointer bg-primary text-primary-foreground hover:opacity-90",
                  )}
                >
                  {working ? <Loader2 size={13} className="animate-spin" /> : <ArrowUp size={13} />}
                </button>
              </span>
            </>
          )}
        </div>
      </div>
    </NodeToolbar>
  );
}
