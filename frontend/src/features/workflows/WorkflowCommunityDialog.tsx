import React from "react";
import {
  AlertCircle,
  CheckCircle2,
  Circle,
  Clapperboard,
  Film,
  FolderInput,
  Languages,
  ListOrdered,
  Loader2,
  Megaphone,
  Palette,
  Plus,
  Scissors,
  SearchX,
  Shirt,
  Smartphone,
} from "lucide-react";

import { useQuery } from "@tanstack/react-query";

import {
  fetchWorkflowTemplateChecks,
  fetchWorkflowTemplates,
  type Workflow,
  type WorkflowGraph,
  type WorkflowTemplate,
  type WorkflowTemplateCheck,
  type WorkflowTemplateId,
  type WorkflowTemplateRequirement,
} from "@/api/client";
import { useI18n } from "@/app/preferences";
import {
  CatalogBadge,
  CatalogCard,
  CatalogDetail,
  CatalogDialog,
  CatalogFact,
  CatalogSection,
} from "@/components/app/CatalogDialog";
import { EmptyState } from "@/components/layout/EmptyState";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { toPlainText } from "@/components/markdown/inlineSyntax";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/** 每个官方模板的图标。**只有图标在前端** —— 名字、介绍、步骤、前置条件都由后端随模板目录
    发下来(`GET /api/workflows/templates`,见 domain/workflows/templates.TEMPLATE_CATALOG)。
    此前这些文案在前端一份、官网同步脚本里一份、后端图里一份,三处各写各的。 */
const TEMPLATE_ICONS: Record<string, typeof Film> = {
  full_video_generation: Film,
  transcript_video_cleanup: Scissors,
  translated_dub: Languages,
  highlight_shorts: Smartphone,
  product_on_model: Shirt,
  product_pitch_short: Megaphone,
  footage_montage: Clapperboard,
  fabric_lookbook: Palette,
};

type Filter = "all" | "added" | "ready";

/** 拉一次模板目录。文案已经是当前语言 —— 切语言时全部查询作废,会自己重来。 */
export function useWorkflowTemplates() {
  return useQuery({
    queryKey: ["workflow-templates"],
    queryFn: fetchWorkflowTemplates,
    staleTime: 5 * 60_000,
  });
}

/**
 * 一条前置条件此刻的样子。五种,不是两种:
 *
 * - met / missing:查过了,齐 / 不齐;
 * - optional:查过了、不齐,但缺了也能跑(旁白之类)—— 说「可选」,不报警;
 * - unknown:本地引擎还在后台探测,或者状态还没拉回来 —— **不拿未知冒充结论**;
 * - runtime:跑的时候才由用户给的素材,现在查不了,也不该查。
 */
type RequirementState = "met" | "missing" | "optional" | "unknown" | "runtime";

function stateOf(requirement: WorkflowTemplateRequirement, statuses: Map<string, WorkflowTemplateCheck["status"]> | null): RequirementState {
  if (!requirement.check) return "runtime";
  const status = statuses?.get(requirement.check);
  if (!status || status === "unknown") return "unknown";
  if (status === "met") return "met";
  return requirement.optional ? "optional" : "missing";
}

/** 这个模板现在能不能直接跑:缺几项必需的、还有几项没测出来。 */
function readinessOf(template: WorkflowTemplate, statuses: Map<string, WorkflowTemplateCheck["status"]> | null) {
  const states = (template.requirements ?? []).map((one) => stateOf(one, statuses));
  const missing = states.filter((one) => one === "missing").length;
  const unknown = states.filter((one) => one === "unknown").length;
  return { missing, unknown, ready: missing === 0 && unknown === 0 };
}

