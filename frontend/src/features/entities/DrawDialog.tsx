import React from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Rotate3d, Smile, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { drawEntity, fetchWorkflowFieldOptions, type Entity, type EntityDrawRequest } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { OptionPicker } from "@/components/ui/option-picker";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { gotoSettings } from "@/lib/deepLink";
import { useWatchedJob } from "@/lib/useWatchedJob";

/** 「AI 补画」管的那两种(「让它说话」是另一个入口,见 SpeakDialog)。 */
export type DrawAbility = Exclude<EntityDrawRequest["ability"], "speak">;

/**
 * 这种资产能让 AI 补画什么。**三种不是一个模板**:人物补角度、画表情;场景的角度是机位(全景 / 反打 / 俯视),
 * 没有表情;道具补角度。和画板上资产格的能力是同一件事(后端 entity_angles / entity_expressions 两个节点)。
 */
export function drawAbilitiesFor(kind: Entity["kind"]): DrawAbility[] {
  return kind === "character" ? ["angles", "expressions"] : ["angles"];
}

const ABILITY_ICONS: Record<DrawAbility, typeof Rotate3d> = { angles: Rotate3d, expressions: Smile };
const ABILITY_LABELS: Record<DrawAbility, MessageKey> = { angles: "entityDrawAngles", expressions: "entityDrawExpressions" };
/** 每一项说它会画什么 —— 补全多角度按种类说(场景画的是机位)。 */
const ABILITY_HINTS: Record<`${DrawAbility}_${Entity["kind"]}`, MessageKey> = {
  angles_character: "entityDrawAnglesHint_character",
  angles_location: "entityDrawAnglesHint_location",
  angles_prop: "entityDrawAnglesHint_prop",
  expressions_character: "entityDrawExpressionsHint",
  expressions_location: "entityDrawExpressionsHint",
  expressions_prop: "entityDrawExpressionsHint",
};

const DEFAULT_MODEL = "__default__";

/**
 * 参考图墙上的「AI 补画」:照现有的参考图再画几张同一个,画好按角度挂回这面墙。
 *
 * 画是一个后台任务(每一张是一次付费生成):点「开始」先由服务端把话说清楚(没图、模型不收参考图、角度都齐了
 * 就当场说,不起任务),起了之后按钮忙着,做完由任务中心说一声、刷新这面墙(任务目录里写着它改动资产库)。
 */
export function DrawMenu({ entity, workspaceId, disabled }: { entity: Entity; workspaceId: string; disabled?: boolean }) {
  const t = useI18n();
  const [menuOpen, setMenuOpen] = React.useState(false);
  const [ability, setAbility] = React.useState<DrawAbility | null>(null);
  const job = useWatchedJob();
  const abilities = drawAbilitiesFor(entity.kind);
  return (
    <>
      <Popover open={menuOpen} onOpenChange={setMenuOpen}>
        <PopoverTrigger asChild>
          <Button variant="outline" disabled={disabled} loading={job.running} data-draw-menu="">
            {!job.running && <Sparkles />}
            {t(job.running ? "entityDrawRunning" : "entityDraw")}
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-[280px] p-1.5">
          <div className="grid gap-0.5">
            {abilities.map((one) => {
              const Icon = ABILITY_ICONS[one];
              return (
                <button
                  key={one}
                  type="button"
                  onClick={() => {
                    setMenuOpen(false);
                    setAbility(one);
                  }}
                  className="grid w-full cursor-pointer grid-cols-[auto_minmax(0,1fr)] items-start gap-x-2.5 gap-y-0.5 rounded-md border-0 bg-transparent px-2 py-2 text-left hover:bg-secondary"
                >
                  <Icon size={15} className="row-span-2 mt-0.5 text-muted-foreground" />
                  <span className="text-ui-sm font-medium text-foreground">{t(ABILITY_LABELS[one])}</span>
                  <span className="text-ui-xs leading-relaxed text-muted-foreground">{t(ABILITY_HINTS[`${one}_${entity.kind}`])}</span>
                </button>
              );
            })}
          </div>
        </PopoverContent>
      </Popover>
      {ability && (
        <DrawDialog
          entity={entity}
          workspaceId={workspaceId}
          ability={ability}
          onClose={() => setAbility(null)}
          onStarted={(jobId) => {
            setAbility(null);
            job.watch(jobId);
            toast.info(t("entityDrawStarted"));
          }}
        />
      )}
    </>
  );
}

