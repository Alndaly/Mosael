import React from "react";

import { useI18n } from "@/app/preferences";
import { ConfirmDialog, DIALOG_FIELD } from "@/components/app/modals";
import { Input } from "@/components/ui/input";

/**
 * 删工作区:**把名字打一遍才能删**。它是全应用最不可逆的一步(项目、素材、成员一起没了),此前却和批量删素材一样
 * 只有一个泛泛的「确认」,手快的人一路回车就下去了(体检 UM-26)。切换器每一行的垃圾桶和设置 → 团队与成员的
 * 「删除工作区」都走这一个。
 */
export function DeleteWorkspaceDialog({
  workspace,
  pending,
  onCancel,
  onConfirm,
}: {
  /** 要删的那个;null 就是没开。 */
  workspace: { name: string } | null;
  pending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const t = useI18n();
  const [typed, setTyped] = React.useState("");
  const name = workspace?.name ?? "";
  React.useEffect(() => setTyped(""), [workspace]);
  return (
    <ConfirmDialog
      open={workspace !== null}
      title={t("deleteWorkspace")}
      body={t("deleteWorkspaceConfirm").replace("{name}", name)}
      confirmLabel={t("deleteWorkspacePermanently")}
      confirmDisabled={typed.trim() !== name}
      pending={pending}
      onCancel={onCancel}
      onConfirm={onConfirm}
    >
      <label className={DIALOG_FIELD}>
        <span>{t("deleteWorkspaceTypeName").replace("{name}", name)}</span>
        <Input autoFocus autoComplete="off" value={typed} onChange={(event) => setTyped(event.currentTarget.value)} />
      </label>
    </ConfirmDialog>
  );
}
