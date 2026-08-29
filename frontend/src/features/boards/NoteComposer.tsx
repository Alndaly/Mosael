import React from "react";
import { NodeToolbar, Position } from "@xyflow/react";
import { ArrowUp, Loader2, Sparkles } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { listCapabilityModels, type BoardItem } from "@/api/client";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

/**
 * 便签的「写文案」面板。
 *
 * **和图片/视频那张不是同一张表。** 那边的每一项(比例、清晰度、时长、参考图)都由生成描述符
 * 说了算,所以是照着描述符出控件;写字这边没有那些东西 —— 一个模型、一句要求,就这两样。
 * 硬塞进同一个组件的话,里面会长出一堆「文本的时候不显示」的分支,而那正是表单开始骗人的
 * 起点。
 *
 * 模型列的是 **chat 能力**下的全部模型(跨连接),和设置里挑默认模型看到的是同一份。
 */
export function NoteComposer({
  item,
  busy,
  onWrite,
}: {
  item: BoardItem;
  busy: boolean;
  onWrite: (input: { prompt: string; providerProfileId: string; model: string }) => void;
}) {
  const [prompt, setPrompt] = React.useState("");
  const [picked, setPicked] = React.useState("");

  const models = useQuery({ queryKey: ["capability-models", "chat"], queryFn: () => listCapabilityModels("chat") });
  const options = models.data ?? [];
  //: 值里带上连接 id:同一个模型名可能挂在两条连接下(自己的和团队的),只存模型名会挑错那条。
  const current = options.find((one) => `${one.provider_profile_id}:${one.model}` === picked) ?? options[0] ?? null;

  const send = () => {
    const text = prompt.trim();
    if (!text || !current || busy) return;
    onWrite({ prompt: text, providerProfileId: current.provider_profile_id, model: current.model });
  };

  return (
    <NodeToolbar nodeId={item.id} isVisible position={Position.Bottom} offset={12}>
      <div className="nodrag nopan nowheel w-[420px] rounded-xl border border-border-strong bg-panel p-2 shadow-[var(--shadow-panel)]">
        <textarea
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          // ⌘/Ctrl+Enter 提交:光按 Enter 会和换行打架,而要求经常要分行写。
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
              event.preventDefault();
              send();
            }
          }}
          rows={3}
          //: 有字和没字问的**不是同一件事**:一个是「写什么」,一个是「怎么改」。
          //: 用同一句提示语的话,用户会以为它要把整篇重写一遍。
          placeholder={
            (item.text ?? "").trim()
              ? "想怎么改?例如:短一半、换成更口语的说法、再来三版"
              : "想让它写什么?例如:给这条片子写三版短视频开头"
          }
          className="w-full resize-none border-0 bg-transparent px-1.5 py-1 text-ui-sm leading-relaxed text-foreground outline-none placeholder:text-muted-foreground"
        />
        <div className="flex items-center gap-1 border-t border-border pt-1.5">
          {options.length === 0 ? (
            // 没有可用模型时说清楚 —— 给一个点了没反应的按钮比什么都不给更糟。
            <span className="px-1 text-ui-2xs text-muted-foreground">还没有可用的对话模型,先去设置里配一个</span>
          ) : (
            <span className="flex min-w-0 shrink items-center gap-0.5 rounded-full px-1 transition-colors hover:bg-secondary">
              <Sparkles size={12} className="shrink-0 text-muted-foreground" />
              <Select value={`${current?.provider_profile_id}:${current?.model}`} onValueChange={setPicked}>
                <SelectTrigger className="h-6 w-auto gap-0 border-0 bg-transparent px-1 text-ui-2xs text-muted-foreground shadow-none focus:ring-0 data-[state=open]:text-foreground [&>svg]:hidden">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="start">
                  {options.map((one) => (
                    <SelectItem key={`${one.provider_profile_id}:${one.model}`} value={`${one.provider_profile_id}:${one.model}`}>
                      {one.display_name || one.model}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </span>
          )}
          <button
            type="button"
            aria-label={(item.text ?? "").trim() ? "改写" : "写"}
            title={`${(item.text ?? "").trim() ? "改写" : "写"}  ⌘↵`}
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
