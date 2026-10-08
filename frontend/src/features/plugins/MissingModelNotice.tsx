import React from "react";
import { useQuery } from "@tanstack/react-query";

import { listPluginPackages } from "@/api/client";
import type { MissingGenerationModel } from "@/api/domains/generation";
import { useI18n } from "@/app/preferences";
import { MissingModelNote } from "@/components/generation/MissingModelNote";
import { Button } from "@/components/ui/button";
import { WorkflowLibraryDialog } from "@/features/plugins/WorkflowLibrary";
import { missingModelNames } from "@/lib/entryNames";

/**
 * 记着的生成模型用不了时的那一块(AI Studio 的会话、画板格子、工作流的生成节点共用,ADR 0045 修订之一):名字、原因,
 * 和两条出路 —— 修法是升级的(ComfyUI 上那张工作流的表单还是上一版格式)就地打开那个连接的工作流库:横幅和「查看并升级」
 * 都在那儿,升级完生成选项重拉,这一处自己恢复;「换一个模型」交给调用方(把焦点送到模型下拉)。
 */
export function MissingModelNotice({
  missing,
  pending,
  workspaceId,
  onPickAnother,
  className,
}: {
  missing: MissingGenerationModel | null;
  pending: boolean;
  workspaceId: string;
  onPickAnother?: () => void;
  className?: string;
}) {
  const t = useI18n();
  const upgradeIn = missing?.upgrade && missing.plugin_instance_id ? missing.plugin_instance_id : "";
  return (
    <MissingModelNote
      names={missingModelNames(missing, t)}
      reason={missing?.reason ?? null}
      pending={pending}
      className={className}
      actions={upgradeIn || onPickAnother ? (
        <>
          {upgradeIn && <UpgradeInLibrary instanceId={upgradeIn} workspaceId={workspaceId} />}
          {onPickAnother && (
            <Button type="button" size="xs" variant="ghost" onClick={onPickAnother} data-model-missing-pick="">
              {t("genModelMissingPickAnother")}
            </Button>
          )}
        </>
      ) : undefined}
    />
  );
}

/** 「去工作流库升级」:就地打开那个连接的工作流库(和插件页那颗按钮开的是同一个窗口)。 */
function UpgradeInLibrary({ instanceId, workspaceId }: { instanceId: string; workspaceId: string }) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const packages = useQuery({ queryKey: ["plugins"], queryFn: () => listPluginPackages() });
  const instance = (packages.data ?? []).flatMap((one) => one.instances ?? []).find((one) => one.id === instanceId) ?? null;
  return (
    <>
      <Button type="button" size="xs" variant="outline" loading={packages.isPending} disabled={!instance}
              onClick={() => setOpen(true)} data-model-missing-upgrade="">
        {t("genModelMissingUpgrade")}
      </Button>
      {open && instance && (
        <WorkflowLibraryDialog open onOpenChange={(next) => !next && setOpen(false)} instance={instance} workspaceId={workspaceId} />
      )}
    </>
  );
}
