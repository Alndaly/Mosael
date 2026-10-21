import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { UserCheck } from "lucide-react";
import { toast } from "sonner";
import React from "react";

import { decideRunApproval, listRunApprovals, runApprovalsKey, type RunApproval } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { CANVAS_GLASS_SURFACE_CLASS } from "@/components/app/canvasPanelLayout";
import { parseServerTime } from "@/lib/time";
import { cn } from "@/lib/utils";

/**
 * 「这一步在等你确认」—— `await_approval` 节点把一次运行停下时,运行历史面板顶上那一条。
 *
 * 这是**应用内那一半**:飞书里点卡片和这里点按钮走的是后端同一处决定路径
 * (`POST /api/run-approvals/{id}/decide` → domain/workflows/approvals.decide_and_wake),
 * 一处写决定、一处唤醒那次运行 —— 两条路不是两套。
 *
 * 没有飞书绑定时这一条就是唯一的入口;有飞书时两条并存,先到的那一个算数(后端 CAS)。
 */
export function RunApprovalNotice({ workflowId }: { workflowId: string }) {
  const t = useI18n();
  const pending = useQuery({
    queryKey: runApprovalsKey(workflowId),
    queryFn: () => listRunApprovals(workflowId),
    //: 停在等人确认上的运行**会一直停着**,所以这一条要轮询 —— 别处的决定(飞书点的、别人点的、
    //: 超时处理的)落了库,这一条得自己消失。
    refetchInterval: (q) => ((q.state.data as RunApproval[] | undefined)?.length ? 5000 : false),
  });
  const rows = pending.data ?? [];
  if (rows.length === 0) return null;
  return (
    <div
      role="status"
      data-wf-run-approval=""
      // 标题栏自带 border-b,这里再来一条就是两条线并排(维护者:「内部甚至我感觉有多余的边线」)。
      className={cn(CANVAS_GLASS_SURFACE_CLASS, "grid gap-2 px-3 py-2 text-ui-xs text-muted-foreground")}
    >
      <p className="m-0 flex items-center gap-1.5 font-medium text-foreground">
        <UserCheck size={13} className="shrink-0 text-warning" />
        {t("runApprovalHeading")}
      </p>
      {rows.map((row) => (
        <RunApprovalRow key={row.id} row={row} workflowId={workflowId} />
      ))}
    </div>
  );
}

function RunApprovalRow({ row, workflowId }: { row: RunApproval; workflowId: string }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [note, setNote] = React.useState("");
  const decide = useMutation({
    mutationFn: (decision: "approved" | "rejected") => decideRunApproval(row.id, decision, note.trim()),
    onSuccess: (updated) => {
      //: 决定落了库,那次运行**正在接着跑**:列表(它不再挂在待批里)和运行记录都要重拉。
      void qc.invalidateQueries({ queryKey: runApprovalsKey(workflowId) });
      void qc.invalidateQueries({ queryKey: ["workflow-runs", workflowId] });
      void qc.invalidateQueries({ queryKey: ["job-events"] });
      toast.success(
        t("runApprovalDone").replace(
          "{decision}",
          updated.decision === "approved" ? t("runApprovalApproved") : t("runApprovalRejected"),
        ),
      );
    },
    onError: (error: Error) => toast.error(t("runApprovalFailed"), { description: error.message }),
  });
  //: 这一次点的是哪个决定 —— 只用来决定**哪一颗按钮转圈**(见下面那颗按钮上的注释)。
  const deciding = decide.isPending ? decide.variables : null;
  const delivery = deliveryLine(row, t);
  return (
    <div className="grid gap-1.5 rounded-md border border-border bg-background/40 p-2">
      <p className="m-0 font-medium text-foreground">{row.title}</p>
      {/*: **正文有上限、自己滚。** 审批正文可能是整篇稿子(几千字),此前它原样铺开、
          把「同意 / 拒绝」推到可视区外面,而外面这一层不滚 —— 维护者撞到的就是"卡太高,点不到按钮"。
          上限跟着视口走(`40vh`),短正文不受影响;按钮因此永远在卡里看得见的地方。 */}
      {row.body && (
        <div
          className="max-h-[min(24rem,40vh)] overflow-y-auto overscroll-contain rounded border border-border/60 bg-secondary/40 px-2 py-1.5"
          data-wf-run-approval-body=""
        >
          <p className="m-0 whitespace-pre-wrap break-words">{row.body}</p>
        </div>
      )}
      <p className="m-0">{t("runApprovalWaiting").replace("{node}", row.node_name || row.node_id)}</p>
      <p className="m-0 text-ui-2xs">{expiry(row, t)}</p>
      {/*: **到底发到飞书没有**。后端把投递结果记在那张单上(见 domain/workflows/approvals):
          发了 / 这次就没打算发(写了「仅站内」、没有机器人、没绑定)/ 发失败了。
          没发出去的那两种要用一行提醒看得见 —— 用户在飞书群里等一张**不会来的卡**,
          而下面那句「在飞书里点那张卡也一样」正是在说"去飞书点"。 */}
      {delivery && (
        <p
          className={cn("m-0 text-ui-2xs", delivery.failed ? "font-medium text-warning" : "text-muted-foreground")}
          data-wf-run-approval-delivery={row.feishu_delivery}
        >
          {delivery.text}
        </p>
      )}
      {row.allow_note && (
        <input
          className="w-full rounded-md border border-border bg-transparent px-2 py-1 text-ui-xs text-foreground"
          placeholder={t("runApprovalNotePlaceholder")}
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      )}
      <div className="flex flex-wrap items-center gap-1.5">
        {/*: 转圈只给**被点的那一颗**。此前两颗都吃 `decide.isPending`,点「拒绝」两个一起转 ——
            看起来像两个决定都在提交。这一次点的是哪个由这次 mutate 的参数说了算
            (`decide.variables`,自带一份就够,不再另起一个 state);另一颗只禁用,不转圈。 */}
        <Button
          size="sm"
          loading={deciding === "approved"}
          disabled={decide.isPending && deciding !== "approved"}
          onClick={() => decide.mutate("approved")}
        >
          {row.approve_label || t("runApprovalApproved")}
        </Button>
        <Button
          size="sm"
          variant="outline"
          loading={deciding === "rejected"}
          disabled={decide.isPending && deciding !== "rejected"}
          onClick={() => decide.mutate("rejected")}
        >
          {row.reject_label || t("runApprovalRejected")}
        </Button>
        <span className="text-ui-2xs">
          {decide.isPending
            ? t("runApprovalSending")
            : /*: 这句只在**真发出去过**时才说 —— 没发出去时上面那行已经说清了去哪儿批。 */
              row.feishu_delivery === "sent"
              ? t("runApprovalFeishuHint")
              : ""}
        </span>
      </div>
    </div>
  );
}

