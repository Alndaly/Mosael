import * as React from "react";
import { ChevronLeft } from "lucide-react";

import { Button } from "@/components/ui/button";
import { CANVAS_GLASS_SURFACE_CLASS } from "@/components/app/canvasPanelLayout";
import { cn } from "@/lib/utils";

/**
 * 画布类页面左上角那颗**身份胶囊**:回哪儿去 · 这是什么。
 *
 * 工作流、子图、创意画板三处此前各写了一份 —— 同一句话说三遍,而它们本来就是同一类东西
 * (「你现在在哪儿」)。三份里已经漂出了肉眼可见的差别:画板那份的 `font-semibold` 是死的,
 * 而没有任何东西会因此报错。
 *
 * 字号字重挂在内部的 `<strong>` 上。**这里不再是绕路** —— 那条
 * `button { font: inherit }` 已经挪进 `@layer base`(2026-08),按钮上的字体类现在正常生效;
 * 留在 `<strong>` 上是因为这块标题本来就是"名字 + 可选的一行小字"两段,两段各有各的字号,
 * 挂在按钮上反而说不清是在说哪一段。
 *
 * `<strong>` 的浏览器默认字重是 bolder(700),所以要**显式钉回 600** —— 不钉的话,
 * 这块标题会比隔壁页面同类的那块明显更粗。
 */
export function CanvasTitle({
  onBack,
  backLabel,
  backIcon,
  icon,
  name,
  sub,
  onRename,
  renameLabel,
}: {
  onBack: () => void;
  /** 返回键的说明 —— 说的是**回到哪儿**(「工作流」「创意画板」),不是「返回」。 */
  backLabel: string;
  /** 缺省是 `<`(回上一层清单)。子图那种"离开这一层"的场景可以换成 `←`。 */
  backIcon?: React.ReactNode;
  /** 名字前面那个小图标。主画布不给 —— 左边导航栏已经亮着那一格,顶上再画一次是同一句话说两遍。 */
  icon?: React.ReactNode;
  name: React.ReactNode;
  /** 名字下面那行小字。没有就不占位。 */
  sub?: React.ReactNode;
  /** 给了就可以点标题改名;不给就是一段纯展示的文字(子图的名字在它的节点上改)。 */
  onRename?: () => void;
  renameLabel?: string;
}) {
  const body = (
    <span className="grid leading-[1.3] [&_small]:text-ui-xs [&_small]:font-normal [&_small]:text-muted-foreground [&_strong]:text-ui-md [&_strong]:font-semibold">
      <strong className="inline-flex items-center gap-[5px]">
        {icon}
        {name}
      </strong>
      {sub ? <small>{sub}</small> : null}
    </span>
  );

  return (
    <div className={cn("flex items-center gap-1 rounded-full p-1 pr-2.5", CANVAS_GLASS_SURFACE_CLASS)}>
      {/* 返回键**给它一个底**。透明底的图标钮在胶囊里没有自己的轮廓,左边和胶囊边缘之间那点
          空白就显得忽大忽小 —— 有了底,它的占位是确定的,和右边的竖线、名字也就对齐了。 */}
      <Button
        variant="secondary"
        size="icon"
        className="h-8 w-8 shrink-0"
        onClick={onBack}
        title={backLabel}
        aria-label={backLabel}
      >
        {backIcon ?? <ChevronLeft size={16} />}
      </Button>
      {/* 一个是「离开这里」,一个是「这里是什么」—— 两件事,挨着放需要一道界。 */}
      <span aria-hidden className="mx-0.5 h-4 w-px shrink-0 bg-border" />
      {onRename ? (
        <button
          type="button"
          className="inline-flex cursor-pointer items-center rounded-full border-0 bg-transparent px-1.5 py-[3px] text-left text-foreground hover:bg-secondary"
          onClick={onRename}
          title={renameLabel}
        >
          {body}
        </button>
      ) : (
        <span className="inline-flex items-center px-1.5 py-[3px] text-foreground">{body}</span>
      )}
    </div>
  );
}
