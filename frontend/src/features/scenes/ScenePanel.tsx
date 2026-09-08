import React from "react";
import { ChevronDown } from "lucide-react";

/**
 * 右栏的一节。**每一节自己滚,整栏不滚**,而且能折成一行。
 *
 * 此前是整栏一起滚:物体列表、检查器、镜头设置串成一长条,想看下面的字段就得把上面的列表
 * 也滚走 —— 而它们本来是**同时要看的东西**(选中哪个物体、它长什么样、它怎么走)。一起滚
 * 还有个副作用:列表被自己的 max-height 截断,而截断的位置和滚动位置无关,永远切在半行上。
 *
 * 折起来只留标题行:一台机位的运镜面板很长,而摆场景的时候完全不需要它 —— 与其滚过去,
 * 不如让它退成一行。开合状态记在本地,是「我习惯怎么用」不是场景数据(和吸附、灰模同一类)。
 */
const KEY = "mosael.scene.panels";

function readOpen(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Record<string, boolean>) : {};
  } catch {
    return {};
  }
}

function writeOpen(next: Record<string, boolean>): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* 记不住而已,这一次照常生效。 */
  }
}

export function ScenePanel({
  id,
  title,
  count,
  actions,
  children,
}: {
  /** 记忆开合用的稳定标识。 */
  id: string;
  title: string;
  /** 标题后面那个小数字(有就显示)。 */
  count?: number;
  /** 标题栏右侧的操作 —— 折起来时仍然可用,那是它放在标题栏而不是内容里的理由。 */
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(() => readOpen()[id] !== false);
  const toggle = () => {
    setOpen((was) => {
      writeOpen({ ...readOpen(), [id]: !was });
      return !was;
    });
  };
  return (
    <section className="scene-panel" data-open={open}>
      <header>
        <button
          type="button"
          className="scene-panel-toggle"
          aria-expanded={open}
          onClick={toggle}
        >
          <ChevronDown size={14} />
          <h2>
            {title}
            {count === undefined ? null : <span>{count}</span>}
          </h2>
        </button>
        {actions}
      </header>
      {open && <div className="scene-panel-body">{children}</div>}
    </section>
  );
}
