import React from "react";
import { NodeToolbar, Position } from "@xyflow/react";
import { ArrowUp, AudioLines, Loader2 } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { listVoices, type BoardItem, type Voice } from "@/api/client";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

/**
 * 音频节点的「念出来」面板。
 *
 * **音频在这个应用里不是「生成」能力,是 TTS。** 出图出片选的是生成模型,而念一段字选的是
 * **音色** —— 硬塞进图片/视频那张描述符驱动的表单里,会长出一个永远没有比例、没有时长、
 * 参数栏全空的怪东西。
 *
 * 上游便签的文字**直接就是要念的内容**:一张写好的文案连过来,用户的意思就是「念这个」,
 * 让他再抄一遍那条线就白连了。
 */
export function AudioComposer({
  item,
  busy,
  workspaceId,
  upstreamText,
  onSpeak,
}: {
  item: BoardItem;
  busy: boolean;
  workspaceId: string;
  /** 上游便签给的文字 —— 念的就是它。 */
  upstreamText?: string;
  onSpeak: (input: { text: string; voiceId: string }) => void;
}) {
  const [text, setText] = React.useState(upstreamText ?? "");
  const [picked, setPicked] = React.useState("");

  //: 上游的字变了就跟着换 —— 但不覆盖用户自己改过的(和便签那条同一个道理)。
  const filled = React.useRef(upstreamText ?? "");
  React.useEffect(() => {
    const next = upstreamText ?? "";
    if (!next || next === filled.current) return;
    setText((current) => (current.trim() === "" || current === filled.current ? next : current));
    filled.current = next;
  }, [upstreamText]);

  const voices = useQuery({ queryKey: ["voices", workspaceId], queryFn: () => listVoices(workspaceId) });
  const options = voices.data ?? [];
  const current = options.find((one: Voice) => one.id === picked) ?? options[0] ?? null;

  //: 点下去**立刻**转圈,不等服务端回来。
  const [sending, setSending] = React.useState(false);
  const working = sending || busy;

  const send = () => {
    const body = text.trim();
    if (!body || working) return;
    setSending(true);
    onSpeak({ text: body, voiceId: current?.id ?? "" });
  };

  return (
    <NodeToolbar nodeId={item.id} isVisible position={Position.Bottom} offset={12}>
      <div className="nodrag nopan nowheel w-[420px] rounded-xl border border-border-strong bg-panel p-2 shadow-[var(--shadow-panel)]">
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
              event.preventDefault();
              send();
            }
          }}
          rows={3}
          placeholder="要念的文字 —— 上游连一张便签过来就自动填好了"
          className="w-full resize-none border-0 bg-transparent px-1.5 py-1 text-ui-sm leading-relaxed text-foreground outline-none placeholder:text-muted-foreground"
        />
        <div className="flex items-center gap-1 border-t border-border pt-1.5">
          {options.length === 0 ? (
            // 没有音色时说清楚 —— 给一个点了没反应的按钮比什么都不给更糟。
            <span className="px-1 text-ui-2xs text-muted-foreground">还没有可用的音色,先去「声音」里加一个</span>
          ) : (
            <span className="flex min-w-0 shrink items-center gap-0.5 rounded-full px-1 transition-colors hover:bg-secondary">
              <AudioLines size={12} className="shrink-0 text-muted-foreground" />
              <Select value={current?.id ?? ""} onValueChange={setPicked}>
                <SelectTrigger className="h-6 w-auto gap-0 border-0 bg-transparent px-1 text-ui-2xs text-muted-foreground shadow-none focus:ring-0 data-[state=open]:text-foreground [&>svg]:hidden">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="start">
                  {options.map((one: Voice) => (
                    <SelectItem key={one.id} value={one.id}>
                      {one.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </span>
          )}
          <button
            type="button"
            aria-label="念出来"
            title="念出来  ⌘↵"
            disabled={!text.trim() || options.length === 0 || working}
            onClick={send}
            className={cn(
              "ml-auto grid h-7 w-7 shrink-0 place-items-center rounded-full transition-colors",
              !text.trim() || options.length === 0 || working
                ? "cursor-not-allowed bg-secondary text-muted-foreground"
                : "cursor-pointer bg-primary text-primary-foreground hover:opacity-90",
            )}
          >
            {working ? <Loader2 size={13} className="animate-spin" /> : <ArrowUp size={13} />}
          </button>
        </div>
      </div>
    </NodeToolbar>
  );
}
