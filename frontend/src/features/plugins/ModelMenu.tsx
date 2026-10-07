import React from "react";
import {
  Copy,
  ExternalLink,
  Expand,
  FolderTree,
  ImageDown,
  ImageUp,
  Loader2,
  PanelRightOpen,
  RotateCcw,
  SearchCheck,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Workflow,
} from "lucide-react";

import type { ModelFile } from "@/api/client";
import { useI18n } from "@/app/preferences";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuSub,
  ContextMenuSubContent,
  ContextMenuSubTrigger,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { MenuItemBody } from "@/components/ui/menu";
import { ModelActionsContext, type ModelActions } from "@/features/plugins/modelActions";
import { targetNote } from "@/features/plugins/modelLibraryView";
import { formedGroups } from "@/lib/entryNames";

/**
 * 模型库里一个模型的菜单(右键、卡片上的 ⋯、Shift+F10 / 菜单键):**同一份菜单**,用的是应用的右键菜单组件。
 *
 * ⋯ 和键盘不另画一份 Popover 菜单(素材库那样两份清单手抄,迟早一边漏一项):它们在卡片上派一个 `contextmenu`
 * 事件,打开的就是右键那一个 —— 子菜单(「用它生成」挑工作流)、方向键、Esc 都是一套。
 *
 * 条目按组排,用不上的不摆;摆着却点不了的,在名字下面一行写为什么。只对一个模型(右键哪张就是哪张)。
 * 不提供删除那台服务器上的模型文件:那是远端的、删了找不回来的事,不放在一个右键菜单里。
 */


type Entry =
  | { kind: "item"; key: string; label: string; icon: React.ReactNode; onSelect: () => void; disabledReason?: string | null;
      description?: string; hint?: string }
  | { kind: "sub"; key: string; label: string; icon: React.ReactNode; items: Entry[] };

const copy = (text: string) => void navigator.clipboard?.writeText(text);

