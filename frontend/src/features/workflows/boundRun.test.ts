/**
 * 画布绑哪一次运行。
 *
 * 此前只认**自己在这一页点「运行」**起的那次(`onSuccess` 里记下 job id)。于是:
 *
 *   - 子工作流是被父流程的 `call_workflow` 起来的(它有自己的 job,见 executors/subworkflow),
 *     点进它的画布时这一页从没调用过 run —— 一个节点状态都没有、没有 loading,明明正在跑,
 *     看着像根本没开始;
 *   - 关掉再打开一个正在跑的工作流,同样什么都不显示。
 *
 * 判据改成「自己起的那次 → 否则这个工作流最近的一次运行,优先还在跑的那次」。这条测试钉住
 * 那个选择,因为它在 WorkflowsView 里是一个 useMemo,出错的表现是"界面安静地不动",不会报错。
 */
import { describe, expect, it } from "vitest";

import { boundRunId, RUN_ACTIVE, viewedRunId } from "./boundRun";

const run = (id: string, status: string) => ({ id, status }) as never;

describe("画布绑定的运行", () => {
  it("自己点运行起的那次优先 —— 哪怕历史里有更新的一条", () => {
    // 刚点完运行,列表可能还没刷新到;此时也不该跳去标别的运行的状态。
    expect(boundRunId("mine", [run("newer", "running")])).toBe("mine");
  });

  it("没自己起过就取正在跑的那次 —— 子工作流就是这种", () => {
    expect(boundRunId(null, [run("old", "succeeded"), run("live", "running")])).toBe("live");
  });

  it("都跑完了就取最近的一次,方便回看跑成什么样", () => {
    // 列表是**新的在前**(listWorkflowRuns 的约定)。
    expect(boundRunId(null, [run("latest", "succeeded"), run("older", "failed")])).toBe("latest");
  });

  it("一次都没跑过就是没有", () => {
    expect(boundRunId(null, [])).toBeNull();
    expect(boundRunId(null, undefined)).toBeNull();
  });

  it("排队中和 pending 都算还在跑", () => {
    // queued 的子工作流已经建好了 job,画布该立刻开始跟着它走。
    expect(RUN_ACTIVE.has("queued")).toBe(true);
    expect(RUN_ACTIVE.has("pending")).toBe(true);
    expect(RUN_ACTIVE.has("running")).toBe(true);
    expect(RUN_ACTIVE.has("succeeded")).toBe(false);
  });
});

describe("正在看哪一次运行", () => {
  //: 此前执行历史自己记一份选中:在历史里点开一次旧的,画布和检查器还停在最近那次。
  it("没点过就跟随", () => {
    expect(viewedRunId(null, "latest", [run("latest", "succeeded"), run("older", "failed")])).toBe("latest");
  });

  it("点了一次旧的就一直看那一次 —— 哪怕又冒出来一次新的", () => {
    expect(viewedRunId("older", "newest", [run("newest", "running"), run("latest", "succeeded"), run("older", "failed")])).toBe("older");
  });

  it("点的那次已经不在历史里了就回到跟随,不停在一个不存在的 id 上", () => {
    expect(viewedRunId("gone", "latest", [run("latest", "succeeded")])).toBe("latest");
  });
});