function DrawDialog({
  entity,
  workspaceId,
  ability,
  onClose,
  onStarted,
}: {
  entity: Entity;
  workspaceId: string;
  ability: DrawAbility;
  onClose: () => void;
  onStarted: (jobId: string) => void;
}) {
  const t = useI18n();
  const [model, setModel] = React.useState(DEFAULT_MODEL);
  const [scope, setScope] = React.useState<EntityDrawRequest["scope"]>("missing");
  const [expressions, setExpressions] = React.useState("");
  const models = useQuery({
    queryKey: ["field-options", "reference_image_models", workspaceId],
    queryFn: () => fetchWorkflowFieldOptions("reference_image_models", workspaceId),
  });
  const start = useMutation({
    mutationFn: () =>
      drawEntity(entity.id, { ability, model: model === DEFAULT_MODEL ? "" : model, scope, expressions: expressions.trim(), text: "" }),
    onSuccess: (job) => onStarted(job.id),
  });
  const noModels = models.isSuccess && models.data.length === 0;
  return (
    <ModalShell
      open
      onOpenChange={(open) => !open && onClose()}
      title={t(ABILITY_LABELS[ability])}
      className="w-[min(30rem,calc(100vw-2rem))]"
      footer={
        <>
          <Button variant="outline" disabled={start.isPending} onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button disabled={noModels} loading={start.isPending} onClick={() => start.mutate()}>
            {t("entityDrawStart")}
          </Button>
        </>
      }
    >
      <div className="grid gap-4" data-draw-dialog={ability}>
        <p className="m-0 text-ui-sm leading-relaxed text-muted-foreground">{t(ABILITY_HINTS[`${ability}_${entity.kind}`])}</p>
        {ability === "angles" ? (
          <label className="grid gap-1.5">
            <span className="text-ui-sm font-medium">{t("entityDrawScope")}</span>
            <OptionPicker
              ariaLabel={t("entityDrawScope")}
              value={scope}
              onChange={(next) => setScope(next as EntityDrawRequest["scope"])}
              options={[
                { value: "missing", label: t("entityDrawScopeMissing") },
                { value: "all", label: t("entityDrawScopeAll") },
              ]}
            />
          </label>
        ) : (
          <label className="grid gap-1.5">
            <span className="text-ui-sm font-medium">{t("entityDrawExpressionList")}</span>
            <Input
              value={expressions}
              onChange={(event) => setExpressions(event.target.value)}
              placeholder={t("entityDrawExpressionPlaceholder")}
              aria-label={t("entityDrawExpressionList")}
            />
          </label>
        )}
        <label className="grid gap-1.5">
          <span className="text-ui-sm font-medium">{t("entityDrawModel")}</span>
          {noModels ? (
            <span className="text-ui-sm leading-relaxed text-muted-foreground">
              {t("entityDrawNoModel")}{" "}
              <button type="button" className="cursor-pointer border-0 bg-transparent p-0 text-primary hover:underline" onClick={() => gotoSettings("providers:image")}>
                {t("entityDrawOpenSettings")}
              </button>
            </span>
          ) : (
            <OptionPicker
              ariaLabel={t("entityDrawModel")}
              value={model}
              onChange={setModel}
              options={[{ value: DEFAULT_MODEL, label: t("entityDrawDefaultModel") }, ...(models.data ?? [])]}
            />
          )}
          <span className="text-ui-xs text-muted-foreground">{t("entityDrawModelHint")}</span>
        </label>
        {start.isError && (
          <p role="alert" className="m-0 text-ui-sm text-destructive">
            {errorText(start.error)}
          </p>
        )}
      </div>
    </ModalShell>
  );
}
