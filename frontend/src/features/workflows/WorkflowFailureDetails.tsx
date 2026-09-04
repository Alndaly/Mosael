import React from "react";

import { useI18n } from "@/app/preferences";

type Details = Record<string, unknown>;

/** 工作流失败现场的统一呈现：历史面板、任务详情和节点检查器共用同一份数据语义。 */
export function WorkflowFailureDetails({ details }: { details: Details | undefined }) {
  const t = useI18n();
  if (!details || Object.keys(details).length === 0) return null;

  const rawResponse = typeof details.raw_response === "string" ? details.raw_response : null;
  const parseError =
    typeof details.parse_error === "string"
      ? details.parse_error
      : typeof details.schema_error === "string"
        ? details.schema_error
        : null;
  const model = typeof details.model === "string" ? details.model : null;
  const responseFormat = typeof details.response_format === "string" ? details.response_format : null;
  const recognized = rawResponse !== null || parseError !== null || model !== null || responseFormat !== null;

  return (
    <div className="grid min-w-0 gap-2 border-l-2 border-destructive/35 pl-2.5 text-ui-xs">
      {(model || responseFormat) && (
        <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 gap-y-0.5 text-muted-foreground">
          {model && (
            <>
              <dt>{t("jobDetailModel")}</dt>
              <dd className="m-0 min-w-0 break-words font-mono text-foreground">{model}</dd>
            </>
          )}
          {responseFormat && (
            <>
              <dt>{t("jobDetailResponseFormat")}</dt>
              <dd className="m-0 min-w-0 break-words font-mono text-foreground">{responseFormat}</dd>
            </>
          )}
        </dl>
      )}
      {rawResponse !== null && (
        <div className="grid min-w-0 gap-1">
          <span className="font-semibold text-muted-foreground">{t("jobDetailRawResponse")}</span>
          <pre className="m-0 max-h-64 min-w-0 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted/60 p-2 font-mono text-ui-2xs leading-[1.55] text-foreground">
            {rawResponse || t("jobDetailEmptyResponse")}
          </pre>
        </div>
      )}
      {parseError && (
        <div className="grid min-w-0 gap-1">
          <span className="font-semibold text-muted-foreground">{t("jobDetailParseError")}</span>
          <pre className="m-0 min-w-0 whitespace-pre-wrap break-words font-mono text-ui-2xs leading-[1.5] text-destructive">
            {parseError}
          </pre>
        </div>
      )}
      {!recognized && (
        <pre className="m-0 max-h-64 min-w-0 overflow-auto whitespace-pre-wrap break-words font-mono text-ui-2xs text-muted-foreground">
          {JSON.stringify(details, null, 2)}
        </pre>
      )}
    </div>
  );
}
