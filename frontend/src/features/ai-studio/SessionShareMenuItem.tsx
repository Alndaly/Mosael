import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Users2 } from "lucide-react";

import { setResourceShared } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { ContextMenuItem } from "@/components/ui/context-menu";

/**
 * 「把这次对话给同事看 / 收回」。
 *
 * 对话和生成记录默认只有自己看得见(见后端 domain/sharing.KINDS),要给别人看是主人的一个显式
 * 动作。抽成组件而不是在两处会话列表里各写一遍 —— 它们本来就是逐字重复的,再复制一份共享
 * 逻辑只会让其中一处先长歪。
 */
/** 对话与生成记录是同一类东西:某人的私人工作线程。共享逻辑因此也只有一份。 */
type SharableSession = { id: string; is_mine: boolean; shared: boolean };

export function SessionShareMenuItem({
  session,
  kind,
  workspaceId,
  queryKey,
}: {
  session: SharableSession;
  kind: "agent_session" | "generation_session";
  workspaceId: string;
  queryKey: string;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const share = useMutation({
    mutationFn: (shared: boolean) => setResourceShared(kind, session.id, workspaceId, shared),
    onSuccess: () => void qc.invalidateQueries({ queryKey: [queryKey, workspaceId] }),
  });

  if (!session.is_mine) return null; // 别人的对话:能看,但共享与否是他的事
  return (
    <ContextMenuItem onSelect={() => share.mutate(!session.shared)}>
      <Users2 /> {session.shared ? t("sessionUnshare") : t("sessionShare")}
    </ContextMenuItem>
  );
}
