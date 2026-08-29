import React from "react";
import { NodeToolbar, Position } from "@xyflow/react";
import { ArrowUp, Loader2, Sparkles, Volume2, VolumeX } from "lucide-react";

import type { BoardItem, GenerationModel } from "@/api/client";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  aspectRatioOptions,
  capabilityNumber,
  capabilityString,
  durationOptions,
  maxImages,
  sizeOptions,
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
      <SelectTrigger className="h-6 w-auto gap-0.5 border-0 bg-transparent px-1 text-ui-2xs text-muted-foreground shadow-none focus:ring-0 [&>svg]:h-3 [&>svg]:w-3">
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

export function NodeComposer({
  item,
  models,
  busy,
  onSubmit,
}: {
  item: BoardItem;
  /** 这种能力下可选的模型。空数组 = 还没配 —— 那时该说清楚,而不是给一个点了没反应的按钮。 */
  models: GenerationModel[];
  busy: boolean;
  onSubmit: (input: { prompt: string; provider: string; model: string; parameters: Record<string, unknown> }) => void;
}) {
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

  const send = () => {
    const text = prompt.trim();
    if (!text || !current || busy) return;
    //: 只发这个模型**认的**那几项 —— 多发一项会被校验器当场拦下(它照描述符判)。
    const parameters: Record<string, unknown> = {};
    if (supportsParameter(current, "aspect_ratio") && ratio) parameters.aspect_ratio = ratio;
    if (supportsParameter(current, "resolution") && resolution) parameters.resolution = resolution;
    if (supportsParameter(current, "size") && size) parameters.size = size;
    if (supportsParameter(current, "duration_seconds")) parameters.duration_seconds = duration;
    if (current.capabilities?.supports_audio && audio) parameters.generate_audio = true;
    if (maxImages(current) > 1 && count > 1) parameters.num_images = count;
    onSubmit({ prompt: text, provider: current.provider, model: current.model, parameters });
  };

  return (
    <NodeToolbar nodeId={item.id} isVisible position={Position.Bottom} offset={12}>
      <div className="nodrag nopan nowheel w-[420px] rounded-xl border border-border-strong bg-panel p-2 shadow-[var(--shadow-panel)]">
        <textarea
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          // ⌘/Ctrl+Enter 提交:光按 Enter 会和换行打架,而提示词经常要分行写。
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
              event.preventDefault();
              send();
            }
          }}
          rows={3}
          placeholder="描述你想要生成的内容"
          className="w-full resize-none border-0 bg-transparent px-1.5 py-1 text-ui-sm leading-relaxed text-foreground outline-none placeholder:text-muted-foreground"
        />
        {/* 参数行:**按这个模型声明的来**,不写死。
            后端描述符已经说清楚了每个模型认哪几项(aspect_ratio / resolution /
            duration_seconds / size / num_images / generate_audio),这里照着出控件 ——
            换一个模型,这一行自己就变了。写死的话每接一个新模型都要回来改一次,
            而漏改不会报错,只会让那一项永远调不了。 */}
        <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 border-t border-border pt-1.5">
          <Sparkles size={12} className="shrink-0 text-muted-foreground" />
          {options.length === 0 ? (
            // 没有可用模型时说清楚 —— 给一个点了没反应的按钮比什么都不给更糟。
            <span className="text-ui-2xs text-muted-foreground">还没有可用的生成模型,先去设置里配一个</span>
          ) : (
            <>
              <Pick value={modelValue} onChange={setPicked} options={options.map((one) => ({ value: `${one.provider}/${one.model}`, label: one.model }))} />

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
              {/* 出声与否:描述符里是 supports_audio 那条已核过的声明,不是又一个旋钮。 */}
              {Boolean(current?.capabilities?.supports_audio) && (
                <button
                  type="button"
                  aria-pressed={audio}
                  title={audio ? "生成声音" : "不生成声音"}
                  onClick={() => setAudio((on) => !on)}
                  className={cn(
                    "grid h-6 w-6 shrink-0 place-items-center rounded-md transition-colors",
                    audio ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-secondary",
                  )}
                >
                  {audio ? <Volume2 size={12} /> : <VolumeX size={12} />}
                </button>
              )}
              {maxImages(current) > 1 && (
                <Pick
                  value={String(count)}
                  onChange={(next) => setCount(Number(next))}
                  options={Array.from({ length: maxImages(current) }, (_, index) => ({
                    value: String(index + 1),
                    label: `${index + 1}×`,
                  }))}
                />
              )}
            </>
          )}
          <button
            type="button"
            aria-label="生成"
            title="生成  ⌘↵"
            disabled={!prompt.trim() || !current || busy}
            onClick={send}
            className={cn(
              "ml-auto grid h-7 w-7 shrink-0 place-items-center rounded-full transition-colors",
              !prompt.trim() || !current || busy
                ? "cursor-not-allowed bg-secondary text-muted-foreground"
                : "cursor-pointer bg-primary text-primary-foreground hover:opacity-90",
            )}
          >
            {busy ? <Loader2 size={13} className="animate-spin" /> : <ArrowUp size={13} />}
          </button>
        </div>
      </div>
    </NodeToolbar>
  );
}
