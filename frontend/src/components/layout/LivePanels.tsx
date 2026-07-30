import React from "react";
import { MonitorPlay } from "lucide-react";

/**
 * 自动化任务悬浮卡片的**外壳**:圆角、边框、阴影、标题条。
 *
 * 内容本身是原生 `WebContentsView`(发布账号视图 / RPA 会话视图),由主进程挂在窗口右下角并叠成
 * 卡片堆。原生 View 画不了圆角与阴影(Electron 32 的 View 只有 setBackgroundColor / setBounds /
 * setVisible),而子视图永远盖在宿主页面之上 —— 所以外壳只能画在**视图下方**:主进程把卡片外廓
 * (含预留的标题条高度)经 publish:panels 下发,这里按同样的矩形铺一层圆角卡片,原生视图内缩 4px
 * 嵌在里面,于是圆角边框在视图四周露出来,看上去就是一个悬浮的小窗。
 *
 * 标题条是可点区域里唯一属于渲染层的部分(视图盖住了其余部分),步骤文案画在这里 —— 光看画面
 * 分不清「正在上传」和「卡住了」,步骤名才分得清。
 */
export function LivePanels() {
  const [cards, setCards] = React.useState<LivePanelCard[]>([]);
  // 步骤文案按会话 id 归档:几何走 publish:panels,文案走 browser:frame,两条流在这里按 id 合起来。
  const [labels, setLabels] = React.useState<Record<string, string>>({});

  React.useEffect(() => {
    const off = window.openStudioPublish?.onPanels?.((next) => setCards(next));
    return () => off?.();
  }, []);

  React.useEffect(() => {
    const off = window.openStudioBrowser?.onFrame((frame) => {
      if (!frame.label) return;
      setLabels((prev) => (prev[frame.sessionId] === frame.label ? prev : { ...prev, [frame.sessionId]: frame.label! }));
    });
    return () => off?.();
  }, []);

  if (!cards.length) return null;
  return (
    <>
      {cards.map((card) => (
        <div
          key={card.id}
          // pointer-events-none:卡片只是外壳,不该抢原生视图和界面的点击。
          className="pointer-events-none fixed z-[70] overflow-hidden border border-border-strong bg-panel shadow-[var(--shadow-raised)]"
          style={{
            left: card.x,
            top: card.y,
            width: card.width,
            height: card.height,
            borderRadius: card.radius,
          }}
        >
          <div
            className="flex items-center gap-1.5 px-2 text-[11px] text-muted-foreground"
            style={{ height: card.header }}
          >
            <MonitorPlay size={12} className="shrink-0 text-primary" />
            <span className="min-w-0 flex-1 truncate">{labels[card.id] ?? ""}</span>
          </div>
        </div>
      ))}
    </>
  );
}