export function WorkflowCommunityDialog({
  open,
  workspaceId,
  workflows,
  installingId,
  onOpenChange,
  onInstall,
  focusTemplate,
}: {
  open: boolean;
  /** 前置条件按工作区查(克隆音色在工作区里)。 */
  workspaceId: string;
  workflows: Workflow[];
  installingId: WorkflowTemplateId | null;
  onOpenChange: (open: boolean) => void;
  onInstall: (templateId: WorkflowTemplateId) => void;
  /** 打开时直接看这个模板(官网「在 Mosael 中打开」)。 */
  focusTemplate?: string | null;
}) {
  const t = useI18n();
  const [query, setQuery] = React.useState("");
  const [filter, setFilter] = React.useState<Filter>("all");
  const [detailId, setDetailId] = React.useState<string | null>(null);
  const templates = useWorkflowTemplates();
  const rows = templates.data ?? [];
  //: 状态**每次打开都重新问**:他可能刚在设置里配好了模型。本地引擎的探测在后台跑,
  //: 还有没测出来的就隔一会儿再问一次,直到每一项都有结论。
  const checks = useQuery({
    queryKey: ["workflow-template-checks", workspaceId],
    queryFn: () => fetchWorkflowTemplateChecks(workspaceId),
    enabled: open && Boolean(workspaceId),
    staleTime: 0,
    refetchInterval: (current) => (current.state.data?.some((row) => row.status === "unknown") ? 1500 : false),
  });
  const statuses = React.useMemo(
    () => (checks.data ? new Map(checks.data.map((row) => [row.check, row.status])) : null),
    [checks.data],
  );

  React.useEffect(() => {
    if (!open) return;
    setQuery("");
    setFilter("all");
    setDetailId(focusTemplate ?? null);
  }, [open, focusTemplate]);

  const installedCounts = React.useMemo(() => {
    const counts = new Map<string, number>();
    for (const workflow of workflows) {
      const templateId = (workflow.graph as unknown as WorkflowGraph).meta?.template_id;
      if (templateId) counts.set(templateId, (counts.get(templateId) ?? 0) + 1);
    }
    return counts;
  }, [workflows]);

  const searched = React.useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) return rows;
    return rows.filter((template) =>
      [template.name, toPlainText(template.description), ...(template.stages ?? [])].join(" ").toLocaleLowerCase().includes(needle),
    );
  }, [query, rows]);
  const passes = (template: WorkflowTemplate, which: Filter) => {
    if (which === "added") return (installedCounts.get(template.id) ?? 0) > 0;
    if (which === "ready") return statuses !== null && readinessOf(template, statuses).ready;
    return true;
  };
  const shown = searched.filter((template) => passes(template, filter));
  const detail = rows.find((template) => template.id === detailId) ?? null;

  const placeholder = templates.isLoading ? (
    <div className="grid w-full grid-cols-[repeat(auto-fill,minmax(min(100%,264px),1fr))] content-start gap-3 self-start" aria-hidden>
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <Skeleton key={i} className="h-[184px] rounded-xl" />
      ))}
    </div>
  ) : (
    <EmptyState size="compact" icon={<SearchX size={15} />} title={t("wfCommunityNoResults")} />
  );

  return (
    <CatalogDialog<WorkflowTemplate, Filter>
      open={open}
      onOpenChange={onOpenChange}
      title={t("wfCommunityTitle")}
      description={t("wfCommunitySubtitle")}
      searchLabel={t("wfCommunitySearch")}
      query={query}
      onQueryChange={setQuery}
      filters={
        rows.length > 0
          ? {
              label: t("wfCommunityFilterLabel"),
              value: filter,
              onChange: setFilter,
              items: [
                { value: "all", label: t("catalogFilterAll"), count: searched.length },
                { value: "added", label: t("wfCommunityFilterAdded"), count: searched.filter((one) => passes(one, "added")).length },
                { value: "ready", label: t("wfCommunityFilterReady"), count: statuses ? searched.filter((one) => passes(one, "ready")).length : undefined },
              ],
            }
          : undefined
      }
      items={shown}
      itemKey={(template) => template.id}
      placeholder={placeholder}
      renderCard={(template, openDetail) => (
        <TemplateCard
          template={template}
          added={installedCounts.get(template.id) ?? 0}
          statuses={statuses}
          installing={installingId === template.id}
          onInstall={() => onInstall(template.id as WorkflowTemplateId)}
          onOpen={openDetail}
        />
      )}
      detail={detail}
      onDetailChange={setDetailId}
      backLabel={t("wfCommunityBack")}
      renderDetail={(template) => (
        <TemplateDetail
          template={template}
          added={installedCounts.get(template.id) ?? 0}
          statuses={statuses}
          installing={installingId === template.id}
          onInstall={() => onInstall(template.id as WorkflowTemplateId)}
        />
      )}
    />
  );
}

