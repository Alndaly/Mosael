import React from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/transport";
import type { Scene, SceneContent } from "@/api/domains/scenes";
import { errorText } from "@/api/errorMessage";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import { useI18n } from "@/app/preferences";

export function SceneHistory({
  scene,
  open,
  onClose,
  onRestore,
}: {
  scene: Scene;
  open: boolean;
  onClose: () => void;
  onRestore: (value: { name: string; content: SceneContent }) => void;
}) {
  const t = useI18n();
  const list = useQuery({
    queryKey: ["scene-revisions", scene.id, open],
    queryFn: () =>
      api<{ revision: number; name: string; created_at: string }[]>(
        `/api/scenes/${scene.id}/revisions?workspace_id=${scene.workspace_id}`,
      ),
    enabled: open,
  });
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (!value) onClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("sceneHistoryTitle")}</DialogTitle>
        </DialogHeader>
        <p className="text-ui-sm text-muted-foreground">
          {t("sceneHistoryHint")}
        </p>
        <div className="scene-history">
          {list.error && <p role="alert">{list.error.message}</p>}
          {list.data?.map((r) => (
            <div key={r.revision}>
              <span>
                {t("sceneHistoryRevision").replace("{n}", String(r.revision))} · {r.name}
                <small>{new Date(r.created_at).toLocaleString()}</small>
              </span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() =>
                  void api<{ name: string; content: SceneContent }>(
                    `/api/scenes/${scene.id}/revisions/${r.revision}?workspace_id=${scene.workspace_id}`,
                  )
                    .then(onRestore)
                    .catch((e) => toast.error(errorText(e)))
                }
              >
                {t("sceneHistoryRestore")}
              </Button>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
