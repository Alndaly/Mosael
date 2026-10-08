import {
  AGENT_ROW_CLASS,
  AGENT_ROW_ICON_CLASS,
  AGENT_ROW_TEXT_CLASS,
  AGENT_TEXT_BLOCK_CLASS,
  AGENT_TURN_BLOCKS_CLASS,
  CHAT_ASSISTANT_ROW_CLASS,
  CHAT_USER_PILL_CLASS,
  CHAT_USER_ROW_CLASS,
  MESSAGE_FOOTER_ROW_CLASS,
} from "@/features/agent/agentRow";
import { Marker, MarkerContent, MarkerIcon } from "@/components/ui/marker";
import { Skeleton, SkeletonLine } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * 第一次打开一段对话、消息还没到时的样子:用户气泡、助手那一轮(一行工具、几行字)两来回。**外壳就是真气泡那几个类**
 * (CHAT_USER_ROW_CLASS、CHAT_USER_PILL_CLASS、CHAT_ASSISTANT_ROW_CLASS、工具行的 Marker、正文块、脚注那一行),每一行字占一行字的高度
 * (SkeletonLine),消息到了原地换上 —— 此前这里是正中间一个「正在载入」,消息一到整屏从中间换到顶上。
 */
export function ChatTranscriptSkeleton() {
  const user = (width: string) => (
    <div className={CHAT_USER_ROW_CLASS} data-skeleton-bubble="user">
      <div className={CHAT_USER_PILL_CLASS}>
        <SkeletonLine className={width} />
      </div>
      <div className={MESSAGE_FOOTER_ROW_CLASS} />
    </div>
  );
  const assistant = (lines: string[], tool: boolean) => (
    <div className={CHAT_ASSISTANT_ROW_CLASS} data-skeleton-bubble="assistant">
      <div className={AGENT_TURN_BLOCKS_CLASS}>
        {tool && (
          <div className={cn("flex w-full min-w-0 flex-col gap-1 self-stretch", AGENT_ROW_TEXT_CLASS)}>
            <Marker className={AGENT_ROW_CLASS}>
              <MarkerIcon className="inline-flex items-center justify-center">
                <Skeleton className={cn(AGENT_ROW_ICON_CLASS, "rounded-full")} />
              </MarkerIcon>
              <MarkerContent className="flex min-w-0 flex-1 items-baseline">
                <SkeletonLine className="w-44" />
              </MarkerContent>
            </Marker>
          </div>
        )}
        <div className={AGENT_TEXT_BLOCK_CLASS}>
          {lines.map((width, index) => (
            <SkeletonLine key={index} className={width} />
          ))}
        </div>
      </div>
      <div className={MESSAGE_FOOTER_ROW_CLASS} />
    </div>
  );
  return (
    <div className="contents" aria-hidden data-chat-skeleton="">
      {user("w-48")}
      {assistant(["w-full", "w-11/12", "w-2/3"], true)}
      {user("w-32")}
      {assistant(["w-full", "w-1/2"], false)}
    </div>
  );
}
