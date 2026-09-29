import { useQuery } from "@tanstack/react-query";
import { Box } from "lucide-react";
import React from "react";

import { getScene, type GenerationOption, type SceneReferenceForm, type SceneReferenceUse } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { OptionPicker } from "@/components/ui/option-picker";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { supportsParameter } from "@/lib/generationCapabilities";
import { cn } from "@/lib/utils";

/** 每种用法要模型收的那个素材角色(和后端 domain/scenes/operations._USE_ROLES 同一张表)。 */
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

/** 连进来的场景:名字和镜头(和编辑器、场景格同一个查询键,改了场景一处刷新处处跟上)。没连场景时不查。 */
export function useReferencedScene(workspaceId: string, sceneId: string | undefined) {
  const scene = useQuery({
    queryKey: ["scene", workspaceId, sceneId ?? ""],
    queryFn: () => getScene(workspaceId, sceneId ?? ""),
    enabled: Boolean(sceneId),
  });
  const data = scene.data;
  return React.useMemo(
    () => (data ? { name: data.name, shots: (data.content?.shots ?? []).map((shot) => ({ id: shot.id, name: shot.name })) } : undefined),
    [data],
  );
}

/** 这次用哪个镜头:挑过的还在场景里就是它;场景只有一个镜头时就是那一个;否则还没挑(不猜)。 */
export function resolvedShot(scene: { shots: { id: string }[] } | undefined, chosen: string): string {
  if (!scene) return chosen;
  if (scene.shots.some((shot) => shot.id === chosen)) return chosen;
  return scene.shots.length === 1 ? scene.shots[0].id : "";
}

/**
 * 生成格上的「3D 参考」(ADR 0029 §2):连进来的是一个 3D 场景。和旁边挂着的参考素材一样是**一枚芯片** ——
 * 场景名、镜头、用法写在上面,点开再挑。此前是两个铺满整行的下拉,把提示词挤到了下面(用户截图)。
 *
 * 跑的时候服务端现渲这个镜头(场景此刻的修订),按用法挂成参考图 / 首尾帧 / 参考视频;镜头里看得见的人偶演的
 * 人物一并带上。好几个镜头却没挑、模型一种用法都不收时,芯片上就说,生成按钮也是灰的。
 */
export function SceneReferencePicker({
  scene,
  uses,
  value,
  onChange,
}: {
  scene: { name: string; shots: { id: string; name: string }[] } | undefined;
  uses: SceneReferenceUse[];
  value: SceneReferenceForm;
  onChange: (next: SceneReferenceForm) => void;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const shots = scene?.shots ?? [];
  const shot = resolvedShot(scene, value.shot_id);
  const use = uses.includes(value.use) ? value.use : uses[0];
  const needsShot = Boolean(scene) && !shot;
  const unsupported = uses.length === 0;
  const shotName = shots.find((one) => one.id === shot)?.name;
  const summary = unsupported
    ? t("boardSceneRefUnsupported")
    : [needsShot ? t("boardSceneRefPickShot") : shots.length > 1 ? shotName : "", use ? t(USE_LABEL[use]) : ""].filter(Boolean).join(" · ");
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-scene-reference=""
          data-scene-reference-state={unsupported ? "unsupported" : needsShot ? "needs-shot" : "ready"}
          title={t("boardSceneRefHint")}
          className={cn(
            "inline-flex h-8 max-w-[18rem] shrink-0 cursor-pointer items-center gap-1.5 rounded-md border-0 px-2 text-ui-xs",
            unsupported || needsShot ? "bg-warning/10 text-warning" : "bg-primary/10 text-primary",
          )}
        >
          <Box size={13} className="shrink-0" />
          <span className="min-w-0 truncate">{scene?.name ?? t("boardKindScene")}</span>
          {summary && <span className="min-w-0 shrink-0 truncate opacity-80">· {summary}</span>}
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="grid w-[280px] gap-3 p-3">
        <div className="grid gap-0.5">
          <span className="text-ui-sm font-medium text-foreground">{t("boardSceneRefLabel").replace("{name}", scene?.name ?? "")}</span>
          <span className="text-ui-xs leading-relaxed text-muted-foreground">{t("boardSceneRefHint")}</span>
        </div>
        {unsupported ? (
          <p data-scene-reference-unsupported="" className="m-0 text-ui-xs leading-relaxed text-warning">
            {t("boardSceneRefUnsupported")}
          </p>
        ) : (
          <>
            {shots.length > 1 && (
              <label className="grid gap-1">
                <span className="text-ui-xs text-muted-foreground">{t("boardSceneRefShot")}</span>
                <OptionPicker
                  ariaLabel={t("boardSceneRefShot")}
                  size="sm"
                  value={shot}
                  placeholder={t("boardSceneRefPickShot")}
                  onChange={(shot_id) => onChange({ ...value, shot_id })}
                  options={shots.map((one) => ({ value: one.id, label: one.name }))}
                />
              </label>
            )}
            <label className="grid gap-1">
              <span className="text-ui-xs text-muted-foreground">{t("boardSceneRefUse")}</span>
              <OptionPicker
                ariaLabel={t("boardSceneRefUse")}
                size="sm"
                value={use ?? ""}
                onChange={(next) => onChange({ ...value, use: next as SceneReferenceUse })}
                options={uses.map((one) => ({ value: one, label: t(USE_LABEL[one]) }))}
              />
            </label>
          </>
        )}
      </PopoverContent>
    </Popover>
  );
}
