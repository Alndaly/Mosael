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
import { cn } from "@/lib/utils";

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

type ConfigForm = { engine: string; python_path: string; source: string; pip_index: string; fish_repo_dir: string; fish_model_dir: string };

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
        pip_index: z.string(),
        fish_repo_dir: z.string(),
        fish_model_dir: z.string(),
      }),
    ),
    defaultValues: { engine: "f5-tts", python_path: "", source: "hf-mirror", pip_index: "", fish_repo_dir: "", fish_model_dir: "" },
  });
  React.useEffect(() => {
    if (config.data) {
      form.reset({
        engine: config.data.engine,
        python_path: config.data.python_path,
        source: config.data.source,
        pip_index: config.data.pip_index ?? "",
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
  // worker_ready 是后端针对「已保存」的引擎算的。选了别的引擎但还没保存时,对新引擎无从谈就绪
  // (要保存后 config 重取才知道)——所以选中引擎 ≠ 已保存引擎时按未就绪处理,顶部提醒也随之
  // 对应下拉里「选中」的引擎,而不再固定显示旧的已保存引擎(选 Fish Speech 却提示 F5-TTS 的根因)。
  const ready = (config.data?.worker_ready ?? false) && form.watch("engine") === config.data?.engine;

  return (
    <SettingsGroup title={t("voiceCloneTitle")} description={t("voiceCloneDesc")}>
      <SettingsBlock>
        {config.data && (
          <Alert variant={ready ? "default" : "destructive"}>
            {ready ? <CheckCircle2 size={14} /> : <CircleAlert size={14} />}
            <AlertDescription>
              {ready
                ? t("voiceCloneReady").replace("{python}", config.data.worker_python)
                : t("voiceCloneNotReady").replace("{engine}", isFish ? "Fish Speech" : "F5-TTS")}
            </AlertDescription>
          </Alert>
        )}

        <Form {...form}>
          <form className="grid gap-2.5 [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none" onSubmit={submit} noValidate>
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
            {/* 与「模型下载源」分开:那个管 HF 权重从哪拉,这个管 Python 依赖从哪拉。
                装引擎要拉 2.5–3.5GB,国内直连 PyPI 常常慢到不可用。 */}
            <FormField
              control={form.control}
              name="pip_index"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t("voiceClonePipIndex")}</FormLabel>
                  <FormControl>
                    <Select value={field.value || "pypi"} onValueChange={(value) => field.onChange(value === "pypi" ? "" : value)}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="pypi">{t("voiceClonePipPypi")}</SelectItem>
                        <SelectItem value="tsinghua">{t("voiceClonePipTsinghua")}</SelectItem>
                        <SelectItem value="aliyun">{t("voiceClonePipAliyun")}</SelectItem>
                        <SelectItem value="tencent">{t("voiceClonePipTencent")}</SelectItem>
                      </SelectContent>
                    </Select>
                  </FormControl>
                  <FormDescription>{t("voiceClonePipIndexHint")}</FormDescription>
                </FormItem>
              )}
            />
            <div className="mt-1 flex justify-end gap-1.5">
              <Button type="submit" size="sm" disabled={save.isPending}>
                {t("save")}
              </Button>
            </div>
          </form>
        </Form>
      </SettingsBlock>

      <SettingsBlock>
        <div className="grid gap-2">
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
    <div className={cn("grid gap-2 rounded-lg border border-border bg-background px-3 py-2.5", model.status === "installed" && "border-[color-mix(in_oklab,var(--primary)_30%,var(--border))]")}>
      <div className="flex items-start justify-between gap-3">
        <div className="grid min-w-0 gap-[3px]">
          <div className="flex flex-wrap items-center gap-2 [&_strong]:text-[13px]">
            <strong>{model.label}</strong>
            <span className="text-[11px] tabular-nums text-muted-foreground">{fmtBytes(model.expected_bytes)}</span>
          </div>
          <small className="text-[11.5px] text-muted-foreground">{model.detail}</small>
        </div>
        <div className="shrink-0">
          {model.status === "installed" && (
            <span className="inline-flex items-center gap-[5px] text-xs font-medium text-primary">
              <CheckCircle2 size={14} /> {t("asrModelInstalled")}
            </span>
          )}
          {model.status === "missing" && (
            <Button size="sm" variant="outline" disabled={busy} onClick={onDownload}>
              <Download size={13} /> {t("asrModelDownload")}
            </Button>
          )}
          {downloading && (
            <span className="inline-flex items-center gap-[5px] text-xs tabular-nums text-muted-foreground">
              <Loader2 size={13} className="animate-openstudio-spin" /> {pct}%
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
        <div className="grid gap-[5px]">
          <Progress value={pct} />
          <div className="flex items-center justify-between gap-2 text-[11px] tabular-nums text-muted-foreground">
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
        <div className="flex items-center gap-1.5 text-[11.5px] text-destructive">
          <AlertCircle size={13} /> {model.message}
        </div>
      )}
    </div>
  );
}
