import React from "react";
import { toast } from "sonner";

import {
  downloadCommunityShare,
  getCommunityShare,
  getCommunitySharePayload,
  type CommunityShare,
} from "@/api/domains/shares";
import { importWorkflow, type Workflow } from "@/api/domains/workflows";
import { useI18n } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { FailureCard } from "@/components/failure/FailureCard";
import { Button } from "@/components/ui/button";
import { formatBytes } from "@/lib/bytes";

import {
  classifyShareFailure,
  failureMessage,
  importablePayload,
  shareCanImport,
  shareFailureCopy,
  shareKindLabel,
  type ShareFailureKind,
} from "./shareImport";

/**
 * 官网社区分享的「在 Mosael 中打开」:**先预览,人点了才导入**。
 *
 * 三个决定,理由都在这:
 *
 * 1. **不静默导入。** 深链是外部输入面(任何网页都能触发它),所以它只能把「有一份分享等你看」
 *    送到这里;弹窗里摆清标题 / 作者 / 类型 / 大小,由人按「导入到工作区」。
 * 2. **下载计数放在导入那一下。** 预览时 GET 详情和内容(确认这份分享读得回来),但
 *    `POST /shares/{id}/download`(downloads +1)只在人真的按了导入时发:预览一下、点取消
 *    都不该给作者记一次下载。导入用的正是这次 download 交回来的内容 —— 计进去的和被导入的
 *    是同一次请求。
 * 3. **导入走现有的 `POST /api/workflows/import`**,不在这里另写一条导入:格式、版本、未知
 *    节点类型的校验都在后端(mosael_formats + workflows.import_one),前端只把 JSON 交过去。
 *
 * 画板分享目前没有自动导入接口(`routes/boards.py` 没有 import,不在这条链路上现造一个),
 * 所以只说明「先去官网下载文件手动导入」,导入键不可点。
 */

type Phase = "idle" | "loading" | "ready" | "failed" | "importing";

type Failure = { at: "preview" | "import"; kind: ShareFailureKind; detail: string };

