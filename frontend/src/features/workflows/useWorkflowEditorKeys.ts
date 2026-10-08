import React from "react";
import type { Node } from "@xyflow/react";

import { hasFocusedFloatingPanel } from "@/components/app/useFloatingPanel";
import type { WorkflowSaveState } from "@/features/workflows/useWorkflowSave";
import { isMarkerNode } from "@/features/workflows/workflowViewShared";
import { useSaveShortcut } from "@/lib/saveShortcut";
import { listenKeys } from "@/lib/shortcuts";

//: 编辑器的两组画布快捷键。WorkflowEditor 在原来那两条 effect 的位置调它们,注册顺序不变。

/**
 * 画布快捷键。
 *
 * ⌘/Ctrl+N 打开「添加节点」;⌘/Ctrl+Enter 运行;⌘/Ctrl+S 存盘。
 *
 * **N 和 Enter 在输入框里一律不劫持** —— 在节点检查器里打字时按 ⌘N,想要的是浏览器的新建窗口
 * (或什么都不发生),而不是画布上冒出一个节点。这和撤销那条同一个判据。
 *
 * **⌘S 例外:在检查器的字段里也存。** 在字段里改完按 ⌘S,想的就是存这一张;此前它在字段里让路,
 * 网页版弹的是浏览器的「存储网页」。它走全应用那一条(lib/saveShortcut),不在这里另听。
 */
export function useWorkflowEditorShortcuts({
  save,
  startRun,
}: {
  save: WorkflowSaveState["save"];
  startRun: () => Promise<void>;
}) {
  useSaveShortcut(() => {
    if (!save.isPending) save.mutate();
  });
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.altKey || event.shiftKey) return;
      const target = event.target as HTMLElement | null;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
      const key = event.key.toLowerCase();
      if (key === "n") {
        // 点那个按钮,而不是给 SearchableSelect 加一个受控 prop —— 它的开合是内部状态,
        // 为一个快捷键把它改成受控,调用它的另外几处都要跟着改。
        const trigger = document.querySelector<HTMLButtonElement>("[data-wf-add-node]");
        if (!trigger) return;
        event.preventDefault();
        trigger.click();
      } else if (event.key === "Enter") {
        event.preventDefault();
        void startRun();
      }
    };
    return listenKeys(window, onKey);
  });
}

/**
 * Cmd/Ctrl+] 把选中节点提到最前、[ 压到最后。与悬浮窗、剪辑页片段同键同义。
 *
 * **夹在 ±900 而不是无穷**:React Flow 的 elevateNodesOnSelect 是给选中节点的 z **加** 1000
 * (实测手动置顶的选中节点是 1001、压底的是 999)。手动值只要不越过 1000,"选中的那个恒在
 * 最上面"就一直成立 —— 而选中的正是用户此刻在操作的那个,它被别人压住最说不通。
 *
 * 节点层级永远盖不过悬浮窗,这一点不靠数值保证也保证不了 —— 靠的是 .react-flow__viewport
 * 带 transform 自成层叠上下文,里面的 z 再大也只在画布内部排序。数值只管画布内部的秩序。
 */
export function useWorkflowNodeZ(nodes: Node[]): Record<string, number> {
  /** 节点的手动层级。只在会话内有效,不写进图 —— 叠放是看图时的临时诉求(把被压住的那个
   *  拎出来看一眼),固化进数据会让每次调整都变成一次图变更、触发自动保存。 */
  const [nodeZ, setNodeZ] = React.useState<Record<string, number>>({});
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.altKey) return;
      if (event.key !== "[" && event.key !== "]") return;
      // 悬浮窗握着焦点时这组键归它。点回画布(onPaneClick / onNodeClick)才交还。
      if (hasFocusedFloatingPanel()) return;
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) return;
      const picked = nodes.filter((node) => node.selected && !isMarkerNode(node)).map((node) => node.id);
      if (picked.length === 0) return;
      event.preventDefault(); // Chromium 里这两个键是后退/前进
      setNodeZ((current) => {
        const values = Object.values(current);
        const next = { ...current };
        if (event.key === "]") {
          const top = Math.min(Math.max(0, ...values) + 1, 900);
          for (const id of picked) next[id] = top;
        } else {
          const bottom = Math.max(Math.min(0, ...values) - 1, -900);
          for (const id of picked) next[id] = bottom;
        }
        return next;
      });
    };
    return listenKeys(window, onKey);
  }, [nodes]);
  return nodeZ;
}
