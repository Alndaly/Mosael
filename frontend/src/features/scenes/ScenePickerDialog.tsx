import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Box, Search } from "lucide-react";
import { listScenes, type SceneSummary } from "@/api/domains/scenes";
import { useI18n } from "@/app/preferences";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LoadingState } from "@/components/layout/LoadingState";

/**
 * 从画板上挑一个已有的 3D 场景。
 *
 * 和 `NotePickerDialog` 是同一套形状,只有一处不同:**筛选在前端做**。
 * `/api/scenes` 不收关键字,而它返回的是整个工作区的场景列表 —— 场景是"搭出来的",
 * 一个工作区里通常是几个到几十个,不是笔记那种成百上千。为这点体量去后端加一个搜索参数,
 * 换来的是多一条要维护的接口路径。
 */
export function ScenePickerDialog({
  workspaceId,
  open,
  onOpenChange,
  onPick,
}: {
  workspaceId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onPick: (scene: SceneSummary) => void;
}) {
  const t = useI18n();
  const [search, setSearch] = React.useState("");
  const scenes = useQuery({
    queryKey: ["scene-picker", workspaceId],
    queryFn: () => listScenes(workspaceId),
    enabled: open,
  });
  const keyword = search.trim().toLowerCase();
  const matches = (scenes.data ?? []).filter(
    (scene) => !keyword || scene.name.toLowerCase().includes(keyword),
  );
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[min(36rem,calc(100dvh-2rem))] max-w-xl flex-col gap-4 overflow-hidden">
        <DialogHeader>
          <DialogTitle>{t("boardScenePick")}</DialogTitle>
          <DialogDescription>{t("boardScenePickHint")}</DialogDescription>
        </DialogHeader>
        <div className="relative">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            className="pl-9"
            aria-label={t("boardSceneSearch")}
            placeholder={t("boardSceneSearch")}
            value={search}
            maxLength={160}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          {scenes.isPending ? (
            <LoadingState />
          ) : scenes.isError ? (
            <div role="alert" className="m-auto text-center text-ui-sm text-muted-foreground">
              {scenes.error.message}
              <Button variant="ghost" onClick={() => void scenes.refetch()}>
                {t("retry")}
              </Button>
            </div>
          ) : !matches.length ? (
            <div className="m-auto flex flex-col items-center gap-3 py-8 text-center text-muted-foreground">
              <Box size={28} strokeWidth={1.5} />
              <span>{t(scenes.data.length ? "boardSceneNoMatches" : "boardSceneNone")}</span>
            </div>
          ) : (
            matches.map((scene) => (
              <button
                key={scene.id}
                className="flex shrink-0 items-start gap-3 rounded-lg p-3 text-left transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => {
                  onPick(scene);
                  onOpenChange(false);
                }}
              >
                <Box size={18} className="mt-1 shrink-0 text-primary" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-ui-sm font-medium">{scene.name}</span>
                  <span className="mt-2 block text-ui-2xs text-muted-foreground">
                    {t("boardSceneMeta")
                      .replace("{objects}", String(scene.object_count))
                      .replace("{shots}", String(scene.shot_count))}{" "}
                    · {new Date(scene.updated_at).toLocaleDateString()}
                  </span>
                </span>
              </button>
            ))
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
