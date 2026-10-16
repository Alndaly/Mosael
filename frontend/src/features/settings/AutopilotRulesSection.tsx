import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import { api, listMembers, type Workspace } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SETTINGS_FIELD_WIDTH, SettingsGroup, SettingsRow } from "@/components/settings/settings-layout";

type Level = "ask" | "judge" | "always";
type Rules = {
  http_request: Level;
  publish: Level;
  run_code: Level;
  run_host_code: Level;
  blender: Level;
  notes: string;
};

const EMPTY: Rules = { http_request: "ask", publish: "ask", run_code: "ask", run_host_code: "ask", blender: "ask", notes: "" };

const sameRules = (a: Rules, b: Rules) => JSON.stringify(a) === JSON.stringify(b);

/** 几类撤不回来的操作,同一种判据。顺序即页面顺序。沙箱与不隔离是两档:放开前者不连带后者。 */
const GATES = [
  { key: "http_request", label: "autopilotHttp", desc: "autopilotHttpDesc" },
  { key: "publish", label: "autopilotPublish", desc: "autopilotPublishDesc" },
  { key: "run_code", label: "autopilotRunCode", desc: "autopilotRunCodeDesc" },
  { key: "run_host_code", label: "autopilotRunHostCode", desc: "autopilotRunHostCodeDesc" },
  { key: "blender", label: "autopilotBlender", desc: "autopilotBlenderDesc" },
] as const;

/**
 * 自动放行的准则 —— 「自动放行」档下,**撤不回来**的那类操作按什么判。
 *
 * 这几类操作、同一种判据:默认一律问你;想让那个与对话隔离的判断者接管,就把那一档显式打开。
 *
 * **这句话不再数行,也不列清单。**「三类」是 2026-08-07(`ab06e5b80`)写的数字,那时 `GATES`
 * 正好三档;`run_host_code` 与 `blender` 是 2026-09-20(`ea82c4e73` / `f9924c78c`)加进来的,
 * 这句说明没跟着改 —— 是个过期数字,不是有意的归类。而改成列举(「对外请求、公开发布、执行代码」)
 * 下次再加一档还会过期,列举里那层「执行代码含沙箱 / 不隔离 / Blender」的归类更没有依据
 * (Blender 算不算「执行代码」并没有判据)。界面上那几行各自带标签与说明,不靠这句话解释 ——
 * 所以只说「这几类」,指的就是这一页列出来的那几行。
 *
 * 曾经有两份白名单(允许的请求主机、允许的发布账号)。删掉的理由是它们**没在工作**:那份清单
 * 既难写(精确匹配、不支持通配)又难维护(换个 CDN 域名就失效),于是绝大多数人的名单永远是空的
 * —— 也就是说「自动放行」对这两类从来没生效过,只是每次都多问一遍。当时页面上那句"名单之外的情况
 * 交给判断者"也只对 run_code 成立,对这两项是错的(它们不命中直接拒绝,判断者根本不参与)。
 *
 * 那句**页面原话也一并改了**:白名单不存在之后,`autopilotJudgeDesc` 不再提「名单」,说的是
 * 「交给判断者的那几档,由一次单独的模型调用判断」。说明里不能留着一个已经不在的东西 ——
 * 而这件事没有测试会拦(文案表那两道棘轮只管 markdown、键集与有没有人用),只能写在这里。
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
  //: 草稿是照着哪一份服务端准则改的。服务端那份变了(后台重新拉取、别人改过)**只在这里没有
  //: 没存的改动时**跟上 —— 此前每次拉回来都整份盖掉草稿,正在写的补充说明说没就没。
  const basis = React.useRef<Rules>(EMPTY);
  const adopt = React.useCallback((next: Rules, from: Rules = basis.current) => {
    setDraft((current) => (sameRules(current, from) ? next : current));
    basis.current = next;
  }, []);
  React.useEffect(() => {
    if (query.data) adopt(query.data.rules);
  }, [query.data, adopt]);

  const save = useMutation({
    mutationFn: (rules: Rules) =>
      api<{ rules: Rules }>(`/api/workspaces/${workspace.id}/autopilot-rules`, {
        method: "PUT",
        body: JSON.stringify({ rules }),
      }),
    onSuccess: (data, sent) => {
      //: 存的时候还在改的话,手上那份比刚存下的新 —— 不拿回执盖掉。
      adopt(data.rules, sent);
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
          <span className="inline-flex items-center gap-1.5 text-ui-xs text-muted-foreground">
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
            <SelectTrigger className={SETTINGS_FIELD_WIDTH}>
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
      <SettingsRow label={t("autopilotNotes")} description={t("autopilotNotesDesc")} stacked>
        <Textarea
          className="min-h-24"
          readOnly={!canEdit}
          value={draft.notes}
          placeholder={t("autopilotNotesPlaceholder")}
          onChange={(event) => patch({ notes: event.currentTarget.value })}
        />
      </SettingsRow>
      <SettingsRow label={t("autopilotJudgeTitle")} description={t("autopilotJudgeDesc")}>
        <span className="inline-flex items-center gap-1.5 text-ui-xs text-muted-foreground">
          <ShieldCheck size={13} /> {t("autopilotJudgeBadge")}
        </span>
      </SettingsRow>
    </SettingsGroup>
  );
}