function TemplateIcon({ id }: { id: string }) {
  const Icon = TEMPLATE_ICONS[id] ?? Film;
  return <Icon />;
}

/** 「已添加」**写出字来**:此前是名字旁边一个没有说明的绿勾,读不出是"齐了"还是"加过了"。 */
function AddedBadge({ count }: { count: number }) {
  const t = useI18n();
  if (count <= 0) return null;
  return (
    <CatalogBadge tone="success" icon={<CheckCircle2 />}>
      {count > 1 ? t("wfCommunityInstalledN").replace("{n}", String(count)) : t("wfCommunityInstalled")}
    </CatalogBadge>
  );
}

function ReadinessFact({ template, statuses }: { template: WorkflowTemplate; statuses: Map<string, WorkflowTemplateCheck["status"]> | null }) {
  const t = useI18n();
  if (statuses === null) return null;
  const { missing, unknown } = readinessOf(template, statuses);
  if (missing > 0) {
    return (
      <CatalogFact icon={<AlertCircle />} tone="warning">
        {t("wfCommunityReqMissing").replace("{n}", String(missing))}
      </CatalogFact>
    );
  }
  if (unknown > 0) return <CatalogFact icon={<Loader2 className="motion-safe:animate-spin" />}>{t("wfCommunityReqChecking")}</CatalogFact>;
  return (
    <CatalogFact icon={<CheckCircle2 />} tone="success">
      {t("wfCommunityReqReady")}
    </CatalogFact>
  );
}

function TemplateCard({
  template,
  added,
  statuses,
  installing,
  onInstall,
  onOpen,
}: {
  template: WorkflowTemplate;
  added: number;
  statuses: Map<string, WorkflowTemplateCheck["status"]> | null;
  installing: boolean;
  onInstall: () => void;
  onOpen: () => void;
}) {
  const t = useI18n();
  const steps = (template.stages ?? []).length;
  return (
    <CatalogCard
      id={template.id}
      icon={<TemplateIcon id={template.id} />}
      title={template.name}
      meta={t("wfCommunityOfficial")}
      badge={<AddedBadge count={added} />}
      summary={toPlainText(template.description)}
      facts={
        <>
          <ReadinessFact template={template} statuses={statuses} />
          <CatalogFact icon={<ListOrdered />}>{t("wfCommunityStepCount").replace("{n}", String(steps))}</CatalogFact>
        </>
      }
      action={
        // 加过的还能再加一份(副本各自改),但它不再是这张卡的主要去处 —— 描边,不抢眼。
        <Button size="sm" variant={added > 0 ? "outline" : "default"} loading={installing} onClick={onInstall}>
          <Plus />
          {t("wfCommunityAddShort")}
        </Button>
      }
      onOpen={onOpen}
    />
  );
}

const REQUIREMENT_LOOK: Record<RequirementState, { icon: typeof Circle; tone: string; label: Parameters<ReturnType<typeof useI18n>>[0] }> = {
  met: { icon: CheckCircle2, tone: "text-success", label: "wfReqStatusMet" },
  missing: { icon: AlertCircle, tone: "text-warning", label: "wfReqStatusMissing" },
  optional: { icon: Circle, tone: "text-muted-foreground", label: "wfReqStatusOptional" },
  unknown: { icon: Loader2, tone: "text-muted-foreground", label: "wfReqStatusUnknown" },
  runtime: { icon: FolderInput, tone: "text-muted-foreground", label: "wfReqStatusRuntime" },
};

