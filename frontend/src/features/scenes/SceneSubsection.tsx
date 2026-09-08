import React from "react";
import { ChevronRight } from "lucide-react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";

/**
 * 面板里的一个次级折叠块(「走位」「精确位置与旋转」「镜头高级设置」这一层)。
 *
 * **换掉原生 `<details>`。** 那个三角形由浏览器画:大小、粗细、颜色都不归我们管,在深色面板里
 * 它比旁边所有 lucide 图标都重一档,而且开合没有过渡 —— 内容是"啪"地出现的。这也是右栏看起来
 * 乱的一部分:同一栏里同时存在两种"可展开"的样式。
 *
 * 它和 `ScenePanel` 的区别是**层级**:面板是右栏的一节(能撑满、内部滚动、记忆开合),
 * 这个是节里面的一小段(跟着内容走,不记忆)。
 */
export function SceneSubsection({
  title,
  defaultOpen = false,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(defaultOpen);
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="scene-subsection">
      <CollapsibleTrigger className="scene-subsection-toggle">
        <ChevronRight size={13} />
        {title}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="scene-subsection-body">{children}</div>
      </CollapsibleContent>
    </Collapsible>
  );
}
