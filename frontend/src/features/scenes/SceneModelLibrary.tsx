import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { deleteSceneModel, type SceneModel } from "@/api/domains/scenes";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { ConfirmDialog, ModalShell, NoticeDialog } from "@/components/app/modals";
import { IconButton } from "@/components/ui/icon-button";
import { Truncate } from "@/components/ui/truncate";
import { formatBytes } from "@/lib/bytes";

/**
 * 工作区的模型库:导入过的 GLB / glTF 一行一份,在这里删。
 *
 * 模型归工作区、不归某个场景(导一次,哪个场景都摆得上),所以它没有"随场景一起删"的时机 —— 此前界面上
 * 就没有任何地方能删它,只能越攒越多。删除的守卫在后端:**还有已保存的场景摆着它就拒**,并说出是哪几个;
 * 拒了用 NoticeDialog 照实说原因,不在确认框里换字(见 modals.tsx 的说明)。
 *
 * 后端只看得见已保存的场景。眼前这个场景还没保存的改动里摆着的那几份(`inDraft`),这里直接不给删 ——
 * 否则删完当场就在视口里留一个加载失败的空位。
 */
export function SceneModelLibrary({
  workspaceId,
  models,
  inDraft,
  open,
  onOpenChange,
}: {
  workspaceId: string;
  models: SceneModel[];
  /** 当前场景(含未保存改动)里摆着的模型 id。 */
  inDraft: ReadonlySet<string>;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [target, setTarget] = React.useState<SceneModel | null>(null);
  const [refusal, setRefusal] = React.useState("");
  const remove = useMutation({
    mutationFn: (model: SceneModel) => deleteSceneModel(workspaceId, model.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["scene-models", workspaceId] }),
    onError: (e) => setRefusal(errorText(e)),
    onSettled: () => setTarget(null),
  });

  return (
    <>
      <ModalShell open={open} onOpenChange={onOpenChange} title={t("sceneModelLibraryTitle")}>
        {models.length ? (
          <ul className="divide-y divide-border" data-scene-model-library>
            {models.map((model) => {
              const placedHere = inDraft.has(model.id);
              return (
                <li key={model.id} className="flex items-center gap-2 py-2" data-scene-model={model.id}>
                  <div className="min-w-0 flex-1">
                    <Truncate className="text-sm">{model.name}</Truncate>
                    <div className="text-xs text-muted-foreground">
                      {placedHere
                        ? t("sceneModelPlacedHere")
                        : `${model.format.toUpperCase()} · ${formatBytes(model.size)}`}
                    </div>
                  </div>
                  <IconButton
                    variant="ghost"
                    size="icon-sm"
                    label={t("sceneModelDelete").replace("{name}", model.name)}
                    disabled={placedHere}
                    onClick={() => setTarget(model)}
                  >
                    <Trash2 size={15} />
                  </IconButton>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="py-2 text-sm text-muted-foreground">{t("sceneModelLibraryEmpty")}</p>
        )}
      </ModalShell>
      <ConfirmDialog
        open={!!target}
        title={t("sceneModelDeleteTitle").replace("{name}", target?.name ?? "")}
        body={t("sceneModelDeleteBody")}
        confirmLabel={t("delete")}
        pending={remove.isPending}
        onCancel={() => setTarget(null)}
        onConfirm={() => target && remove.mutate(target)}
      />
      <NoticeDialog
        open={!!refusal}
        title={t("sceneModelDeleteRefused")}
        body={refusal}
        onClose={() => setRefusal("")}
      />
    </>
  );
}
