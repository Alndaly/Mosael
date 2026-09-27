import { useQuery } from "@tanstack/react-query";
import { Box } from "lucide-react";

import { getScene, type GenerationOption, type SceneReferenceForm, type SceneReferenceUse } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { OptionPicker } from "@/components/ui/option-picker";
import { supportsParameter } from "@/lib/generationCapabilities";

/** 每种用法要模型收的那个素材角色(和后端 scenes._USE_ROLES 同一张表)。 */
const USE_ROLE: Record<SceneReferenceUse, string> = {
  composition: "reference_image",
  frames: "first_frame",
  motion: "reference_video",
};
const USE_LABEL: Record<SceneReferenceUse, MessageKey> = {
  composition: "boardSceneRefComposition",
  frames: "boardSceneRefFrames",
  motion: "boardSceneRefMotion",
};

/** 这个模型、这种格子能怎么用一个 3D 场景 —— 只列它收得下的(描述符说了算)。首尾帧和运镜只给视频。 */
export function sceneReferenceUses(model: GenerationOption | null, kind: string): SceneReferenceUse[] {
  const uses: SceneReferenceUse[] = kind === "video" ? ["composition", "frames", "motion"] : ["composition"];
  return uses.filter((use) => supportsParameter(model, USE_ROLE[use]));
}

/**
 * 生成格上的「3D 参考」(ADR 0029 §2):连进来的是一个 3D 场景,这里挑**哪个镜头、怎么用**。
 *
 * 跑的时候服务端现渲这个镜头(场景此刻的修订),按用法挂成参考图 / 首尾帧 / 参考视频;镜头里看得见的人偶演的
 * 人物一并带上。模型一种都不收时说清楚,不给一个点了会被拒的选择。
 */
export function SceneReferencePicker({
  workspaceId,
  sceneId,
  uses,
  value,
  onChange,
}: {
  workspaceId: string;
  sceneId: string;
  uses: SceneReferenceUse[];
  value: SceneReferenceForm;
  onChange: (next: SceneReferenceForm) => void;
}) {
  const t = useI18n();
  const scene = useQuery({ queryKey: ["scene", workspaceId, sceneId], queryFn: () => getScene(workspaceId, sceneId) });
  const shots = scene.data?.content.shots ?? [];
  return (
    <div data-scene-reference="" className="flex min-w-0 flex-wrap items-center gap-2 rounded-md border border-border bg-secondary/30 px-2 py-1.5">
      <Box size={14} className="shrink-0 text-muted-foreground" />
      <span className="min-w-0 max-w-[12rem] truncate text-ui-xs text-foreground" title={scene.data?.name}>
        {t("boardSceneRefLabel").replace("{name}", scene.data?.name ?? "")}
      </span>
      {uses.length === 0 ? (
        <span data-scene-reference-unsupported="" className="text-ui-xs text-muted-foreground">
          {t("boardSceneRefUnsupported")}
        </span>
      ) : (
        <>
          {shots.length > 1 && (
            <OptionPicker
              ariaLabel={t("boardSceneRefShot")}
              size="sm"
              value={value.shot_id || ""}
              placeholder={t("boardSceneRefPickShot")}
              onChange={(shot_id) => onChange({ ...value, shot_id })}
              options={shots.map((shot) => ({ value: shot.id, label: shot.name }))}
            />
          )}
          <OptionPicker
            ariaLabel={t("boardSceneRefUse")}
            size="sm"
            value={uses.includes(value.use) ? value.use : uses[0]}
            onChange={(use) => onChange({ ...value, use: use as SceneReferenceUse })}
            options={uses.map((use) => ({ value: use, label: t(USE_LABEL[use]) }))}
          />
        </>
      )}
    </div>
  );
}
