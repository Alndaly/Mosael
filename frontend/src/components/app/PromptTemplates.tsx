import React from "react";
import { LayoutTemplate } from "lucide-react";

import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { IconButton } from "@/components/ui/icon-button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Truncate } from "@/components/ui/truncate";
import { cn } from "@/lib/utils";

/**
 * 生图提示词模板:不知道怎么写的时候,挑一张照着改。
 *
 * 模板正文在文案表里(中英各一份),`【】` 里是要换成自己内容的地方。**宫格那一组**和图片格上的「宫格切分」
 * 是一对:先出一张九宫格表情包 / 四格分镜,再一键切成单图。
 *
 * 画板的生成面板和 AI 工作台的生成页共用这一个;挑中之后怎么放进提示词由调用方决定(onPick 给的是正文)。
 */
export const PROMPT_TEMPLATE_GROUPS: { id: string; label: MessageKey; templates: { id: string; title: MessageKey; prompt: MessageKey }[] }[] = [
  {
    id: "portrait",
    label: "promptTplGroupPortrait",
    templates: [
      { id: "studio", title: "promptTplStudioTitle", prompt: "promptTplStudio" },
      { id: "street", title: "promptTplStreetTitle", prompt: "promptTplStreet" },
      { id: "headshot", title: "promptTplHeadshotTitle", prompt: "promptTplHeadshot" },
    ],
  },
  {
    id: "product",
    label: "promptTplGroupProduct",
    templates: [
      { id: "white", title: "promptTplWhiteTitle", prompt: "promptTplWhite" },
      { id: "lifestyle", title: "promptTplLifestyleTitle", prompt: "promptTplLifestyle" },
      { id: "splash", title: "promptTplSplashTitle", prompt: "promptTplSplash" },
    ],
  },
  {
    id: "poster",
    label: "promptTplGroupPoster",
    templates: [
      { id: "event", title: "promptTplEventTitle", prompt: "promptTplEvent" },
      { id: "cinema", title: "promptTplCinemaTitle", prompt: "promptTplCinema" },
    ],
  },
  {
    id: "illustration",
    label: "promptTplGroupIllustration",
    templates: [
      { id: "flat", title: "promptTplFlatTitle", prompt: "promptTplFlat" },
      { id: "watercolor", title: "promptTplWatercolorTitle", prompt: "promptTplWatercolor" },
      { id: "cartoon3d", title: "promptTplCartoon3dTitle", prompt: "promptTplCartoon3d" },
      { id: "guofeng", title: "promptTplGuofengTitle", prompt: "promptTplGuofeng" },
    ],
  },
  {
    id: "scene",
    label: "promptTplGroupScene",
    templates: [
      { id: "interior", title: "promptTplInteriorTitle", prompt: "promptTplInterior" },
      { id: "landscape", title: "promptTplLandscapeTitle", prompt: "promptTplLandscape" },
    ],
  },
  {
    id: "grid",
    label: "promptTplGroupGrid",
    templates: [
      { id: "stickers", title: "promptTplStickersTitle", prompt: "promptTplStickers" },
      { id: "storyboard", title: "promptTplStoryboardTitle", prompt: "promptTplStoryboard" },
      { id: "turnaround", title: "promptTplTurnaroundTitle", prompt: "promptTplTurnaround" },
    ],
  },
];

/** 挑中的模板放进已有的提示词:空着就是它,写了东西就接在后面 —— 不替人删掉已经写好的。 */
export function withTemplate(current: string, template: string): string {
  return current.trim() ? `${current.trimEnd()}\n${template}` : template;
}

/** 输入卡底栏里的「模板」按钮:弹层左边分组,右边这一组的模板(标题 + 两行预览),点一张就交出正文。 */
export function PromptTemplateButton({ onPick, className }: { onPick: (prompt: string) => void; className?: string }) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const [group, setGroup] = React.useState(PROMPT_TEMPLATE_GROUPS[0].id);
  const current = PROMPT_TEMPLATE_GROUPS.find((one) => one.id === group) ?? PROMPT_TEMPLATE_GROUPS[0];
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <IconButton
          variant="ghost"
          size="icon-xs"
          className={className}
          label={t("promptTemplates")}
          data-prompt-templates=""
        >
          <LayoutTemplate size={14} />
        </IconButton>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[min(520px,calc(100vw-16px))] p-0">
        <div className="grid grid-cols-[8.5rem_minmax(0,1fr)]">
          <div role="tablist" aria-label={t("promptTemplates")} className="grid content-start gap-0.5 border-r border-divider p-1.5">
            {PROMPT_TEMPLATE_GROUPS.map((one) => (
              <button
                key={one.id}
                type="button"
                role="tab"
                aria-selected={one.id === current.id}
                onClick={() => setGroup(one.id)}
                className={cn(
                  "cursor-pointer rounded-md border-0 px-2 py-1.5 text-left text-ui-xs transition-colors",
                  one.id === current.id ? "bg-secondary text-foreground" : "bg-transparent text-muted-foreground hover:text-foreground",
                )}
              >
                {t(one.label)}
              </button>
            ))}
          </div>
          <div role="tabpanel" className="grid max-h-[min(360px,60vh)] content-start gap-1 overflow-y-auto p-1.5">
            {current.templates.map((one) => (
              <button
                key={one.id}
                type="button"
                data-prompt-template={one.id}
                onClick={() => {
                  onPick(t(one.prompt));
                  setOpen(false);
                }}
                className="grid cursor-pointer gap-0.5 rounded-md border-0 bg-transparent px-2 py-1.5 text-left hover:bg-secondary"
              >
                <span className="text-ui-xs font-medium text-foreground">{t(one.title)}</span>
                <Truncate lines={2} className="text-ui-2xs leading-relaxed text-muted-foreground">{t(one.prompt)}</Truncate>
              </button>
            ))}
          </div>
        </div>
        <p className="m-0 border-t border-divider px-3 py-1.5 text-ui-2xs text-muted-foreground">{t("promptTemplatesHint")}</p>
      </PopoverContent>
    </Popover>
  );
}
