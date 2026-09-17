import React from "react";
import { Bot, CheckCircle2, Film, Languages, Search, SearchX, Scissors, Video } from "lucide-react";

import type { Workflow, WorkflowGraph, WorkflowTemplateId } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface TemplateDefinition {
  id: WorkflowTemplateId;
  title: MessageKey;
  description: MessageKey;
  stages: MessageKey[];
  requirements: MessageKey[];
  icon: typeof Film;
}

export function workflowTemplateText(templateId: WorkflowTemplateId): { title: MessageKey; description: MessageKey } {
  const template = TEMPLATES.find((one) => one.id === templateId) ?? TEMPLATES[0];
  return { title: template.title, description: template.description };
}

const TEMPLATES: TemplateDefinition[] = [
  {
    id: "full_video_generation",
    title: "wfFullVideoTemplateName",
    description: "wfFullVideoTemplateDescription",
    stages: [
      "wfCommunityStageBrief",
      "wfCommunityStageNarrativeVisual",
      "wfCommunityStageStoryboard",
      "wfCommunityStageGenerateAssemble",
      "wfCommunityStageExport",
    ],
    requirements: ["wfCommunityRequirementChat", "wfCommunityRequirementVideo"],
    icon: Film,
  },
  {
    id: "transcript_video_cleanup",
    title: "wfTranscriptCleanupTemplateName",
    description: "wfTranscriptCleanupTemplateDescription",
    stages: [
      "wfCommunityStagePickVideo",
      "wfCommunityStageDenoise",
      "wfCommunityStageTranscript",
      "wfCommunityStageCleanupPlan",
      "wfCommunityStageRippleCut",
      "wfCommunityStageExport",
    ],
    requirements: ["wfCommunityRequirementChat"],
    icon: Scissors,
  },
  {
    id: "translated_dub",
    title: "wfTranslatedDubTemplateName",
    description: "wfTranslatedDubTemplateDescription",
    stages: [
      "wfCommunityStageDubProject",
      "wfCommunityStageTranscript",
      "wfCommunityStageTranslateLines",
      "wfCommunityStageSubtitles",
      "wfCommunityStageDub",
      "wfCommunityStageExport",
    ],
    // 翻译走对话模型(免费的 Google 接口按出口 IP 封禁,官方模板不押在它上面),外加一把嗓子。
    requirements: ["wfCommunityRequirementChat", "wfCommunityRequirementVoice"],
    icon: Languages,
  },
];