export function ShareImportDialog({
  shareId,
  workspaceId,
  onClose,
  onImported,
}: {
  /** null = 关闭。深链送来的是解析器里的 `share:` 后面的那个 id。 */
  shareId: string | null;
  workspaceId: string;
  onClose: () => void;
  /** 导入成功:工作流页据此选中刚建好的那一条(不在这里自己改 hash / 选中状态)。 */
  onImported: (workflow: Workflow) => void;
}) {
  const t = useI18n();
  const open = shareId !== null;
  const [phase, setPhase] = React.useState<Phase>("idle");
  const [detail, setDetail] = React.useState<CommunityShare | null>(null);
  const [failure, setFailure] = React.useState<Failure | null>(null);
  //: 重试预览换一个值再跑一遍 effect(不把 shareId 存进 state —— 那会和弹窗的开关打架)。
  const [attempt, setAttempt] = React.useState(0);

  React.useEffect(() => {
    if (!shareId) {
      setPhase("idle");
      setDetail(null);
      setFailure(null);
      return;
    }
    let alive = true;
    setPhase("loading");
    setDetail(null);
    setFailure(null);
    void (async () => {
      try {
        const found = await getCommunityShare(shareId);
        if (!alive) return;
        setDetail(found);
        // 预览就把内容取一次:不存在 / 连不上在弹窗里就能说清,而不是等人点了导入才失败。
        // 真正导入时再走 POST download(计一次下载),所以这里取到的内容不用。
        if (shareCanImport(found.kind)) await getCommunitySharePayload(shareId);
        if (!alive) return;
        setPhase("ready");
      } catch (error) {
        if (!alive) return;
        setFailure({ at: "preview", kind: classifyShareFailure(error), detail: failureMessage(error) });
        setPhase("failed");
      }
    })();
    return () => {
      alive = false;
    };
  }, [shareId, attempt]);

  const runImport = async () => {
    if (!shareId || phase === "importing" || !shareCanImport(detail?.kind)) return;
    setPhase("importing");
    setFailure(null);
    try {
      //: 这一次既计下载、也把内容交回来(见文件头第 2 条)。
      const { payload } = await downloadCommunityShare(shareId);
      const data = importablePayload(payload);
      if (!data) {
        setFailure({ at: "import", kind: "invalid", detail: "" });
        setPhase("ready");
        return;
      }
      const workflow = await importWorkflow({ workspace_id: workspaceId, data });
      toast.success(t("shareImportDone").replace("{name}", workflow.name));
      onImported(workflow);
      //: 成功后不收本地状态:父级把 shareId 置空、关弹窗(它会同时选中这条工作流)。
    } catch (error) {
      setFailure({ at: "import", kind: classifyShareFailure(error), detail: failureMessage(error) });
      setPhase("ready");
    }
  };

  const retry = () => {
    if (phase === "importing") return;
    if (failure?.at === "import") void runImport();
    else if (shareId) setAttempt((value) => value + 1);
  };

  const copy = failure ? shareFailureCopy(t, failure.kind, failure.detail) : null;
  const canImport = phase === "ready" && shareCanImport(detail?.kind);
  const downloads = detail?.stats?.downloads;
  const author = detail?.author?.display_name?.trim() || detail?.author?.handle?.trim() || "—";

  return (
    <ModalShell
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title={t("shareImportTitle")}
      className="w-[520px] max-w-[92vw]"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={phase === "importing"}>
            {t("cancel")}
          </Button>
          <Button onClick={() => void runImport()} loading={phase === "importing"} disabled={!canImport}>
            {t(phase === "importing" ? "shareImportImporting" : "shareImportConfirm")}
          </Button>
        </>
      }
    >
      <div data-share-import="" className="grid gap-4 pb-4">
        {phase === "loading" ? <p className="m-0 text-ui-sm text-muted-foreground">{t("shareImportLoading")}</p> : null}

        {copy ? (
          <FailureCard
            title={t("shareImportFailed")}
            summary={copy.summary}
            detail={copy.detail}
            fix={copy.fix}
            actions={
              //: 「分享不在」重试没有意义(链接就是错的);「格式不对」重试同一份也一样。其余给一颗重试。
              failure && (failure.kind === "offline" || failure.kind === "other") ? (
                <Button size="sm" variant="outline" onClick={retry}>
                  {t("retry")}
                </Button>
              ) : undefined
            }
          />
        ) : null}

        {detail ? (
          <div className="grid gap-3">
            <p className="m-0 text-ui-md font-semibold leading-snug text-foreground">{detail.title}</p>
            <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 gap-y-2 rounded-lg border border-border bg-card px-4 py-3 text-ui-sm">
            <dt className="m-0 text-muted-foreground">{t("shareImportAuthor")}</dt>
            <dd className="m-0 font-medium text-foreground">{author}</dd>
            <dt className="m-0 text-muted-foreground">{t("shareImportKind")}</dt>
            <dd className="m-0 text-foreground">{shareKindLabel(t, detail.kind)}</dd>
            <dt className="m-0 text-muted-foreground">{t("shareImportSize")}</dt>
            <dd className="m-0 text-foreground">{typeof detail.bytes === "number" ? formatBytes(detail.bytes) : "—"}</dd>
            </dl>
          </div>
        ) : null}

        {detail && typeof downloads === "number" ? (
          <p className="m-0 text-ui-xs text-muted-foreground">
            {t("shareImportDownloads").replace("{n}", String(downloads))}
          </p>
        ) : null}

        {detail && !shareCanImport(detail.kind) ? (
          <p className="m-0 rounded-lg border border-border bg-secondary/40 px-3 py-2 text-ui-sm leading-relaxed text-muted-foreground">
            {t("shareImportBoardUnsupported")}
          </p>
        ) : null}
      </div>
    </ModalShell>
  );
}