/**
 * 「这一次到底发到飞书没有」那一行。空 = 不说(这张单是投递结果那一版之前建的,没有记录)。
 *
 * 三档照后端 `domain/workflows/approvals` 的 `feishu_delivery`:
 * `sent`(卡片成了,或卡片失败之后退成的那段文字成了)、
 * `not_attempted`(路由那一层就没打算发:写了「仅站内」/ 没机器人 / 没绑定 —— **用户的选择或这次没有去处,不是失败**)、
 * `failed`(卡片和文字都没出去:那才要在界面上说得像个问题)。
 */
function deliveryLine(
  row: RunApproval,
  t: ReturnType<typeof useI18n>,
): { text: string; failed: boolean } | null {
  if (row.feishu_delivery === "sent") return { text: t("runApprovalDeliverySent"), failed: false };
  if (row.feishu_delivery === "not_attempted") {
    return { text: `${t("runApprovalDeliveryStationOnly")} · ${reasonWord(row.feishu_delivery_reason, t)}`, failed: false };
  }
  if (row.feishu_delivery === "failed") {
    //: 发失败时把后端那句原因原样带上(它是一句拿得出手的说明),再说清"只能在站内批"。
    return { text: `${t("runApprovalNotDelivered")}(${row.feishu_delivery_reason || reasonWord("", t)})`, failed: true };
  }
  return null;
}

/** 路由那一档的原因(见后端 domain/feishu/routing 的 reason)—— 每一档的修法不同,不该只说"没发出去"。 */
function reasonWord(reason: string, t: ReturnType<typeof useI18n>): string {
  if (reason === "none") return t("runApprovalReasonNone");
  if (reason === "no-bot") return t("runApprovalReasonNoBot");
  if (reason === "no-origin") return t("runApprovalReasonNoOrigin");
  if (reason === "not-bound") return t("runApprovalReasonNotBound");
  if (reason === "no-target") return t("runApprovalReasonNoTarget");
  return reason || t("runApprovalReasonUnknown");
}

/** 什么时候算超时。`expires_at` 是后端给的那一刻(空 = 不设超时,一直等)。 */
function expiry(row: RunApproval, t: ReturnType<typeof useI18n>): string {
  if (!row.expires_at) return t("runApprovalNoExpiry");
  //: 后端给的是不带时区的 UTC —— 自己拼 `Z` 会绕过 lib/time 那一条(见 lib/time.test.ts)。
  const minutes = Math.max(0, Math.round((parseServerTime(row.expires_at).getTime() - Date.now()) / 60000));
  const left = minutes >= 60 ? `${Math.round(minutes / 60)}h` : `${minutes}m`;
  return t("runApprovalExpires").replace("{time}", left);
}
