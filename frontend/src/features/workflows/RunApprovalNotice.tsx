import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { UserCheck } from "lucide-react";
import { toast } from "sonner";
import React from "react";

import { decideRunApproval, listRunApprovals, runApprovalsKey, type RunApproval } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
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
      // **待批段的两个形态:2px 强调色左边条 + 浅强调底**(ADR 0074,维护者选定)。
      // 这里**不画整圈边、不铺卡片底** —— 整块面板只有它自己那一圈 `rounded-xl border`;
      // 段与段之间只有一条 `border-t`(见 WorkflowRunHistory 的列表/详情)。
      // 没有待批时整块返回 null:不占位、不留线。
      className="flex shrink-0 flex-col gap-2 border-l-2 border-primary bg-accent/40 px-3 py-2 text-ui-xs text-muted-foreground"
    >
      <p className="m-0 flex items-center gap-1 font-medium text-foreground">
        <UserCheck size={13} className="shrink-0 text-warning" />
        {t("runApprovalHeading")}
      </p>
      {rows.map((row) => (
        <RunApprovalRow key={row.id} row={row} workflowId={workflowId} />
      ))}
    </div>
  );
}

/** 折叠后露出的行数:够看清这一段在问什么,又不至于把「确认 / 拒绝」推出面板。 */
const FOLD_LINES = 6;
/** 没有换行的长段落也要折:一行几千字的稿件,光按行数折不住(一行就是全部)。 */
const FOLD_CHARS = 360;

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

function RunApprovalRow({ row, workflowId }: { row: RunApproval; workflowId: string }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [note, setNote] = React.useState("");
  //: 正文默认折 6 行;「展开全文 / 收起」改成落在这一行自己的状态上(同一条待批单里可能有多条)。
  const [openBody, setOpenBody] = React.useState(false);
  const bodyId = React.useId();
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
  //: 折 6 行;正文短的时候 `folded` 为 false,什么都不发生。
  const preview = row.body ? previewOf(row.body) : null;
  const folded = Boolean(preview?.folded);
  const shownBody = preview ? (openBody ? row.body : preview.shown) : "";
  return (
    /* 一行待批单:外层那一段已经有左条和浅底,这里只是一组块(标题 / 正文 / 元信息 / 备注 / 按钮),
       间距 8px,不再自己画边、铺底。 */
    <div data-wf-run-approval-row="" className="flex min-w-0 flex-col gap-2">
      <p className="m-0 font-medium text-foreground">{row.title}</p>
      {/*: **正文:折叠 6 行,展开后限高滚动;不画边、不铺底。**
          上限和滚动只在正文这一块(ADR 0074 决定 5 唯一的例外,刻意的:整篇稿子不该把按钮推走)——
          这里再画一圈边就成了"框套框",再铺一块底就成了第四块底。 */}
      {row.body && (
        <div
          data-wf-run-approval-body=""
          className="max-h-[min(24rem,40vh)] overflow-y-auto"
        >
          {/*: 折叠时末尾给一个省略号 —— 让「这里还有」看得见,而不是断在一句话中间。 */}
          <p id={bodyId} className="m-0 whitespace-pre-wrap break-words">
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
          className="justify-self-start"
          onClick={() => setOpenBody((value) => !value)}
        >
          {openBody ? t("confirmCollapse") : t("confirmNoteExpand")}
        </Button>
      )}
      {/* 元信息:停在哪一步、什么时候算超时 —— 一行,段内 4px。 */}
      <p className="m-0 flex flex-wrap items-center gap-1 text-ui-2xs text-muted-foreground">
        <span>{t("runApprovalWaiting").replace("{node}", row.node_name || row.node_id)}</span>
        <span aria-hidden>·</span>
        <span>{expiry(row, t)}</span>
      </p>
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
        //: 输入框只画**一条下划线**:面板里只有一层框,再给输入框一圈边就是第二个框。
        <input
          className="w-full border-b border-border bg-transparent px-0 py-1 text-ui-xs text-foreground placeholder:text-muted-foreground focus-visible:border-primary focus-visible:outline-none"
          placeholder={t("runApprovalNotePlaceholder")}
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      )}
      {/*: **按钮右对齐,并且贴在滚动口底沿。** 正文有自己的限高滚动;但面板可以被拖到
          380px(悬浮的最小高度),这时「标题 + 正文 + meta + 备注 + 展开」仍然比可视区高,
          按钮会落到底沿外(实测:按钮 622–654,面板 236–616)。`sticky bottom-0` 让它在
          这种情况下钉在面板底、始终点得到;正常高度下它就是普通一行,看不出区别。
          底色用和待批段同一档的强调色 + 面板底混出来的不透明色(`bg-accent/40` 叠在面板上
          就是这个颜色),不是第四块底、也不画边。 */}
      <div
        data-wf-run-approval-actions=""
        className="sticky bottom-0 z-[1] flex flex-wrap items-center justify-end gap-2 bg-[color-mix(in_oklab,var(--accent)_40%,var(--panel))] py-1"
      >
        {/*: 转圈只给**被点的那一颗**。此前两颗都吃 `decide.isPending`,点「拒绝」两个一起转 ——
            看起来像两个决定都在提交。这一次点的是哪个由这次 mutate 的参数说了算
            (`decide.variables`,自带一份就够,不再另起一个 state);另一颗只禁用,不转圈。 */}
        <span className="mr-auto text-ui-2xs">
          {decide.isPending
            ? t("runApprovalSending")
            : /*: 这句只在**真发出去过**时才说 —— 没发出去时上面那行已经说清了去哪儿批。 */
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
