import React from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/transport";
import type { Scene, SceneContent } from "@/api/domains/scenes";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "sonner";

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
          <DialogTitle>场景版本记录</DialogTitle>
        </DialogHeader>
        <p className="text-ui-sm text-muted-foreground">
          恢复会保存为新版本，已有历史仍然保留。
        </p>
        <div className="scene-history">
          {list.error && <p role="alert">{list.error.message}</p>}
          {list.data?.map((r) => (
            <div key={r.revision}>
              <span>
                版本 {r.revision} · {r.name}
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
                    .catch((e) => toast.error(String(e)))
                }
              >
                恢复
              </Button>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
