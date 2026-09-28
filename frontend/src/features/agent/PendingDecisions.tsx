import { InlineConfirmations } from "@/features/agent/InlineConfirmations";
import { InlineQuestions } from "@/features/agent/InlineQuestions";

/**
 * 这个会话里**等人拍板**的两种卡:确认卡问「这件事能不能做」,选择卡问「你要哪一个」。
 *
 * 两者总是一起出现、一起挪:两个对话入口(AI 工作台、画布助手)都放,工作台的对话 / 轨迹 / 子代理
 * 视图也都放。此前每处各写一对,轨迹视图就是漏写了才让两张卡一切视图就消失的。
 */
export function PendingDecisions({ workspaceId, sessionId }: { workspaceId: string; sessionId: string }) {
  return (
    <>
      <InlineConfirmations workspaceId={workspaceId} allowKey={sessionId} />
      <InlineQuestions sessionId={sessionId} />
    </>
  );
}