/**
 * 「运行前需要」,**每一条带着它此刻的状态**。此前每一条都配同一个勾 —— 勾在说"齐了",
 * 其实只是"这是一条";用户照着它点了添加,跑到第一个节点才知道没配对话模型。
 */
function RequirementList({ template, statuses }: { template: WorkflowTemplate; statuses: Map<string, WorkflowTemplateCheck["status"]> | null }) {
  const t = useI18n();
  return (
    <ul className="m-0 grid list-none gap-2.5 p-0">
      {(template.requirements ?? []).map((requirement) => {
        const state = stateOf(requirement, statuses);
        const look = REQUIREMENT_LOOK[state];
        const Icon = look.icon;
        return (
          <li key={requirement.text} data-requirement-state={state} className="grid grid-cols-[16px_minmax(0,1fr)] gap-2.5">
            <Icon size={15} aria-hidden className={cn("mt-0.5", look.tone, state === "unknown" && "motion-safe:animate-spin")} />
            <span className="grid min-w-0 gap-0.5">
              <span className="text-ui-sm leading-snug text-foreground">{requirement.text}</span>
              <span className={cn("text-ui-xs", state === "missing" ? "text-warning" : "text-muted-foreground")}>{t(look.label)}</span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function TemplateDetail({
  template,
  added,
  statuses,
  installing,
  onInstall,
}: {
  template: WorkflowTemplate;
  added: number;
  statuses: Map<string, WorkflowTemplateCheck["status"]> | null;
  installing: boolean;
  onInstall: () => void;
}) {
  const t = useI18n();
  const stages = template.stages ?? [];
  return (
    <CatalogDetail
      icon={<TemplateIcon id={template.id} />}
      title={template.name}
      badges={
        <>
          <CatalogBadge tone="primary">{t("wfCommunityOfficial")}</CatalogBadge>
          {added > 0 && (
            <CatalogBadge tone="success" icon={<CheckCircle2 />}>
              {t("wfCommunityInstalledCount").replace("{n}", String(added))}
            </CatalogBadge>
          )}
        </>
      }
      meta={t("wfCommunityStepCount").replace("{n}", String(stages.length))}
      //: 主操作**贴着它作用的那一条**。此前它在底栏,和正在看的模板隔着整个弹窗。
      actions={
        <Button loading={installing} onClick={onInstall}>
          <Plus />
          {added > 0 ? t("wfCommunityAddAgain") : t("wfCommunityAdd")}
        </Button>
      }
      aside={
        <CatalogSection title={t("wfCommunityRequirements")}>
          <RequirementList template={template} statuses={statuses} />
          <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">{t("wfReqLegend")}</p>
        </CatalogSection>
      }
    >
      <CatalogSection title={t("wfCommunityAbout")}>
        <p className="m-0 text-ui-sm leading-relaxed text-foreground">
          <InlineMarkdown text={template.description} />
        </p>
      </CatalogSection>
      <CatalogSection title={t("wfCommunityWorkflowIncludes")} count={stages.length}>
        <ol className="m-0 grid list-none gap-0 p-0">
          {stages.map((stage, index) => (
            <li key={stage} className="grid grid-cols-[24px_minmax(0,1fr)] gap-3">
              <span className="relative grid size-6 place-items-center rounded-full border border-primary/30 bg-[color-mix(in_srgb,var(--primary)_8%,transparent)] text-ui-xs font-semibold text-primary">
                {index + 1}
                {index < stages.length - 1 && <span className="absolute left-1/2 top-6 h-5 w-px -translate-x-1/2 bg-border" />}
              </span>
              <span className="pb-5 pt-0.5 text-ui-sm text-foreground">{stage}</span>
            </li>
          ))}
        </ol>
      </CatalogSection>
    </CatalogDetail>
  );
}
