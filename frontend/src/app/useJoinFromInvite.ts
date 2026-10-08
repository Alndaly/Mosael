import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { redeemInviteLink, removeMember } from "@/api/client";
import { workspaceKeys } from "@/api/queryKeys";
import { useAuth } from "@/app/auth";
import { useI18n } from "@/app/preferences";
import { clearPendingInvite, usePendingInvite } from "@/lib/inviteLinks";

/**
 * 登录之后兑现待处理的那张邀请链接(ADR 0054 D51):直接加入那个工作区、切过去,toast 写主人和角色,能「撤销」(退出,
 * 切回原来那个)。注册时已经凭它进来的,后端照样回那个工作区(兑现对用过它的那个人是幂等的)。
 *
 * 回「正在兑现」:工作区那一层据此先不摆「建第一个工作区」—— 刚注册、还没切过去的那一刻,列表可能还是空的。
 */
export function useJoinFromInvite(selectWorkspace: (id: string) => void, currentWorkspaceId: string | null): boolean {
  const t = useI18n();
  const qc = useQueryClient();
  const { user } = useAuth();
  const code = usePendingInvite();
  //: 兑现之前所在的那个工作区:撤销时切回去。
  const previous = React.useRef<string | null>(null);
  const redeem = useMutation({
    mutationFn: (value: string) => redeemInviteLink(value),
    onSuccess: async (joined) => {
      clearPendingInvite();
      await qc.invalidateQueries({ queryKey: workspaceKeys.all() });
      selectWorkspace(joined.workspace_id);
      const role = t(`role_${joined.role}` as never) as string;
      const description = t("inviteJoinedDetail").replace("{owner}", joined.owner_name).replace("{role}", role);
      if (joined.already_member) {
        toast.success(t("inviteAlreadyMember").replace("{name}", joined.workspace_name), { description });
        return;
      }
      const back = previous.current;
      toast.success(t("inviteJoined").replace("{name}", joined.workspace_name), {
        description,
        action: {
          label: t("inviteJoinUndo"),
          onClick: () => {
            if (!user) return;
            void removeMember(joined.workspace_id, user.id).then(
              async () => {
                await qc.invalidateQueries({ queryKey: workspaceKeys.all() });
                if (back) selectWorkspace(back);
                toast.success(t("inviteJoinUndone").replace("{name}", joined.workspace_name));
              },
              (error: Error) => toast.error(error.message),
            );
          },
        },
      });
    },
    onError: (error: Error) => {
      clearPendingInvite();
      toast.error(t("inviteJoinFailed"), { description: error.message });
    },
  });
  const { mutate, isPending } = redeem;
  const current = React.useRef(currentWorkspaceId);
  current.current = currentWorkspaceId;
  React.useEffect(() => {
    if (!code) return;
    previous.current = current.current;
    mutate(code);
  }, [code, mutate]);
  return Boolean(code) || isPending;
}
