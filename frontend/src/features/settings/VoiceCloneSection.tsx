import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { AlertCircle, CheckCircle2, CircleAlert, Download, Loader2, RotateCw } from "lucide-react";
import { toast } from "sonner";

import {
  downloadTtsModel,
  getTtsConfig,
  listTtsModels,
  updateTtsConfig,
  type TtsEngine,
} from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SettingsBlock, SettingsGroup } from "@/features/settings/ui";

function fmtBytes(n: number): string {
  if (n <= 0) return "0 MB";
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)} GB`;
  return `${Math.round(n / 1_000_000)} MB`;
}
function fmtSpeed(bps: number): string {
  if (bps <= 0) return "";
  if (bps >= 1_000_000) return `${(bps / 1_000_000).toFixed(1)} MB/s`;
  return `${Math.round(bps / 1000)} KB/s`;
}

type ConfigForm = { engine: string; python_path: string; source: string; fish_repo_dir: string; fish_model_dir: string };

/** Settings → 声音克隆:选引擎、指定装了 f5-tts 的 Python 解释器、下载源,并下载
    引擎权重。装好并配好后合成即为真实音色;否则回退占位音。 */
export function VoiceCloneSection() {
  const t = useI18n();
  const qc = useQueryClient();
  const config = useQuery({ queryKey: ["tts-config"], queryFn: getTtsConfig });
  const models = useQuery({
    queryKey: ["tts-models"],
    queryFn: listTtsModels,
    refetchInterval: (query) => ((query.state.data ?? []).some((m) => m.status === "downloading") ? 1200 : false),
  });

  const form = useForm<ConfigForm>({
    resolver: zodResolver(
      z.object({
        engine: z.string(),
        python_path: z.string(),
        source: z.string(),
        fish_repo_dir: z.string(),
        fish_model_dir: z.string(),
      }),
    ),
    defaultValues: { engine: "f5-tts", python_path: "", source: "hf-mirror", fish_repo_dir: "", fish_model_dir: "" },
  });
  React.useEffect(() => {
    if (config.data) {
      form.reset({
        engine: config.data.engine,
        python_path: config.data.python_path,
        source: config.data.source,
        fish_repo_dir: config.data.fish_repo_dir ?? "",
        fish_model_dir: config.data.fish_model_dir ?? "",
      });
    }
  }, [config.data]);
  const isFish = form.watch("engine") === "fish-speech";

  const save = useMutation({
    mutationFn: (values: ConfigForm) => updateTtsConfig(values),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tts-config"] });
      toast.success(t("saved"));
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const submit = form.handleSubmit((values) => save.mutate(values));

  const download = useMutation({
    mutationFn: (id: string) => downloadTtsModel(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["tts-models"] }),
    onError: (error: Error) => toast.error(error.message),
  });
  const busy = download.isPending || (models.data ?? []).some((m) => m.status === "downloading");
  const ready = config.data?.worker_ready ?? false;

  return (
    <SettingsGroup title={t("voiceCloneTitle")} description={t("voiceCloneDesc")}>
      <SettingsBlock>
        {config.data && (
          <Alert variant={ready ? "default" : "destructive"}>
            {ready ? <CheckCircle2 size={14} /> : <CircleAlert size={14} />}
            <AlertDescription>
              {ready
                ? t("voiceCloneReady").replace("{python}", config.data.worker_python)
                : t("voiceCloneNotReady")
                    .replace("{engine}", config.data.engine === "fish-speech" ? "Fish Speech" : "F5-TTS")
                    .replace("{install}", config.data.engine === "fish-speech" ? t("voiceCloneInstallFish") : t("voiceCloneInstallF5"))}
            </AlertDescription>
          </Alert>
        )}

        <Form {...form}>
          <form className="task-create-form" onSubmit={submit} noValidate>
            <FormField
              control={form.control}
              name="engine"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t("voiceCloneEngine")}</FormLabel>
                  <FormControl>
                    <Select value={field.value} onValueChange={field.onChange}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="f5-tts">F5-TTS</SelectItem>
                        <SelectItem value="fish-speech">Fish Speech</SelectItem>
                      </SelectContent>
                    </Select>
                  </FormControl>
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="python_path"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t("voiceCloneInterpreter")}</FormLabel>
                  <FormControl>
                    <Input placeholder="/path/to/venv/bin/python" {...field} />
                  </FormControl>
                  <FormDescription>{t("voiceCloneInterpreterHint")}</FormDescription>
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="source"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t("voiceCloneSource")}</FormLabel>
                  <FormControl>
                    <Select value={field.value} onValueChange={field.onChange}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="hf-mirror">HF 镜像 (hf-mirror.com)</SelectItem>
                        <SelectItem value="hf">HuggingFace</SelectItem>
                        <SelectItem value="modelscope">ModelScope</SelectItem>
                      </SelectContent>
                    </Select>
                  </FormControl>
                </FormItem>
              )}
            />
            {isFish && (
              <>
                <FormField
                  control={form.control}
                  name="fish_repo_dir"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>{t("voiceCloneFishRepo")}</FormLabel>
                      <FormControl>
                        <Input placeholder="/path/to/fish-speech" {...field} />
                      </FormControl>
                      <FormDescription>{t("voiceCloneFishRepoHint")}</FormDescription>
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="fish_model_dir"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>{t("voiceCloneFishModel")}</FormLabel>
                      <FormControl>
                        <Input placeholder="/path/to/fish-speech-s2-pro" {...field} />
                      </FormControl>
                      <FormDescription>{t("voiceCloneFishModelHint")}</FormDescription>
                    </FormItem>
                  )}
                />
              </>
            )}
            <div className="task-create-actions">
              <Button type="submit" size="sm" disabled={save.isPending}>
                {t("save")}
              </Button>
            </div>
          </form>
        </Form>
      </SettingsBlock>

      <SettingsBlock>
        <div className="asr-model-list">
          {models.data?.map((model) => (
            <EngineCard key={model.id} model={model} busy={busy} onDownload={() => download.mutate(model.id)} />
          ))}
        </div>
      </SettingsBlock>
    </SettingsGroup>
  );
}

function EngineCard({ model, busy, onDownload }: { model: TtsEngine; busy?: boolean; onDownload: () => void }) {
  const t = useI18n();
  const pct = model.total_bytes > 0 ? Math.min(100, Math.round((model.downloaded_bytes / model.total_bytes) * 100)) : 0;
  const downloading = model.status === "downloading";
  return (
    <div className={`asr-model asr-model-${model.status}`}>
      <div className="asr-model-main">
        <div className="asr-model-info">
          <div className="asr-model-title">
            <strong>{model.label}</strong>
            <span className="asr-model-size">{fmtBytes(model.expected_bytes)}</span>
          </div>
          <small className="asr-model-detail">{model.detail}</small>
        </div>
        <div className="asr-model-action">
          {model.status === "installed" && (
            <span className="asr-model-ok">
              <CheckCircle2 size={14} /> {t("asrModelInstalled")}
            </span>
          )}
          {model.status === "missing" && (
            <Button size="sm" variant="outline" disabled={busy} onClick={onDownload}>
              <Download size={13} /> {t("asrModelDownload")}
            </Button>
          )}
          {downloading && (
            <span className="asr-model-progresslabel">
              <Loader2 size={13} className="spin" /> {pct}%
            </span>
          )}
          {model.status === "failed" && (
            <Button size="sm" variant="outline" disabled={busy} onClick={onDownload}>
              <RotateCw size={13} /> {t("asrModelRetry")}
            </Button>
          )}
        </div>
      </div>
      {downloading && (
        <div className="asr-model-progress">
          <Progress value={pct} />
          <div className="asr-model-progressmeta">
            <span>
              {fmtBytes(model.downloaded_bytes)} / {fmtBytes(model.total_bytes)}
            </span>
            <span>
              {fmtSpeed(model.speed_bps)}
              {model.speed_bps > 0 && model.message ? " · " : ""}
              {model.message}
            </span>
          </div>
        </div>
      )}
      {model.status === "failed" && (
        <div className="asr-model-error">
          <AlertCircle size={13} /> {model.message}
        </div>
      )}
    </div>
  );
}
