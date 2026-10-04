import React from "react";

import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { conflictOf, validWorkflowPath, workflowPathFrom } from "@/features/plugins/workflowLibraryView";

/**
 * 往那台服务器上写一个工作流路径(复制、改名、恢复、导入):填的时候当场说不合格,提交撞了名(409)说清楚并给一个建议名
 * —— 从不提供覆盖。`.json` 不用自己写。
 */
export function useWorkflowPath(initial: string, onSubmit: (path: string) => Promise<void>, onDone: () => void) {
  const [value, setValue] = React.useState(initial);
  const [pending, setPending] = React.useState(false);
  const [clash, setClash] = React.useState<{ path: string; suggestion: string } | null>(null);
  const [error, setError] = React.useState("");
  const path = workflowPathFrom(value);
  const bad = !validWorkflowPath(path);
  const submit = async () => {
    if (bad || pending) return;
    setPending(true);
    setClash(null);
    setError("");
    try {
      await onSubmit(path);
      onDone();
    } catch (failure) {
      const conflict = conflictOf(failure);
      if (conflict) setClash({ path, suggestion: conflict.suggestion });
      else setError(errorText(failure));
    } finally {
      setPending(false);
    }
  };
  const change = (next: string) => {
    setValue(next);
    setClash(null);
  };
  return { value, change, pending, clash, error, bad, submit };
}

export function WorkflowPathField({ state }: { state: ReturnType<typeof useWorkflowPath> }) {
  const t = useI18n();
  const inputId = React.useId();
  return (
    <>
      <div className="grid gap-1.5">
        <label htmlFor={inputId} className="text-ui-xs font-medium text-muted-foreground">{t("workflowPathLabel")}</label>
        <Input
          id={inputId}
          aria-label={t("workflowPathLabel")}
          value={state.value}
          onChange={(event) => state.change(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.nativeEvent.isComposing) void state.submit();
          }}
        />
        {state.bad && state.value.trim() ? (
          <p className="m-0 text-ui-xs text-destructive">{t("workflowPathBad")}</p>
        ) : (
          <p className="m-0 text-ui-xs text-muted-foreground">{t("workflowPathHelp")}</p>
        )}
      </div>
      {state.clash && (
        <div role="alert" className="grid gap-2 rounded-lg border border-warning/40 bg-panel p-3 text-ui-sm text-foreground">
          <span>{t("workflowExists").replace("{path}", state.clash.path)}</span>
          {state.clash.suggestion && (
            <span>
              <Button variant="outline" size="sm" onClick={() => state.change(state.clash!.suggestion)}>
                {t("workflowUseSuggestion").replace("{name}", state.clash.suggestion)}
              </Button>
            </span>
          )}
        </div>
      )}
      {state.error && <p role="alert" className="m-0 text-ui-sm text-destructive">{state.error}</p>}
    </>
  );
}
