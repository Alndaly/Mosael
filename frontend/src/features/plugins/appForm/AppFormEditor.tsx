import React from "react";
import { Info, TriangleAlert } from "lucide-react";

import type { PluginInstance, WorkflowApp } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { FormBuilder } from "@/features/plugins/appForm/FormBuilder";
import { PreviewPanel } from "@/features/plugins/appForm/PreviewPanel";
import { SourcePanel } from "@/features/plugins/appForm/SourcePanel";
import { addItem, removeItem, type AppDraft } from "@/features/plugins/workflowAppForm";
import { useElementWidth } from "@/lib/useElementWidth";
import { cn } from "@/lib/utils";

/** 比这窄就不摆三栏,改成「挑项 / 表单 / 预览」三个标签(工作台的「应用」面板 420px,弹窗在小窗口里也会这样)。 */
const NARROW_BELOW = 880;

type Zone = "source" | "form" | "preview";

/**
 * 应用表单编辑器的正文(ADR 0038 §2、§4),像搭一张表单:
 *
 * - **工作流里能填的**(SourcePanel):这张图全部能填的项,按节点分组、人话名字、现在的值,一颗「+」放进表单;
 * - **表单**(FormBuilder):挑进来的项是一张张卡片,拖动或 ↑ ↓ 排序、就地改名、设置里收窄可选值 / 当主提示词;空着时给
 *   「按推荐先挑一版」;下面一节「结果取自」;
 * - **预览**(PreviewPanel):用的人看到的样子,生成面板同一组控件,能填、不存。
 *
 * 宽的时候三栏各自滚;窄的时候(`layout="narrow"`,或者量出来比 {@link NARROW_BELOW} 窄)三个标签。工作流库的弹窗和工作台的
 * 「应用」面板用的是同一个它 —— 工作台里改的是画布上的节点(见 workbench/canvasMarks)。应用名和说明不在这里:弹窗把它们放在
 * 钉住的头上,面板放在最上面(见 {@link AppHead})。
 */
export function AppFormEditor({
  instance,
  data,
  draft,
  onChange,
  layout = "auto",
}: {
  instance: Pick<PluginInstance, "id">;
  data: WorkflowApp;
  draft: AppDraft;
  onChange: (next: AppDraft) => void;
  layout?: "auto" | "narrow";
}) {
  const t = useI18n();
  const [root, setRoot] = React.useState<HTMLDivElement | null>(null);
  const width = useElementWidth(root);
  const narrow = layout === "narrow" || (width > 0 && width < NARROW_BELOW);
  const [zone, setZone] = React.useState<Zone>("form");
  const source = (
    <SourcePanel
      data={data}
      draft={draft}
      onAdd={(item) => onChange(addItem(draft, item))}
      onRemove={(key) => onChange(removeItem(draft, key))}
    />
  );
  const form = <FormBuilder data={data} draft={draft} onChange={onChange} />;
  const preview = <PreviewPanel instanceId={instance.id} data={data} draft={draft} />;
  const notices = (
    <>
      {data.app?.status === "unsupported" && (
        <Notice>{t("workflowAppUnsupported").replace("{version}", data.app?.version || "?")}</Notice>
      )}
      {!data.editable && <Notice>{t("workflowAppNotEditable")}</Notice>}
    </>
  );

  if (narrow) {
    return (
      <div ref={setRoot} className="grid min-w-0 gap-3" data-app-layout="narrow">
        {notices}
        <Tabs value={zone} onValueChange={(next) => setZone(next as Zone)} className="grid min-w-0 gap-3">
          <TabsList className="w-full justify-between gap-2">
            <TabsTrigger value="source" className="flex-1 gap-1.5">
              {t("workflowAppTabSource")}
              <span className="tabular-nums text-muted-foreground">{(data.items ?? []).length}</span>
            </TabsTrigger>
            <TabsTrigger value="form" className="flex-1 gap-1.5">
              {t("workflowAppTabForm")}
              <span className="tabular-nums text-muted-foreground">{draft.items.length}</span>
            </TabsTrigger>
            <TabsTrigger value="preview" className="flex-1">{t("workflowAppTabPreview")}</TabsTrigger>
          </TabsList>
          <TabsContent value="source" className="mt-0 min-w-0">{source}</TabsContent>
          <TabsContent value="form" className="mt-0 min-w-0">{form}</TabsContent>
          <TabsContent value="preview" className="mt-0 min-w-0">{preview}</TabsContent>
        </Tabs>
      </div>
    );
  }
  return (
    <div ref={setRoot} className="flex min-h-0 min-w-0 flex-1 flex-col gap-3" data-app-layout="wide">
      {notices}
      {/* 三栏撑满弹窗给的高度(弹窗本身定高),各自滚 */}
      <div className="grid min-h-80 flex-1 grid-cols-[minmax(240px,300px)_minmax(0,1fr)_minmax(280px,360px)] grid-rows-[minmax(0,1fr)]">
        <Column className="border-r border-divider pr-4">{source}</Column>
        <Column className="px-5">{form}</Column>
        <Column className="border-l border-divider pl-4">{preview}</Column>
      </div>
    </div>
  );
}

/** 三栏里的一栏:各自滚。里面留一圈 1px,首尾那个控件的聚焦光圈不被裁掉。 */
function Column({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <div className={cn("min-h-0 min-w-0 overflow-y-auto overscroll-contain", className)}>
      <div className="grid min-w-0 p-1">{children}</div>
    </div>
  );
}

function Notice({ children }: { children: React.ReactNode }) {
  return (
    <div role="status" className="flex min-w-0 items-start gap-2 rounded-lg border border-warning/40 bg-panel p-3 text-ui-sm text-foreground">
      <TriangleAlert size={14} aria-hidden className="mt-0.5 shrink-0 text-warning" />
      <span className="min-w-0 break-words">{children}</span>
    </div>
  );
}

/**
 * 应用名和说明(就地改),下面一行小字说存在哪 —— 用大白话:「存进这张工作流文件里,复制、导出都跟着走」。弹窗把它钉在标题下面,
 * 工作台的面板放在最上面。按容器宽度决定两个框并排还是上下叠。
 */
export function AppHead({ draft, onChange, where }: { draft: AppDraft; onChange: (next: AppDraft) => void; where?: string }) {
  const t = useI18n();
  return (
    <div className="@container grid min-w-0 gap-2" data-app-head="">
      <div className="grid min-w-0 gap-3 @lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <label className="grid min-w-0 gap-1 text-ui-xs font-medium text-muted-foreground">
          {t("workflowAppName")}
          <Input value={draft.title} maxLength={120} placeholder={t("workflowAppNamePlaceholder")}
                 onChange={(event) => onChange({ ...draft, title: event.target.value })} />
        </label>
        <label className="grid min-w-0 gap-1 text-ui-xs font-medium text-muted-foreground">
          {t("workflowAppDescription")}
          <Input value={draft.description} maxLength={1000} placeholder={t("workflowAppDescriptionPlaceholder")}
                 onChange={(event) => onChange({ ...draft, description: event.target.value })} />
        </label>
      </div>
      {where && (
        <p className="m-0 flex min-w-0 items-start gap-1.5 text-ui-xs leading-relaxed text-muted-foreground">
          <Info size={12} aria-hidden className="mt-0.5 shrink-0" />
          <span className="min-w-0">{where}</span>
        </p>
      )}
    </div>
  );
}
