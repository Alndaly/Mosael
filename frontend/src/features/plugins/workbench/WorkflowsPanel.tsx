import React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, PackagePlus, Plus, RefreshCw, SearchX, Workflow } from "lucide-react";
import { toast } from "sonner";

import { getBundledWorkflows, getWorkflowLibrary, installBundledWorkflows, type BundledWorkflow, type WorkflowFile } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { EmptyState } from "@/components/layout/EmptyState";
import { LoadingState } from "@/components/layout/LoadingState";
import { IconButton } from "@/components/ui/icon-button";
import { Truncate } from "@/components/ui/truncate";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { SearchInput } from "@/components/ui/search-input";
import { Button } from "@/components/ui/button";
import { workbenchCall, type WorkbenchTarget } from "@/features/plugins/workbench/workbenchSession";

/**
 * 工作台右栏的「工作流」:当前连接上保存的工作流清单,点开就用同一个工作台打开,不必先回 Mosael 的插件页。
 * 一个入口同时给「新建」和刷新;列表沿用 `/workflow-library`,模型/节点缺失直接标出来。
 */
export function WorkflowsPanel({ target }: { target: WorkbenchTarget }) {
  const t = useI18n();
  const [query, setQuery] = React.useState("");
  const [opening, setOpening] = React.useState<string | null>(null);
  const [examplesOpen, setExamplesOpen] = React.useState(false);
  const library = useQuery({
    queryKey: ["workflow-library", target.instanceId, target.workspaceId],
    queryFn: () => getWorkflowLibrary(target.instanceId, target.workspaceId),
    retry: false,
  });
  const bundled = useQuery({
    queryKey: ["workflows-bundled", target.instanceId],
    queryFn: () => getBundledWorkflows(target.instanceId),
    retry: false,
  });
  const qc = useQueryClient();
  const [installing, setInstalling] = React.useState("");
  const install = async (flow: BundledWorkflow) => {
    setInstalling(flow.file);
    try {
      const result = await installBundledWorkflows(target.instanceId, [flow.file], bundled.data?.folder);
      await bundled.refetch();
      await qc.invalidateQueries({ queryKey: ["workflow-library", target.instanceId, target.workspaceId] });
      toast.success(t("workflowBundleInstallDone").replace("{n}", String(result.installed.length)));
    } catch (error) {
      toast.error(errorText(error));
    } finally {
      setInstalling("");
    }
  };
  const rows = (library.data?.workflows ?? []).filter((flow) => {
    const text = `${flow.label} ${flow.path}`.toLowerCase();
    return text.includes(query.trim().toLowerCase());
  });

  const open = async (flow?: WorkflowFile) => {
    const path = flow?.path ?? "";
    setOpening(path);
    try {
      const result = await workbenchCall({
        op: "openWorkflow",
        graph: flow ? null : { nodes: [] },
        name: "",
        path: flow ? flow.path : null,
        ops: [],
      });
      if (!result.ok) toast.error(result.error || t("workbenchOpenFailed"));
    } catch (error) {
      toast.error(errorText(error));
    } finally {
      setOpening(null);
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3" data-workflows-panel="">
      <div className="flex min-w-0 items-center gap-2">
        <SearchInput className="min-w-0 flex-1" value={query} placeholder={t("workbenchWorkflowsSearch")} onChange={(event) => setQuery(event.target.value)} />
        <IconButton size="icon" label={t("workbenchWorkflowsRefresh")} loading={library.isFetching} onClick={() => void library.refetch()}>
          <RefreshCw size={13} />
        </IconButton>
        <Button size="default" disabled={opening !== null} loading={opening === ""} onClick={() => void open()}>
          <Plus size={13} /> {t("workbenchWorkflowsNew")}
        </Button>
      </div>
      {bundled.data && bundled.data.workflows.length > 0 && (
        <section className="grid gap-2 border-t border-divider pt-3" data-bundled-workflows="">
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start"
            aria-expanded={examplesOpen}
            onClick={() => setExamplesOpen((open) => !open)}
          >
            <ChevronRight size={14} className={examplesOpen ? "rotate-90" : ""} />
            <PackagePlus size={14} /> {bundled.data.title || t("workflowBundleInstall")}
          </Button>
          {examplesOpen && (
            <ul role="list" aria-label={bundled.data.title} className="m-0 grid list-none gap-2 p-0">
              {bundled.data.workflows.map((flow) => (
                <li key={flow.file} className="flex min-w-0 items-center gap-2 rounded-lg border border-border bg-panel-subtle px-4 py-2">
                  <div className="grid min-w-0 flex-1 gap-0.5">
                    <Truncate className="min-w-0 text-ui-sm font-medium text-foreground">{flow.name}</Truncate>
                    {flow.description && (
                      <span className="min-w-0 text-ui-xs text-muted-foreground">
                        <InlineMarkdown text={flow.description} links={false} />
                      </span>
                    )}
                  </div>
                  <Button
                    size="default"
                    variant={flow.installed ? "outline" : "default"}
                    disabled={flow.installed || installing !== ""}
                    loading={installing === flow.file}
                    onClick={() => void install(flow)}
                  >
                    {flow.installed ? t("workflowBundleInstalled") : t("workflowBundleInstallOne")}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
      {library.isPending ? (
        <LoadingState label={t("workflowLibraryLoading")} className="flex-1" />
      ) : library.isError ? (
        <EmptyState size="compact" icon={<SearchX size={16} />} title={t("workflowLibraryErrorTitle")} body={errorText(library.error)} />
      ) : rows.length === 0 ? (
        <EmptyState size="compact" icon={<Workflow size={16} />} title={query ? t("workflowLibraryNoMatchTitle") : t("workflowLibraryEmpty")} />
      ) : (
        <>
          <h4 className="m-0 border-t border-divider pt-3 text-ui-sm font-semibold text-foreground">{t("workbenchWorkflows")}</h4>
        <ul role="list" aria-label={t("workbenchWorkflows")} className="m-0 grid list-none gap-2 p-0">
          {rows.map((flow) => {
            const missing = (flow.missing_nodes ?? []).length + (flow.missing_models ?? []).length;
            return (
              <li key={flow.path}>
                <Button
                  variant="outline"
                  className="w-full justify-start"
                  onClick={() => void open(flow)}
                  disabled={opening !== null}
                >
                  <span className="grid min-w-0 flex-1 gap-0.5 text-left">
                    <Truncate className="min-w-0 text-ui-sm font-medium text-foreground">{flow.label}</Truncate>
                    <Truncate className="min-w-0 text-ui-xs text-muted-foreground">{flow.path}</Truncate>
                  </span>
                  {missing > 0 && (
                    <span className="text-ui-xs text-warning">
                      {t("workbenchWorkflowsMissing").replace("{n}", String(missing))}
                    </span>
                  )}
                </Button>
              </li>
            );
          })}
        </ul>
        </>
      )}
    </div>
  );
}
