import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import { api, listMembers, type Workspace } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SettingsGroup, SettingsRow } from "@/features/settings/ui";

type Level = "ask" | "judge" | "always";
type Rules = {
  http_request: Level;
  publish: Level;
  run_code: Level;
  notes: string;
};

const EMPTY: Rules = { http_request: "ask", publish: "ask", run_code: "ask", notes: "" };

/** 三类撤不回来的操作,同一种判据。顺序即页面顺序。 */
const GATES = [
  { key: "http_request", label: "autopilotHttp", desc: "autopilotHttpDesc" },
  { key: "publish", label: "autopilotPublish", desc: "autopilotPublishDesc" },
  { key: "run_code", label: "autopilotRunCode", desc: "autopilotRunCodeDesc" },
] as const;

/**
 * 自动放行的准则 —— 「自动放行」档下,**撤不回来**的那类操作按什么判。
 *
 * 三类操作、同一种判据:默认一律问你;想让那个与对话隔离的判断者接管,就把那一档显式打开。
 *
 * 曾经有两份白名单(允许的请求主机、允许的发布账号)。删掉的理由是它们**没在工作**:那份清单
 * 既难写(精确匹配、不支持通配)又难维护(换个 CDN 域名就失效),于是绝大多数人的名单永远是空的
 * —— 也就是说「自动放行」对这两类从来没生效过,只是每次都多问一遍。而页面上那句"名单之外的情况
 * 交给判断者"只对 run_code 成立,对这两项是错的(它们不命中直接拒绝,判断者根本不参与)。
 *
 * 删掉之后是**收紧**:此前名单命中是确定性放行、连判断者都不过;现在最宽也要过判断者那一关。
 * 「补充说明」仍是喂给判断者的唯一自由文本 —— 它单独放行不了任何东西。
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
      {GATES.map((gate) => (
        <SettingsRow key={gate.key} label={t(gate.label)} description={t(gate.desc)}>
          <Select
            key={draft[gate.key]}
            value={draft[gate.key]}
            disabled={!canEdit}
            onValueChange={(value) => patch({ [gate.key]: value as Level })}
          >
            <SelectTrigger className="h-8 w-[180px] text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ask">{t("autopilotGateAsk")}</SelectItem>
              <SelectItem value="judge">{t("autopilotGateJudge")}</SelectItem>
              <SelectItem value="always">{t("autopilotGateAlways")}</SelectItem>
            </SelectContent>
          </Select>
        </SettingsRow>
      ))}
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
