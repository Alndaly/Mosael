import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Box } from "lucide-react";
import { listScenes, type SceneSummary } from "@/api/domains/scenes";
import { useI18n, usePreferences } from "@/app/preferences";
import { PickListDialog } from "@/components/app/PickListDialog";
import { relativeTime } from "@/lib/time";

/**
 * 从画板上挑一个已有的 3D 场景。
 *
 * 和 `NotePickerDialog` 同一个弹窗(PickListDialog),只有一处不同:**筛选在前端做**。
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
  const { locale } = usePreferences();
  const [search, setSearch] = React.useState("");
  const scenes = useQuery({
    queryKey: ["scene-picker", workspaceId],
    queryFn: () => listScenes(workspaceId),
    enabled: open,
  });
  const keyword = search.trim().toLowerCase();
  const matches = React.useMemo(
    () => (scenes.data ?? []).filter((scene) => !keyword || scene.name.toLowerCase().includes(keyword)),
    [scenes.data, keyword],
  );
  return (
    <PickListDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("boardScenePick")}
      description={t("boardScenePickHint")}
      searchLabel={t("boardSceneSearch")}
      query={search}
      onQueryChange={setSearch}
      items={matches}
      itemKey={(scene) => scene.id}
      row={(scene) => ({
        lead: <Box size={16} />,
        title: scene.name,
        subtitle: t("boardSceneMeta")
          .replace("{objects}", String(scene.object_count))
          .replace("{shots}", String(scene.shot_count)),
        meta: relativeTime(scene.updated_at, locale),
      })}
      onPick={(scene) => {
        onPick(scene);
        onOpenChange(false);
      }}
      pending={scenes.isPending}
      error={scenes.isError ? scenes.error.message : null}
      onRetry={() => void scenes.refetch()}
      empty={{
        icon: <Box size={24} strokeWidth={1.5} />,
        text: t(scenes.data?.length ? "boardSceneNoMatches" : "boardSceneNone"),
      }}
    />
  );
}