/** 一个模型的菜单条目,按组。`openLabel`:打开详情那一项叫什么(工作台里叫「查看详情」:那里点一行是填进画布)。 */
export function modelMenuGroups(model: ModelFile, actions: ModelActions, t: ReturnType<typeof useI18n>, openLabel?: string): Entry[][] {
  const used = model.used_by ?? [];
  const targets = actions.targets(model);
  const formed = formedGroups(targets.map((target) => target.option));
  const generate: Entry =
    targets.length > 1
      ? {
          kind: "sub", key: "generate", label: t("modelUseToGenerate"), icon: <Sparkles />,
          items: targets.map((target) => ({
            kind: "item" as const, key: `generate:${target.option.id}`, label: target.name, icon: <Workflow />,
            description: targetNote(target, formed, t) || undefined,
            onSelect: () => actions.generate(model, target),
          })),
        }
      : {
          kind: "item", key: "generate", label: t("modelUseToGenerate"), icon: <Sparkles />,
          description: targets.length === 1 ? targets[0].name : undefined,
          disabledReason: targets.length === 0
            ? actions.targetsLoading() ? t("modelUseToGenerateLoading") : t("modelUseToGenerateNone")
            : null,
          onSelect: () => targets[0] && actions.generate(model, targets[0]),
        };
  const nsfw = model.nsfw;
  const marks: Entry[] = [
    nsfw?.flagged
      ? { kind: "item", key: "nsfw-off", label: t("modelNsfwUnmark"), icon: <ShieldCheck />,
          onSelect: () => actions.markNsfw(model, false) }
      : { kind: "item", key: "nsfw-on", label: t("modelNsfwMark"), icon: <ShieldAlert />,
          onSelect: () => actions.markNsfw(model, true) },
    ...(nsfw?.manual != null
      ? [{ kind: "item" as const, key: "nsfw-auto", label: t("modelNsfwClearMark"), icon: <RotateCcw />,
           onSelect: () => actions.markNsfw(model, null) }]
      : []),
  ];
  return [
    [
      { kind: "item", key: "open", label: openLabel ?? t("modelMenuOpen"), icon: <PanelRightOpen />, onSelect: () => actions.open(model) },
      generate,
    ],
    [
      { kind: "item", key: "copy-name", label: t("modelCopyName"), icon: <Copy />, onSelect: () => copy(model.name) },
      { kind: "item", key: "copy-path", label: t("modelCopyPath"), icon: <FolderTree />,
        description: `${model.folder}/${model.name.replace(/\\/g, "/")}`,
        onSelect: () => copy(`${model.folder}/${model.name.replace(/\\/g, "/")}`) },
      { kind: "item", key: "used", label: t("modelMenuUsedBy"), icon: <Workflow />, hint: String(used.length),
        disabledReason: used.length === 0 ? t("modelUsedByNone") : null, onSelect: () => actions.openUsed(model) },
    ],
    [
      ...(model.source?.page
        ? [{ kind: "item" as const, key: "source", label: t("modelMenuOpenSource"), icon: <ExternalLink />,
             description: model.source.page.replace(/^https?:\/\//, ""), onSelect: () => actions.openSource(model) }]
        : []),
      // 有预览图的(那台服务器上的、别处的):去 Civitai 上找出处、NSFW 标记;没有的:找来一张示例图当预览图。
      // 点了菜单就关上,进度在任务中心;正在找时再打开,这一行点不了、图标在转(和剪辑素材池右键的「分离人声与背景音」一样)
      { kind: "item", key: "lookup",
        icon: actions.lookupRunning(model) ? <Loader2 className="animate-mosael-spin" />
          : model.has_preview ? <SearchCheck /> : <ImageDown />,
        label: t(model.has_preview ? "modelLookup" : "modelLookupPreview"),
        disabledReason: actions.lookupUnavailable(model), onSelect: () => actions.lookUp(model) },
    ],
    [
      ...(model.preview_origin && model.preview_origin !== "server"
        ? [{ kind: "item" as const, key: "save-preview", label: t("modelSavePreview"), icon: <ImageUp />,
             disabledReason: actions.saveUnavailable(model), onSelect: () => actions.savePreview(model) }]
        : []),
      { kind: "item", key: "large", label: t("modelMenuShowLarge"), icon: <Expand />,
        disabledReason: actions.largeUnavailable(model), onSelect: () => actions.showLarge(model) },
    ],
    marks,
  ];
}

function MenuEntry({ entry }: { entry: Entry }) {
  if (entry.kind === "sub") {
    return (
      <ContextMenuSub>
        <ContextMenuSubTrigger>
          <MenuItemBody icon={entry.icon} label={entry.label} />
        </ContextMenuSubTrigger>
        <ContextMenuSubContent>
          {entry.items.map((item) => (
            <MenuEntry key={item.key} entry={item} />
          ))}
        </ContextMenuSubContent>
      </ContextMenuSub>
    );
  }
  return (
    <ContextMenuItem disabled={Boolean(entry.disabledReason)} onSelect={entry.onSelect} data-menu-entry={entry.key}>
      <MenuItemBody
        icon={entry.icon}
        label={entry.label}
        description={entry.disabledReason || entry.description}
        truncate={entry.kind === "item" && entry.key.startsWith("generate:")}
        hint={entry.hint}
      />
    </ContextMenuItem>
  );
}

/** 在一个元素上像右键那样打开它的菜单(⋯、Shift+F10 / 菜单键用):菜单出在这个元素的左下角。 */
export function openMenuAt(trigger: HTMLElement | null, anchor: HTMLElement) {
  if (!trigger) return;
  const rect = anchor.getBoundingClientRect();
  trigger.dispatchEvent(new MouseEvent("contextmenu", {
    bubbles: true, cancelable: true, clientX: rect.left, clientY: rect.bottom, button: 2,
  }));
}

/** 按下的是不是「打开菜单」的键:Shift+F10 或键盘上的菜单键。 */
export const isMenuKey = (event: React.KeyboardEvent) => event.key === "ContextMenu" || (event.shiftKey && event.key === "F10");

/**
 * 把一张卡、一行包成右键菜单的触发区。`children` 拿到一个 `openFrom(元素)`:⋯ 和键盘用它打开同一个菜单,
 * 关上之后焦点回到打开它的那个元素。
 */
export function ModelContextMenu({
  model,
  openLabel,
  children,
}: {
  model: ModelFile;
  /** 打开详情那一项叫什么(见 modelMenuGroups) */
  openLabel?: string;
  children: (openFrom: (anchor: HTMLElement) => void) => React.ReactElement;
}) {
  const t = useI18n();
  const actions = React.useContext(ModelActionsContext);
  const triggerRef = React.useRef<HTMLElement | null>(null);
  const opener = React.useRef<HTMLElement | null>(null);
  const [open, setOpen] = React.useState(false);
  const openFrom = React.useCallback((anchor: HTMLElement) => {
    opener.current = anchor;
    openMenuAt(triggerRef.current, anchor);
  }, []);
  //: 菜单只在开着时算条目(生成选项、标记都是开的那一刻的)
  const groups = open && actions ? modelMenuGroups(model, actions, t, openLabel) : [];
  return (
    <ContextMenu onOpenChange={setOpen}>
      <ContextMenuTrigger asChild ref={triggerRef as React.Ref<HTMLElement>}>
        {children(openFrom)}
      </ContextMenuTrigger>
      <ContextMenuContent
        aria-label={t("modelMenuLabel").replace("{name}", model.name)}
        onCloseAutoFocus={(event) => {
          //: ⋯ 或键盘打开的:焦点回到打开它的那个元素;右键打开的照右键菜单自己的规矩
          const back = opener.current;
          opener.current = null;
          if (back?.isConnected) {
            event.preventDefault();
            back.focus();
          }
        }}
      >
        {groups.map((group, index) => (
          <React.Fragment key={group[0]?.key ?? index}>
            {index > 0 && <ContextMenuSeparator />}
            {group.map((entry) => (
              <MenuEntry key={entry.key} entry={entry} />
            ))}
          </React.Fragment>
        ))}
      </ContextMenuContent>
    </ContextMenu>
  );
}
