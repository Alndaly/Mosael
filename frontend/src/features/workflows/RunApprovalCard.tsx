import { useMutation, useQueryClient } from "@tanstack/react-query";
import { UserCheck } from "lucide-react";
import { toast } from "sonner";
import React from "react";

import { decideRunApproval, runApprovalsKey, type RunApproval } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { parseServerTime } from "@/lib/time";
import { cn } from "@/lib/utils";

/**
 * 「等人确认」那一步**展开体里的审批卡** —— 它不再独占面板顶部那一段,
 * 而是挂在它实际卡住的那一步里面:步骤行说「停在哪」,这张卡说「要你做什么」,
 * 同一件事不说两遍。
 *
 * 这是**应用内那一半**:飞书里点卡片和这里点按钮走的是后端同一处决定路径
 * (`POST /api/run-approvals/{id}/decide` → domain/workflows/approvals.decide_and_wake),
 * 一处写决定、一处唤醒那次运行 —— 两条路不是两套。
 */
export function RunApprovalCard({ row, workflowId }: { row: RunApproval; workflowId: string }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [note, setNote] = React.useState("");
  //: 正文默认折几行;「展开全文 / 收起」落在这一张卡自己的状态上。
  const [openBody, setOpenBody] = React.useState(false);
  const bodyId = React.useId();
  const decide = useMutation({
    mutationFn: (decision: "approved" | "rejected") => decideRunApproval(row.id, decision, note.trim()),
    onSuccess: (updated) => {
      //: 决定落了库,那次运行**正在接着跑**:待批单、运行记录、事件流都要重拉。
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
  //: 折几行;正文短的时候 `folded` 为 false,什么都不发生。
  const preview = row.body ? previewOf(row.body) : null;
  const folded = Boolean(preview?.folded);
  const shownBody = preview ? (openBody ? row.body : preview.shown) : "";
  return (
    /* 一张软底卡:铺开的三块是 标题(要你做什么)/ 正文(要批的是什么)/ 操作(元信息 + 备注 + 决定),
       内容区与操作区之间一条分隔线。底是「次级面」那一档,不画边框 —— 面板那一圈框仍是全面板唯一的框。 */
    <div data-wf-run-approval="" className="flex min-w-0 flex-col gap-2 rounded-lg bg-muted p-3 text-ui-xs text-muted-foreground">
      <p className="m-0 flex items-center gap-1.5 text-xs font-semibold text-foreground">
        <UserCheck size={13} className="shrink-0 text-warning" />
        {row.title}
      </p>
      {/*: **正文有上限、自己滚。** 审批正文可能是整篇稿子(几千字),折几行默认收起,
          展开后也只在这一块里滚 —— 「确认 / 拒绝」永远在卡上看得见的地方,不被正文推走。 */}
      {row.body && (
        <div
          data-wf-run-approval-body=""
          //: 不写 overscroll-contain:正文滚到底之后,滚轮要继续传给外层详情区 ——
          //: 否则光标停在卡内时整个详情滚不动(维护者实测)。
          className="max-h-[min(24rem,40vh)] overflow-y-auto"
        >
          {/*: 折叠时末尾给一个省略号 —— 让「这里还有」看得见,而不是断在一句话中间。 */}
          <p id={bodyId} className="m-0 whitespace-pre-wrap break-words leading-[1.6]">
            {shownBody}
            {folded && !openBody ? <span className="text-muted-foreground">…</span> : null}
          </p>
        </div>
      )}
      {folded && (
        <Button
          variant="inline"
          aria-expanded={openBody}
          aria-controls={bodyId}
          className="self-start underline"
          onClick={() => setOpenBody((value) => !value)}
        >
          {openBody ? t("confirmCollapse") : t("confirmNoteExpand")}
        </Button>
      )}
      {/* 操作区:元信息(什么时候算超时 · 到底发到飞书没有)/ 备注 / 决定。 */}
      <div className="flex min-w-0 flex-col gap-2 border-t border-border pt-2">
        <p className="m-0 flex flex-wrap items-center gap-1 text-ui-2xs">
          <span>{expiry(row, t)}</span>
          {delivery && (
            <>
              <span aria-hidden>·</span>
              <span className={cn(delivery.failed ? "font-medium text-warning" : "text-muted-foreground")} data-wf-run-approval-delivery={row.feishu_delivery}>
                {delivery.text}
              </span>
            </>
          )}
        </p>
        {row.allow_note && (
          <Input
            size="sm"
            placeholder={t("runApprovalNotePlaceholder")}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        )}
        {/*: 按钮右对齐。转圈只给**被点的那一颗** —— 此前两颗都吃 `decide.isPending`,
            点「拒绝」两个一起转,看起来像两个决定都在提交。 */}
        <div className="flex flex-wrap items-center justify-end gap-2">
          <span className="mr-auto text-ui-2xs">
            {decide.isPending
              ? t("runApprovalSending")
              : /*: 这句只在**真发出去过**时才说 —— 没发出去时元信息那行已经说清了去哪儿批。 */
                row.feishu_delivery === "sent"
                ? t("runApprovalFeishuHint")
                : ""}
          </span>
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
        </div>
      </div>
    </div>
  );
}

/** 折叠后露出的行数:够看清这一张在问什么,又不至于把「确认 / 拒绝」推出面板。 */
const FOLD_LINES = 5;
/** 没有换行的长段落也要折:一行几千字的稿件,光按行数折不住(一行就是全部)。 */
const FOLD_CHARS = 320;

/**
 * 折叠时露出来的那一段。**在 JS 里切,不靠 CSS 的 `line-clamp`** ——
 * 跟 AI 助手正文、笔记差异同一套(见 ConfirmationCard 的 TextBlock):切掉的字不在 DOM 里,
 * 读屏也不会读到一截被 CSS 藏起来的重复全文;而 `line-clamp` 在本仓是「截断不给出全文」的记号
 * (design/truncatedText.test.ts),这里本来就有一条「展开全文」,不该再混进那个清单。
 */
function previewOf(text: string): { shown: string; folded: boolean } {
  const lines = text.split("\n");
  const preview = lines.slice(0, FOLD_LINES).join("\n").slice(0, FOLD_CHARS);
  return { shown: preview, folded: preview.length < text.length };
}

/**
 * 「这一次到底发到飞书没有」。空 = 不说(这张单是投递结果那一版之前建的,没有记录)。
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
