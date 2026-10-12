import React from "react";

import { useI18n } from "@/app/preferences";
import { locateNode } from "@/features/plugins/workbench/locateNode";
import { cn } from "@/lib/utils";

/**
 * 在画布上定位一个节点的按钮:助手回复里的 `#12`(AssistantPanel 的 NodeRef)和「工作流里能填的」那一列节点分组
 * 标题上的 `#706`(appForm/SourcePanel)共用这一颗 —— 一个能力不写两份。点下去经桥选中那个节点、移到中间,没成
 * 就在旁边说一句(见 locateNode:画布上没有、在子图里、桥没做成)。
 *
 * **说明浮层不挂在这一层**:两处的说明说的不是同一件事 —— 回复里是「在画布上定位 #12」,而表单标题上那条 Hint 说的
 * 是这个节点**是什么**(节点号 · 类名)。由用它的地方按自己那一处挂,一处只留一条;按钮上只有 `#12` 这几个字,
 * 读屏和键盘用户听不出它是干什么的,所以名字走 `ariaLabel`。
 *
 * 长相是「正文里的链接」那一套(虚线下划线,悬停变实线);表单标题里那几个字更小更淡,由 `className` 覆盖
 * (字号、字体、颜色都是同一组 class,后写的赢,见 lib/utils 的 cn)。
 */
export function LocateNodeButton({ node, label, ariaLabel, className }: {
  node: string;
  /** 按钮上的字,不给就是 `#节点号`。 */
  label?: React.ReactNode;
  /** 读屏和键盘用户听到的全名(按钮上只有 `#12` 时给一句,比如「在画布上定位 #12」)。 */
  ariaLabel?: string;
  className?: string;
}) {
  const t = useI18n();
  const [note, setNote] = React.useState("");
  const locate = () => {
    setNote("");
    void locateNode(t, node).then(setNote);
  };
  return (
    <>
      <button
        type="button"
        data-comfy-node={node}
        aria-label={ariaLabel}
        className={cn(
          "cursor-pointer rounded-sm border-0 bg-transparent p-0 font-mono text-[0.95em] text-primary underline decoration-dotted underline-offset-2 hover:decoration-solid",
          className,
        )}
        onClick={locate}
      >
        {label ?? `#${node}`}
      </button>
      {note && <span role="status" className="ml-1 text-ui-xs text-destructive">{note}</span>}
    </>
  );
}
