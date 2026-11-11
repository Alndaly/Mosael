import React from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { MessageCircle } from "lucide-react";
import { toast } from "sonner";

import { drawEntity, fetchWorkflowFieldOptions, type Entity } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { OptionPicker } from "@/components/ui/option-picker";
import { entryNamedOptions } from "@/lib/entryNames";
import { Textarea } from "@/components/ui/textarea";
import { gotoSettings } from "@/lib/deepLink";
import { useWatchedJob } from "@/lib/useWatchedJob";

/**
 * 人物资产「让它说话」(ADR 0028 §4):用它自己的音色给一段话配音,再用它的正面图做一段说话的视频。
 *
 * 和画板上人物资产格的那一项能力是同一个执行器(后端 entity_speak)。**门槛在服务端**:真人要有授权声明、要有音色、
 * 要有图、要有会「说话照片」的视频模型 —— 点「开始」先由服务端查一遍,说不通的原因就写在这个弹窗里,不起任务。
 * 做完由任务中心说一声(视频在素材库里,任务详情里能直接看)。
 */
export function SpeakButton({ entity, workspaceId }: { entity: Entity; workspaceId: string }) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const job = useWatchedJob();
  return (
    <>
      <Button variant="outline" loading={job.running} onClick={() => setOpen(true)} data-entity-speak="">
        {!job.running && <MessageCircle />}
        {t(job.running ? "entitySpeakRunning" : "entitySpeak")}
      </Button>
      {open && (
        <SpeakDialog
          entity={entity}
          workspaceId={workspaceId}
          onClose={() => setOpen(false)}
          onStarted={(jobId) => {
            setOpen(false);
            job.watch(jobId);
            toast.info(t("entitySpeakStarted"));
          }}
        />
      )}
    </>
  );
}

function SpeakDialog({
  entity,
  workspaceId,
  onClose,
  onStarted,
}: {
  entity: Entity;
  workspaceId: string;
  onClose: () => void;
  onStarted: (jobId: string) => void;
}) {
  const t = useI18n();
  const [text, setText] = React.useState("");
  const [model, setModel] = React.useState("");
  const models = useQuery({
    queryKey: ["field-options", "speech_video_models", workspaceId],
    queryFn: () => fetchWorkflowFieldOptions("speech_video_models", workspaceId),
  });
  const options = React.useMemo(() => entryNamedOptions(models.data ?? [], t), [models.data, t]);
  const effectiveDefault = options.find((one) => one.is_default) ?? options[0];
  React.useEffect(() => {
    if (!model && effectiveDefault) setModel(effectiveDefault.value);
  }, [effectiveDefault, model]);
  const pickerOptions = React.useMemo(() => options.map((one) => (
    one.value === effectiveDefault?.value
      ? { ...one, label: `${one.label} · ${t("entitySpeakDefaultBadge")}` }
      : one
  )), [effectiveDefault, options, t]);
  const selectedOption = options.find((one) => one.value === model);
  const start = useMutation({
    mutationFn: () =>
      drawEntity(entity.id, { ability: "speak", text: text.trim(), model, scope: "missing", expressions: "" }),
    onSuccess: (job) => onStarted(job.id),
  });
  const noModels = models.isSuccess && models.data.length === 0;
  return (
    <ModalShell
      open
      onOpenChange={(next) => !next && onClose()}
      title={t("entitySpeakTitle").replace("{name}", entity.name)}
      className="w-[min(32rem,calc(100vw-2rem))]"
      footer={
        <>
          <Button variant="outline" disabled={start.isPending} onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button disabled={noModels || !model || !text.trim()} loading={start.isPending} onClick={() => start.mutate()}>
            {t("entitySpeakStart")}
          </Button>
        </>
      }
    >
      <div className="grid gap-4" data-speak-dialog="">
        <p className="m-0 text-ui-sm leading-relaxed text-muted-foreground">{t("entitySpeakHint")}</p>
        <label className="grid gap-1.5">
          <span className="text-ui-sm font-medium">{t("entitySpeakText")}</span>
          <Textarea
            value={text}
            onChange={(event) => setText(event.target.value)}
            rows={4}
            maxLength={4000}
            placeholder={t("entitySpeakPlaceholder")}
            aria-label={t("entitySpeakText")}
          />
        </label>
        <label className="grid gap-1.5">
          <span className="text-ui-sm font-medium">{t("entitySpeakModel")}</span>
          {noModels ? (
            <span className="text-ui-sm leading-relaxed text-muted-foreground">
              {t("entitySpeakNoModel")}{" "}
              <button type="button" className="cursor-pointer border-0 bg-transparent p-0 text-primary hover:underline" onClick={() => gotoSettings("providers:video")}>
                {t("entityDrawOpenSettings")}
              </button>
            </span>
          ) : (
            <>
              <OptionPicker
                ariaLabel={t("entitySpeakModel")}
                value={model}
                onChange={setModel}
                options={pickerOptions}
              />
              {selectedOption?.description && (
                <span className="text-ui-xs text-muted-foreground">
                  <InlineMarkdown text={selectedOption.description} links={false} />
                </span>
              )}
            </>
          )}
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
