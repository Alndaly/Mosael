import * as React from "react";
import { ChevronLeft } from "lucide-react";

import { Button } from "@/components/ui/button";

/**
 * 画布类页面左上角那颗**身份胶囊**:回哪儿去 · 这是什么。
 *
 * 工作流、子图、创意画板三处此前各写了一份 —— 同一句话说三遍,而它们本来就是同一类东西
 * (「你现在在哪儿」)。三份里已经漂出了肉眼可见的差别:画板那份的字重是死的(见下),
 * 而没有任何东西会因此报错。
 *
 * **标题的字号字重必须挂在内部的 `<strong>` 上,不能挂在 `<button>` 上。**
 * `design/tokens.css` 里有一条**无层级**的 `button, input, select, textarea { font: inherit }`,
 * 它压过 `@layer utilities` —— 于是按钮上的 `text-ui-md` / `font-semibold` 一律不生效,
 * 元素静默回落到继承来的字号,而 class 还老老实实挂在 DOM 上(实测:同样两个类,
 * 放 `<span>` 上是 600/13.5px,放 `<button>` 上是 400/13px)。那条规则是有意留着的
 * (挪进 @layer base 会一次性把一批没人审视过的 shadcn 默认字号铺满全站),所以这里照它的
 * 说明走:类挂在内部元素上。
 *
 * `<strong>` 的浏览器默认字重是 bolder(700),所以还要**显式钉回 600** —— 不钉的话,
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
    <div className="flex items-center gap-1 rounded-full border border-border bg-panel/95 p-1 pr-2.5 shadow-[var(--shadow-panel)] backdrop-blur">
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
