/**
 * 「助手」页签认得的几种工具结果(ADR 0042 §5),画在对话里那一步的下面、不跟着折叠(见 features/agent/pageViews):
 *
 * - `comfy_check` 的诊断:一条一条,每条带「定位」(在画布上选中那个节点)和「照这个改」(替用户说一句,让智能体把这一条转成
 *   一次 comfy_canvas_edit 的提议 —— 改不改仍是用户在确认卡上点「应用」);
 * - `comfy_canvas_edit` 应用之后:改了几处、修好了几个、多出来的提醒(也能定位);
 * - `comfy_canvas_new`:在新标签页里开了哪一张、没存盘、还缺几个模型合计多大,带「去下载」(换到「缺失项」那一页)。
 *
 * 认不出形状的回 null,工具行照通用的画。要做的事(定位、照这个改、去下载)由页签经 WorkbenchAssistantContext 给。
 */
import React from "react";
import { CircleAlert, Crosshair, Download, FilePlus2, Info, TriangleAlert, Wrench } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Truncate } from "@/components/ui/truncate";
import { WorkbenchAssistantContext, type AssistantFinding } from "@/features/plugins/workbench/assistantActions";
import { formatBytes } from "@/lib/bytes";
import { cn } from "@/lib/utils";

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);

/** 问题单里一条的形状对不对:要有严重程度、种类、原因。 */
function findingsOf(value: unknown): AssistantFinding[] | null {
  if (!Array.isArray(value)) return null;
  const found = value.filter((one): one is AssistantFinding =>
    isRecord(one) && typeof one.severity === "string" && typeof one.kind === "string" && typeof one.cause === "string");
  return found.length === value.length ? found.map((one) => ({ ...one, ref: typeof one.ref === "string" ? one.ref : "" })) : null;
}

function counted(value: unknown): { error: number; warning: number } {
  const counts = isRecord(value) ? value : {};
  return { error: Number(counts.error) || 0, warning: Number(counts.warning) || 0 };
}

/** 这一次的结果画成什么(见模块说明)。不认得回 null。 */
export function assistantToolResult(tool: string, data: unknown): React.ReactNode {
  if (!isRecord(data)) return null;
  if (tool === "comfy_check") {
    const findings = findingsOf(data.findings);
    //: 零发现不画任何结果行:工具行(✓ comfy_check · 0.6s)已经证明检查跑过了,
    //: 「没查出问题」智能体自己会回答 —— 再单独来一行,是把工具的回包当成内容播。
    if (findings && findings.length === 0) return null;
    return findings ? <FindingsCard findings={findings} counts={counted(data.counts)} /> : null;
  }
  if (tool === "comfy_canvas_edit" && typeof data.applied === "number") {
    return <AppliedCard applied={data.applied} fixed={findingsOf(data.fixed) ?? []} introduced={findingsOf(data.introduced) ?? []} />;
  }
  if (tool === "comfy_canvas_new" && isRecord(data.opened)) {
    return <NewTabCard result={data} />;
  }
  return null;
}

const CARD = "grid min-w-0 gap-1.5 rounded-md border border-border bg-panel p-2 text-ui-xs";

function FindingsCard({ findings, counts }: { findings: AssistantFinding[]; counts: { error: number; warning: number } }) {
  const t = useI18n();
  return (
    <section className={CARD} aria-label={t("workbenchFindingsTitle")} data-comfy-findings="">
      <header className="flex min-w-0 items-center gap-1.5 text-muted-foreground">
        <Wrench size={12} aria-hidden />
        <span>{t("workbenchFindingsSummary").replace("{errors}", String(counts.error)).replace("{warnings}", String(counts.warning))}</span>
      </header>
      {findings.length > 0 && (
        <ul className="m-0 grid max-h-[320px] min-w-0 list-none gap-1 overflow-y-auto p-0">
          {findings.map((one, index) => <FindingRow key={`${one.ref}:${one.kind}:${one.input ?? ""}:${index}`} finding={one} />)}
        </ul>
      )}
    </section>
  );
}