export function WorkflowCommunityDialog({
  open,
  workflows,
  installingId,
  onOpenChange,
  onInstall,
}: {
  open: boolean;
  workflows: Workflow[];
  installingId: WorkflowTemplateId | null;
  onOpenChange: (open: boolean) => void;
  onInstall: (templateId: WorkflowTemplateId) => void;
}) {
  const t = useI18n();
  const [query, setQuery] = React.useState("");
  const [selectedId, setSelectedId] = React.useState<WorkflowTemplateId>(TEMPLATES[0].id);

  React.useEffect(() => {
    if (!open) return;
    setQuery("");
  }, [open]);

  const installedCounts = React.useMemo(() => {
    const counts = new Map<WorkflowTemplateId, number>();
    for (const workflow of workflows) {
      const templateId = (workflow.graph as unknown as WorkflowGraph).meta?.template_id;
      if (templateId) counts.set(templateId, (counts.get(templateId) ?? 0) + 1);
    }
    return counts;
  }, [workflows]);

  const filtered = React.useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return TEMPLATES.filter((template) => {
      if (!needle) return true;
      return `${t(template.title)} ${t(template.description)}`.toLocaleLowerCase().includes(needle);
    });
  }, [query, t]);

  React.useEffect(() => {
    if (filtered.length > 0 && !filtered.some((template) => template.id === selectedId)) {
      setSelectedId(filtered[0].id);
    }
  }, [filtered, selectedId]);

  const selected = filtered.find((template) => template.id === selectedId) ?? filtered[0] ?? null;
  const installed = selected ? installedCounts.get(selected.id) ?? 0 : 0;

  return (
    <ModalShell
      open={open}
      onOpenChange={onOpenChange}
      title={t("wfCommunityTitle")}
      className="w-[min(920px,calc(100vw-24px))] max-w-none"
      // 正文和头部、底部用**同一套左右边距**(ModalShell 的 px-6)。此前这里是 p-0,左侧列表只靠
      // 自己的 p-3 缩进,于是列表比标题和搜索框往外凸出一截。
      bodyClassName="px-6 py-5"
      header={
        <div className="grid gap-2.5">
          <p className="m-0 text-ui-xs font-normal leading-relaxed text-muted-foreground">
            {t("wfCommunitySubtitle")}
          </p>
          <label className="relative min-w-0">
            <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" size={14} />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("wfCommunitySearch")}
              aria-label={t("wfCommunitySearch")}
              className="pl-9"
            />
          </label>
        </div>
      }
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            disabled={!selected}
            loading={selected !== null && installingId === selected.id}
            onClick={() => selected && onInstall(selected.id)}
          >
            {installed > 0 ? t("wfCommunityAddAgain") : t("wfCommunityAdd")}
          </Button>
        </>
      }
    >
      {filtered.length === 0 ? (
        <div className="grid min-h-[430px] place-items-center py-12 text-center">
          <div className="grid justify-items-center gap-2 text-muted-foreground">
            <span className="grid size-10 place-items-center rounded-full bg-secondary/60">
              <SearchX size={18} />
            </span>
            <p className="m-0 text-ui-sm">{t("wfCommunityNoResults")}</p>
          </div>
        </div>
      ) : (
        <div className="grid min-h-[430px] md:grid-cols-[310px_minmax(0,1fr)]">
          {/* 两列之间一条分隔线,线两侧的留白相等(pr-5 / pl-5);外侧不再加内边距 ——
              外侧的边距由正文统一给。 */}
          <div
            className="border-b border-border/60 pb-4 md:border-b-0 md:border-r md:pb-0 md:pr-5"
            role="listbox"
            aria-label={t("wfCommunityTitle")}
          >
            <div className="grid gap-2">
              {filtered.map((template) => {
                const Icon = template.icon;
                const count = installedCounts.get(template.id) ?? 0;
                return (
                  <button
                    key={template.id}
                    type="button"
                    role="option"
                    aria-selected={selected?.id === template.id}
                    className={cn(
                      "grid w-full grid-cols-[36px_minmax(0,1fr)] gap-2.5 rounded-lg border p-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                      selected?.id === template.id
                        ? "border-primary/50 bg-[color-mix(in_srgb,var(--primary)_8%,transparent)]"
                        : "border-border bg-panel hover:border-border-strong hover:bg-secondary/40",
                    )}
                    onClick={() => setSelectedId(template.id)}
                  >
                    <span className="grid size-9 place-items-center rounded-md bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] text-primary">
                      <Icon size={17} />
                    </span>
                    <span className="min-w-0">
                      <span className="flex items-center gap-1.5">
                        <strong className="truncate text-ui-sm text-foreground">{t(template.title)}</strong>
                        {count > 0 && <CheckCircle2 className="shrink-0 text-success" size={13} aria-label={t("wfCommunityInstalled")} />}
                      </span>
                      {/* 不能再加 `block`:line-clamp 靠的是 -webkit-box,block 会把它覆盖掉,
                          说明就整段铺开、把卡片撑高(真出过)。 */}
                      <span className="mt-1 line-clamp-2 text-ui-xs leading-relaxed text-muted-foreground">
                        {t(template.description)}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="min-w-0 pt-4 md:pl-5 md:pt-0">
            {selected && (
              <div className="grid gap-5">
                <div className="grid gap-2">
                  <div className="flex flex-wrap items-center gap-2 text-ui-xs">
                    <span className="rounded-full bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] px-2 py-1 font-medium text-primary">
                      {t("wfCommunityOfficial")}
                    </span>
                    {installed > 0 && (
                      <span className="inline-flex items-center gap-1 text-muted-foreground">
                        <CheckCircle2 size={13} className="text-success" />
                        {t("wfCommunityInstalledCount").replace("{n}", String(installed))}
                      </span>
                    )}
                  </div>
                  <h3 className="m-0 text-lg font-semibold text-foreground">{t(selected.title)}</h3>
                  <p className="m-0 text-ui-sm leading-relaxed text-muted-foreground">{t(selected.description)}</p>
                </div>

                <section className="grid gap-2.5">
                  <h4 className="m-0 text-ui-sm font-semibold text-foreground">{t("wfCommunityWorkflowIncludes")}</h4>
                  <ol className="m-0 grid list-none gap-0 p-0">
                    {selected.stages.map((stage, index) => (
                      <li key={stage} className="grid grid-cols-[24px_minmax(0,1fr)] gap-2">
                        <span className="relative grid size-6 place-items-center rounded-full border border-primary/30 bg-[color-mix(in_srgb,var(--primary)_8%,transparent)] text-ui-xs font-semibold text-primary">
                          {index + 1}
                          {index < selected.stages.length - 1 && <span className="absolute left-1/2 top-6 h-5 w-px -translate-x-1/2 bg-border" />}
                        </span>
                        <span className="pb-4 pt-0.5 text-ui-sm text-foreground">{t(stage)}</span>
                      </li>
                    ))}
                  </ol>
                </section>

                <section className="grid gap-2.5">
                  <h4 className="m-0 text-ui-sm font-semibold text-foreground">{t("wfCommunityRequirements")}</h4>
                  <div className="flex flex-wrap gap-2">
                    {selected.requirements.map((requirement) => (
                      <span key={requirement} className="inline-flex items-center gap-1.5 rounded-full border border-border bg-secondary/50 px-2.5 py-1 text-ui-xs text-foreground">
                        {requirement === "wfCommunityRequirementVideo" ? <Video size={13} /> : <Bot size={13} />}
                        {t(requirement)}
                      </span>
                    ))}
                  </div>
                </section>
              </div>
            )}
          </div>
        </div>
      )}
    </ModalShell>
  );
}
