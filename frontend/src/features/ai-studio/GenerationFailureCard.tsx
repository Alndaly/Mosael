import React from "react";
import { RotateCcw, RotateCw } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { FailureCard, type FailureFix } from "@/components/failure/FailureCard";
import { Button } from "@/components/ui/button";
import { Hint } from "@/components/ui/tooltip";

export type { FailureFix } from "@/components/failure/FailureCard";

/** AI 工作台记录流里的卡和在跑的占位、结果画廊同一个宽度:最宽 560px,窄栏里铺满。 */
const RECORD_WIDTH = "w-[min(560px,100%)]";

/** 停下的那一条:不是失败,一枚灰色的停止图标,说一句没有产出。壳是全应用那一份失败展示(components/failure/FailureCard)。 */
export function GenerationStoppedCard({ meta }: { meta?: React.ReactNode }) {
  const t = useI18n();
  return (
    <FailureCard status="stopped" title={t("genStopped")} summary={t("genStoppedBody")} meta={meta} className={RECORD_WIDTH}
                 data-generation-stopped="" />
  );
}

/** 一颗失败卡上的动作:再来一次、重新取回。`run` 不给就不摆。 */
export type FailureAction = { run: () => void; pending?: boolean };

/**
 * 跑挂了的那一条生成。排版是全应用那一份(components/failure/FailureCard);这里只决定**这一条能做什么**:
 *
 * - 「再来一次」(同样的模型和参数重新提交)、「重新取回」(只在远端可能已经做完、是我们没拿到时,后端 `retrievable` 说了算)、
 *   记着的模型用不了时「去工作流库升级」(`upgrade`);复制错误、「详情」开关由共用的那一份摆在动作行右边。
 * - 一句话(`error_summary`)不带「「连接名」生成失败:」—— 连接和模型在卡头右边的元信息里。
 */
export function GenerationFailureCard({
  summary: said,
  detail,
  fix,
  copyText,
  meta,
  repeat,
  retrieve,
  upgrade,
}: {
  summary: string;
  /** 原文:比那一句多出信息时才有 */
  detail: string | null;
  fix: FailureFix | null;
  /** 「复制错误」复制的那一段(记录上存的整句失败原因,报问题时最有用) */
  copyText: string;
  meta?: React.ReactNode;
  repeat?: FailureAction;
  retrieve?: FailureAction;
  /** 「去工作流库升级」那一颗(记着的模型用不了、修法是升级时由调用方给) */
  upgrade?: React.ReactNode;
}) {
  const t = useI18n();
  const summary = said.trim() || t("genFailed");
  const actions = (
    <>
      {repeat ? (
        <Hint label={t("genRepeatHint")}>
          <Button type="button" variant="outline" size="xs" loading={repeat.pending} onClick={repeat.run} data-failure-repeat="">
            <RotateCw size={12} />
            {t("genRepeat")}
          </Button>
        </Hint>
      ) : null}
      {retrieve ? (
        <Hint label={t("genRetrieveHint")}>
          <Button type="button" variant="outline" size="xs" loading={retrieve.pending} onClick={retrieve.run} data-failure-retrieve="">
            <RotateCcw size={12} />
            {t("genRetrieve")}
          </Button>
        </Hint>
      ) : null}
      {upgrade}
    </>
  );
  return (
    <FailureCard
      title={t("generationFailedTitle")}
      meta={meta}
      summary={summary}
      detail={detail}
      fix={fix}
      copyText={(copyText || detail || summary).trim()}
      actions={actions}
      className={RECORD_WIDTH}
      data-generation-failed=""
    />
  );
}
