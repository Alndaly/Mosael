import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";

import { useI18n } from "@/app/preferences";

/** 一次批量动作的结果:哪些做成了,哪些没做成、为什么。 */
export interface BatchOutcome {
  done: string[];
  failed: { id: string; reason: unknown }[];
}

/**
 * 逐个发、一次性收:后端没有批量接口的地方都这样做(为一张设置页列表加一个破坏性的批量端点不划算)。
 * 一个失败不拦着别的,也不让「做了 N 项」盖过失败的那几项。
 */
export async function runBatch(ids: readonly string[], run: (id: string) => Promise<unknown>): Promise<BatchOutcome> {
  const results = await Promise.allSettled(ids.map((id) => run(id)));
  const outcome: BatchOutcome = { done: [], failed: [] };
  results.forEach((result, index) => {
    if (result.status === "fulfilled") outcome.done.push(ids[index]);
    else outcome.failed.push({ id: ids[index], reason: result.reason });
  });
  return outcome;
}

/**
 * **批量动作只有这一种写法**:勾选 → 逐个发 → 说结果 → 处理勾选。
 *
 * 此前六处各写一遍,已经分叉:设置页模型 / 连接的批量启停、批量删除**把失败吞了**(选择照样清掉,界面上像是全成了);
 * 记忆、计价规则会说失败几项但清掉了勾选;只有画板把没删掉的留在勾选里,可以直接再试一次。现在一律按画板那样:
 *   - 全部成功:清掉勾选(`exitOnSuccess` 时连选择模式一起退),有 `doneMessage` 就说一句;
 *   - 有失败:说「成功 N、失败 M」,勾选只留下失败的那几项。
 * 刷新列表、关确认框这类各页不同的收尾放进 `onSettled`,成功失败都会调。
 */
export function useBatchAction<Extra = void>({
  run,
  selection,
  doneMessage,
  exitOnSuccess = false,
  onSettled,
}: {
  run: (id: string, extra: Extra) => Promise<unknown>;
  selection: { clear: () => void; exit: () => void; keepOnly: (ids: Iterable<string>) => void };
  doneMessage?: (count: number) => string;
  exitOnSuccess?: boolean;
  onSettled?: (outcome: BatchOutcome) => void;
}) {
  const t = useI18n();
  return useMutation({
    mutationFn: ({ ids, extra }: { ids: readonly string[]; extra?: Extra }) => runBatch(ids, (id) => run(id, extra as Extra)),
    onSuccess: (outcome) => {
      onSettled?.(outcome);
      if (outcome.failed.length) {
        selection.keepOnly(outcome.failed.map((one) => one.id));
        toast.error(
          t("bulkPartialFailed").replace("{ok}", String(outcome.done.length)).replace("{failed}", String(outcome.failed.length)),
        );
        return;
      }
      if (exitOnSuccess) selection.exit();
      else selection.clear();
      if (doneMessage) toast.success(doneMessage(outcome.done.length));
    },
  });
}
