import React from "react";
import { X } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

/**
 * 输入框里那排**这次要带上去的东西**。
 *
 * 附件、笔记引用此前分成两排:附件在输入卡**外面**、笔记在里面,而且两处的小条各写了一份
 * 样式(一个有边框、`py-0.5`,一个没边框、`py-1`)。可它们回答的是同一个问题 —— 我这条
 * 消息里带了什么。分成两排的结果是:输入框上方浮着一排来路不明的东西,和下面那个框看不出
 * 关系;而两种小条挨着时又明显不是一套。
 *
 * 所以收成一排,放进输入卡里 —— 挨着正文,和「发送」在同一个框内,它们的去向才是清楚的。
 *
 * 这里只管**怎么显示**:缩略图、名字、去掉、点开。每一样东西怎么来的、点开该看到什么,
 * 由提供它的那一方在 ComposerChip 里说明(媒体走全局灯箱,文本和笔记走这里的只读弹层)。
 */
export interface ComposerChip {
  id: string;
  label: string;
  /** 有画面的给缩略图(图片、视频封面);没有的给图标。 */
  thumbnail?: string;
  icon: React.ReactNode;
  /** 自己处理的预览 —— 媒体交给全局灯箱,那里有翻页、Esc 和层级。 */
  onOpen?: () => void;
  /** 一段读一读的字(文本附件、笔记正文)。交给下面那个共用的只读弹层,不必各开一个。 */
  text?: { title: string; body: string };
  onRemove: () => void;
}

export function ComposerChips({
  chips,
  uploading,
  className,
}: {
  chips: ComposerChip[];
  uploading?: boolean;
  className?: string;
}) {
  const t = useI18n();
  const [reading, setReading] = React.useState<ComposerChip["text"] | null>(null);
  if (!chips.length && !uploading) return null;
  return (
    <>
      <div className={cn("flex flex-wrap items-center gap-1 pb-1.5", className)}>
        {chips.map((chip) => {
          const openable = Boolean(chip.onOpen || chip.text);
          return (
            // 一个 div 装两个按钮,而不是按钮套按钮:后者是非法 HTML,浏览器会把它拆开,
            // 键盘走到哪一个都不确定。
            <span
              key={chip.id}
              className="inline-flex max-w-52 items-center rounded-md border border-border bg-secondary pr-1 text-ui-xs text-foreground"
              title={chip.label}
            >
              <button
                type="button"
                disabled={!openable}
                onClick={() => (chip.text ? setReading(chip.text) : chip.onOpen?.())}
                className={cn(
                  "inline-flex min-w-0 items-center gap-1.5 rounded-l-md border-0 bg-transparent py-0.5 pl-0.5 pr-1 text-left text-inherit",
                  openable ? "cursor-pointer hover:text-primary" : "cursor-default",
                )}
              >
                {/* 缩略图和图标占同一个方格 —— 一排里有图有文件时,名字仍然从同一列开始。 */}
                <span className="grid size-5 shrink-0 place-items-center overflow-hidden rounded bg-muted text-muted-foreground">
                  {chip.thumbnail ? (
                    <img src={chip.thumbnail} alt="" className="size-5 object-cover" loading="lazy" />
                  ) : (
                    chip.icon
                  )}
                </span>
                <span className="truncate">{chip.label}</span>
              </button>
              <button
                type="button"
                className="inline-flex cursor-pointer border-0 bg-transparent p-0 text-muted-foreground hover:text-foreground"
                aria-label={`${t("close")} ${chip.label}`}
                onClick={chip.onRemove}
              >
                <X size={11} />
              </button>
            </span>
          );
        })}
        {uploading && <span className="text-ui-xs text-muted-foreground">{t("composerUploading")}</span>}
      </div>

      <Dialog open={Boolean(reading)} onOpenChange={(open) => !open && setReading(null)}>
        <DialogContent className="max-w-[min(46rem,calc(100vw-2rem))]">
          <DialogHeader>
            <DialogTitle className="truncate">{reading?.title}</DialogTitle>
          </DialogHeader>
          {/* 原样显示,不渲染 markdown:这里要看的是"我到底带上去了什么",而渲染过的版本
              和真正发出去的那段字不是一一对应的。 */}
          <pre className="m-0 max-h-[60vh] overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted p-3 text-ui-xs leading-relaxed text-foreground">
            {reading?.body}
          </pre>
        </DialogContent>
      </Dialog>
    </>
  );
}
