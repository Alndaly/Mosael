import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus, RefreshCw, SearchX, Workflow } from "lucide-react";
import { toast } from "sonner";

import { getWorkflowLibrary, type WorkflowFile } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { EmptyState } from "@/components/layout/EmptyState";
import { LoadingState } from "@/components/layout/LoadingState";
import { IconButton } from "@/components/ui/icon-button";
import { SearchInput } from "@/components/ui/search-input";
import { Button } from "@/components/ui/button";
import { openWorkbench, type WorkbenchTarget } from "@/features/plugins/workbench/workbenchSession";

/**
 * 工作台右栏的「工作流」:当前连接上保存的工作流清单,点开就用同一个工作台打开,不必先回 Mosael 的插件页。
 * 一个入口同时给「新建」和刷新;列表沿用 `/workflow-library`,模型/节点缺失直接标出来。
 */
export function WorkflowsPanel({ target }: { target: WorkbenchTarget }) {
  const t = useI18n();
  const [query, setQuery] = React.useState("");
  const [opening, setOpening] = React.useState<string | null>(null);
  const library = useQuery({
    queryKey: ["workflows-panel", target.instanceId, target.workspaceId],
    queryFn: () => getWorkflowLibrary(target.instanceId, target.workspaceId),
    retry: false,
  });
  const rows = (library.data?.workflows ?? []).filter((flow) => {
    const text = `${flow.label} ${flow.path}`.toLowerCase();
    return text.includes(query.trim().toLowerCase());
  });

  const open = async (flow?: WorkflowFile) => {
    const path = flow?.path ?? "";
    setOpening(path);
    try {
      const result = await openWorkbench(target, flow ? { path } : { fresh: true });
      if (!result.ok) toast.error(result.error || t("workbenchOpenFailed"));
    } catch (error) {
      toast.error(errorText(error));
    } finally {
      setOpening(null);
    }
  };

  return (
    <div className="grid min-w-0 gap-3" data-workflows-panel="">
      <div className="flex min-w-0 items-center gap-2">
        <SearchInput className="min-w-0 flex-1" value={query} placeholder={t("workbenchWorkflowsSearch")} onChange={(event) => setQuery(event.target.value)} />
        <IconButton size="icon-sm" label={t("workbenchWorkflowsRefresh")} loading={library.isFetching} onClick={() => void library.refetch()}>
          <RefreshCw size={13} />
        </IconButton>
        <Button size="sm" disabled={opening !== null} loading={opening === ""} onClick={() => void open()}>
          <Plus size={13} /> {t("workbenchWorkflowsNew")}
        </Button>
      </div>
      {library.isPending ? (
        <LoadingState label={t("workflowLibraryLoading")} className="h-40" />
      ) : library.isError ? (
        <EmptyState size="compact" icon={<SearchX size={16} />} title={t("workflowLibraryErrorTitle")} body={errorText(library.error)} />
      ) : rows.length === 0 ? (
        <EmptyState size="compact" icon={<Workflow size={16} />} title={query ? t("workflowLibraryNoMatchTitle") : t("workflowLibraryEmpty")} />
      ) : (
        <ul role="list" aria-label={t("workbenchWorkflows")} className="m-0 grid list-none gap-1 p-0">
          {rows.map((flow) => {
            const missing = (flow.missing_nodes ?? []).length + (flow.missing_models ?? []).length;
            return (
              <li key={flow.path}>
                <button
                  type="button"
                  className="grid w-full min-w-0 cursor-pointer gap-0.5 rounded-lg border border-border bg-panel-subtle px-3 py-2 text-left hover:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={() => void open(flow)}
                  disabled={opening !== null}
                >
                  <span className="min-w-0 truncate text-ui-sm font-medium text-foreground">{flow.label}</span>
                  <span className="min-w-0 truncate text-ui-xs text-muted-foreground">{flow.path}</span>
                  {missing > 0 && (
                    <span className="text-ui-xs text-warning">
                      {t("workbenchWorkflowsMissing").replace("{n}", String(missing))}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
