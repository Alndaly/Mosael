import React from "react";
import { NodeToolbar, Position } from "@xyflow/react";
import { ArrowUp, Loader2, Sparkles } from "lucide-react";

import type { BoardItem, GenerationModel } from "@/api/client";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
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
  onSubmit: (input: { prompt: string; provider: string; model: string }) => void;
}) {
  const [prompt, setPrompt] = React.useState(item.text ?? "");
  const [picked, setPicked] = React.useState("");

  const options = React.useMemo(
    () => models.filter((model) => model.kind === item.kind),
    [models, item.kind],
  );
  const current = options.find((model) => `${model.provider}/${model.model}` === picked) ?? options[0];

  const send = () => {
    const text = prompt.trim();
    if (!text || !current || busy) return;
    onSubmit({ prompt: text, provider: current.provider, model: current.model });
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
        <div className="flex items-center gap-1.5 border-t border-border pt-1.5">
          <Sparkles size={12} className="shrink-0 text-muted-foreground" />
          {options.length === 0 ? (
            // 没有可用模型时说清楚 —— 给一个点了没反应的按钮比什么都不给更糟。
            <span className="text-ui-2xs text-muted-foreground">还没有可用的生成模型,先去设置里配一个</span>
          ) : (
            <Select
              value={picked || (current ? `${current.provider}/${current.model}` : "")}
              onValueChange={setPicked}
            >
              <SelectTrigger className="h-6 min-w-0 flex-1 border-0 bg-transparent px-1 text-ui-2xs text-muted-foreground shadow-none focus:ring-0">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {options.map((model) => (
                  <SelectItem key={`${model.provider}/${model.model}`} value={`${model.provider}/${model.model}`}>
                    {model.model}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          <button
            type="button"
            aria-label="生成"
            title="生成  ⌘↵"
            disabled={!prompt.trim() || !current || busy}
            onClick={send}
            className={cn(
              "grid h-7 w-7 shrink-0 place-items-center rounded-full transition-colors",
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
