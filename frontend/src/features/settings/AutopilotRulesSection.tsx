import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock, Plus, ShieldCheck, X } from "lucide-react";
import { toast } from "sonner";

import { api, listMembers, type Workspace } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SettingsGroup, SettingsRow } from "@/features/settings/ui";

type Rules = {
  http_allow_hosts: string[];
  publish_allow_accounts: string[];
  run_code: "ask" | "judge";
  notes: string;
};

const EMPTY: Rules = { http_allow_hosts: [], publish_allow_accounts: [], run_code: "ask", notes: "" };

/**
 * 自动放行的准则 —— 「自动放行」档下,**撤不回来**的那类操作按什么判。
 *
 * 这一页配的是确定性的那一半:名单命中就放行、不命中就问你,判断者翻不了案。名单之外的情况才
 * 交给一个看不到对话内容的判断者,而「补充说明」是喂给它的唯一自由文本 —— 它单独放行不了任何东西。
 *
 * 主机名**精确匹配,不做通配**:`*.example.com` 里哪些子域算数取决于谁在解析它,而白名单要能被
 * 逐条读懂,不是被逐条猜。
 */
export function AutopilotRulesSection({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["autopilot-rules", workspace.id],
    queryFn: () => api<{ rules: Rules }>(`/api/workspaces/${workspace.id}/autopilot-rules`),
  });
  // 改准则要 admin(后端 ensure_workspace_role)。**没权限就别给可编辑的控件** —— 让人填完一整页
  // 再用一个 403 告诉他不行,是把"看得见但做不到"当成了提示。
  const members = useQuery({ queryKey: ["members", workspace.id], queryFn: () => listMembers(workspace.id) });
  const role = members.data?.my_role ?? "viewer";
  const canEdit = role === "admin" || role === "owner";

  const [draft, setDraft] = React.useState<Rules>(EMPTY);
  React.useEffect(() => {
    if (query.data) setDraft(query.data.rules);
  }, [query.data]);

  const save = useMutation({
    mutationFn: (rules: Rules) =>
      api<{ rules: Rules }>(`/api/workspaces/${workspace.id}/autopilot-rules`, {
        method: "PUT",
        body: JSON.stringify({ rules }),
      }),
    onSuccess: (data) => {
      setDraft(data.rules);
      void qc.invalidateQueries({ queryKey: ["autopilot-rules", workspace.id] });
      toast.success(t("autopilotSaved"));
    },
  });

  const patch = (next: Partial<Rules>) => setDraft((current) => ({ ...current, ...next }));

  return (
    <SettingsGroup
      title={t("autopilotTitle")}
      description={t("autopilotDesc")}
      actions={
        canEdit ? (
          <Button size="sm" loading={save.isPending} onClick={() => save.mutate(draft)}>
            {t("save")}
          </Button>
        ) : (
          <span className="inline-flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
            <Lock size={12} /> {t("autopilotAdminOnly")}
          </span>
        )
      }
    >
      <SettingsRow
        label={t("autopilotHosts")}
        description={t("autopilotHostsDesc")}
        className="grid-cols-1 items-start gap-2"
      >
        <TokenList
          values={draft.http_allow_hosts}
          placeholder="api.example.com"
          addLabel={t("autopilotAddHost")}
          emptyLabel={t("autopilotNothingAllowed")}
          readOnly={!canEdit}
          onChange={(http_allow_hosts) => patch({ http_allow_hosts })}
        />
      </SettingsRow>
      <SettingsRow
        label={t("autopilotAccounts")}
        description={t("autopilotAccountsDesc")}
        className="grid-cols-1 items-start gap-2"
      >
        <TokenList
          values={draft.publish_allow_accounts}
          placeholder="acc-…"
          addLabel={t("autopilotAddAccount")}
          emptyLabel={t("autopilotNothingAllowed")}
          readOnly={!canEdit}
          onChange={(publish_allow_accounts) => patch({ publish_allow_accounts })}
        />
      </SettingsRow>
      <SettingsRow label={t("autopilotRunCode")} description={t("autopilotRunCodeDesc")}>
        <Select
          key={draft.run_code}
          value={draft.run_code}
          disabled={!canEdit}
          onValueChange={(value) => patch({ run_code: value as Rules["run_code"] })}
        >
          <SelectTrigger className="h-8 w-[180px] text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ask">{t("autopilotRunCodeAsk")}</SelectItem>
            <SelectItem value="judge">{t("autopilotRunCodeJudge")}</SelectItem>
          </SelectContent>
        </Select>
      </SettingsRow>
      <SettingsRow
        label={t("autopilotNotes")}
        description={t("autopilotNotesDesc")}
        className="grid-cols-1 items-start gap-2"
      >
        <Textarea
          className="min-h-[80px] text-xs"
          readOnly={!canEdit}
          value={draft.notes}
          placeholder={t("autopilotNotesPlaceholder")}
          onChange={(event) => patch({ notes: event.currentTarget.value })}
        />
      </SettingsRow>
      <SettingsRow label={t("autopilotJudgeTitle")} description={t("autopilotJudgeDesc")}>
        <span className="inline-flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
          <ShieldCheck size={13} /> {t("autopilotJudgeBadge")}
        </span>
      </SettingsRow>
    </SettingsGroup>
  );
}

/** 一串可增删的条目。名单就该长成名单,而不是一个要自己记住用逗号分隔的输入框。 */
function TokenList({
  values,
  placeholder,
  addLabel,
  emptyLabel,
  readOnly,
  onChange,
}: {
  values: string[];
  placeholder: string;
  addLabel: string;
  emptyLabel: string;
  readOnly?: boolean;
  onChange: (next: string[]) => void;
}) {
  const [entry, setEntry] = React.useState("");
  const add = () => {
    const value = entry.trim();
    if (!value || values.includes(value)) return setEntry("");
    onChange([...values, value]);
    setEntry("");
  };
  return (
    <div className="grid w-full gap-1.5">
      {values.length === 0 ? (
        <p className="m-0 text-[11.5px] text-muted-foreground">{emptyLabel}</p>
      ) : (
        <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
          {values.map((value) => (
            <li
              key={value}
              className="inline-flex items-center gap-1 rounded-full border border-border bg-panel px-2 py-0.5 text-[11.5px]"
            >
              <code className="timecode">{value}</code>
              {!readOnly && (
                <button
                  type="button"
                  aria-label={`remove ${value}`}
                  className="cursor-pointer border-0 bg-transparent p-0 text-muted-foreground transition-colors hover:text-destructive"
                  onClick={() => onChange(values.filter((item) => item !== value))}
                >
                  <X size={11} />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {readOnly ? null : (
      <div className="flex gap-1.5">
        <Input
          className="h-8 max-w-[280px] text-xs"
          value={entry}
          placeholder={placeholder}
          onChange={(event) => setEntry(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              add();
            }
          }}
        />
        <Button size="sm" variant="outline" onClick={add} disabled={!entry.trim()}>
          <Plus size={13} /> {addLabel}
        </Button>
      </div>
      )}
    </div>
  );
}