/** 一条问题:严重程度、哪个节点、原因、改法;「定位」和「照这个改」。指不到节点的(整张图的报错)只有「照这个改」。 */
export function FindingRow({ finding, canFix = true }: { finding: AssistantFinding; canFix?: boolean }) {
  const t = useI18n();
  const actions = React.useContext(WorkbenchAssistantContext);
  const [note, setNote] = React.useState("");
  const error = finding.severity === "error";
  const Icon = error ? CircleAlert : finding.severity === "warning" ? TriangleAlert : Info;
  const where = finding.ref ? `#${finding.ref}` : "";
  const name = finding.title || finding.type || "";
  return (
    <li className="grid min-w-0 gap-1 rounded-md px-1 py-1 hover:bg-secondary" data-finding={finding.ref}>
      <span className="flex min-w-0 items-start gap-1.5">
        <Icon size={13} className={cn("mt-[2px] shrink-0", error ? "text-destructive" : "text-warning")}
              aria-label={t(error ? "workbenchSeverityError" : "workbenchSeverityWarning")} />
        <span className="grid min-w-0 flex-1 gap-0.5">
          <span className="min-w-0 text-foreground [overflow-wrap:anywhere]">
            {where && <span className="mr-1 font-mono">{where}</span>}
            {name && <span className="mr-1 text-muted-foreground">{name}</span>}
            {finding.cause}
          </span>
          {finding.fix && <span className="text-muted-foreground [overflow-wrap:anywhere]">{finding.fix}</span>}
        </span>
      </span>
      {actions && (
        <span className="flex flex-wrap items-center gap-1 pl-5">
          {finding.ref && (
            <Button variant="ghost" size="xs" data-locate={finding.ref}
                    aria-label={t("workbenchLocateLabel").replace("{name}", where)}
                    onClick={() => {
                      setNote("");
                      void actions.locate(finding.ref).then(setNote);
                    }}>
              <Crosshair size={12} />
              {t("workbenchLocate")}
            </Button>
          )}
          {canFix && (
            <Button variant="ghost" size="xs" data-fix={finding.ref}
                    aria-label={t("workbenchFixThisLabel").replace("{what}", `${where} ${finding.cause}`.trim())}
                    onClick={() => actions.fix(finding)}>
              <Wrench size={12} />
              {t("workbenchFixThis")}
            </Button>
          )}
          {note && <span role="status" className="text-ui-2xs text-destructive">{note}</span>}
        </span>
      )}
    </li>
  );
}

function AppliedCard({ applied, fixed, introduced }: { applied: number; fixed: AssistantFinding[]; introduced: AssistantFinding[] }) {
  const t = useI18n();
  return (
    <section className={CARD} aria-label={t("workbenchAppliedTitle")} data-comfy-applied="">
      <span className="text-foreground">{t("workbenchAppliedSummary").replace("{n}", String(applied))}</span>
      {fixed.length > 0 && <span className="text-success">{t("workbenchAppliedFixed").replace("{n}", String(fixed.length))}</span>}
      {introduced.length > 0 && (
        <>
          <span className="text-muted-foreground">{t("workbenchAppliedIntroduced").replace("{n}", String(introduced.length))}</span>
          <ul className="m-0 grid min-w-0 list-none gap-1 p-0">
            {introduced.map((one, index) => <FindingRow key={`${one.ref}:${one.kind}:${index}`} finding={one} />)}
          </ul>
        </>
      )}
    </section>
  );
}

interface TemplateModel {
  name: string;
  folder?: string;
  status: string;
  size?: number;
}

function NewTabCard({ result }: { result: Record<string, unknown> }) {
  const t = useI18n();
  const actions = React.useContext(WorkbenchAssistantContext);
  const opened = isRecord(result.opened) ? result.opened : {};
  const template = isRecord(result.template) ? result.template : null;
  const missing = (Array.isArray(template?.models) ? template.models : [])
    .filter((one): one is TemplateModel => isRecord(one) && one.status === "missing" && typeof one.name === "string");
  const size = Number(template?.missing_size) || 0;
  const check = isRecord(result.check) ? result.check : {};
  const counts = counted(check.counts);
  const temporary = opened.temporary === true;
  return (
    <section className={CARD} aria-label={t("workbenchNewTabTitle")} data-comfy-new-tab="">
      <span className="flex min-w-0 items-start gap-1.5 text-foreground">
        <FilePlus2 size={13} className="mt-[2px] shrink-0 text-muted-foreground" aria-hidden />
        <span className="min-w-0 [overflow-wrap:anywhere]">
          {t(temporary ? "workbenchNewTabOpened" : "workbenchNewTabOpenedSaved").replace("{name}", String(opened.name ?? ""))}
        </span>
      </span>
      {missing.length > 0 && (
        <div className="grid min-w-0 gap-1">
          <span className="flex min-w-0 items-center gap-1.5">
            <span className="min-w-0 flex-1 text-muted-foreground">
              {(size ? t("workbenchNewTabMissing").replace("{size}", formatBytes(size)) : t("workbenchNewTabMissingNoSize"))
                .replace("{n}", String(missing.length))}
            </span>
            {actions && (
              <Button size="xs" className="shrink-0" onClick={actions.showMissing}>
                <Download size={12} />
                {t("workbenchGoDownload")}
              </Button>
            )}
          </span>
          <ul className="m-0 grid min-w-0 list-none gap-0.5 p-0 text-muted-foreground">
            {missing.map((one) => (
              <li key={one.name} className="flex min-w-0 items-center gap-1.5">
                <Truncate className="min-w-0 flex-1 font-mono">{one.name}</Truncate>
                {one.folder && <span className="shrink-0">{one.folder}</span>}
                {one.size ? <span className="shrink-0 tabular-nums">{formatBytes(one.size)}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      )}
      {(counts.error > 0 || counts.warning > 0) && (
        <span className="text-muted-foreground">
          {t("workbenchFindingsSummary").replace("{errors}", String(counts.error)).replace("{warnings}", String(counts.warning))}
        </span>
      )}
    </section>
  );
}
