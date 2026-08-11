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
import { formatBytes, formatSpeed } from "@/lib/bytes";
import { pollWhileUnsettled } from "@/features/settings/pollWhileUnsettled";


type ConfigForm = { engine: string; python_path: string; source: string; pip_index: string; fish_repo_dir: string; fish_model_dir: string };

/** Settings → 声音克隆:选引擎、指定装了 f5-tts 的 Python 解释器、下载源,并下载
    引擎权重。装好并配好后合成即为真实音色;否则回退占位音。 */
const SOURCE_LABELS: Record<string, string> = {
  "hf-mirror": "HF 镜像 (hf-mirror.com)",
  hf: "HuggingFace",
  modelscope: "ModelScope",
};

/**
 * 受控下拉的值**必须**是列得出来的某一项 —— 这是 Radix Select 的硬约束:找不到对应 Item 时
 * 它会把值清成空串并回调出来,而 react-hook-form 把那记成一次"用户改动"。用户报的
 * 「每次刷新页面下载源都会变动,导致要重新保存」就是这么来的:表单一进页面自己变脏,
 * 顶上常驻「改了还没保存」,下拉还显示成一片空白。
 *
 * 所以:哪些源能选**由后端按引擎给**(ModelScope 上没有 F5 要的 vocos,列出来就是陷阱),
 * 而当前值一旦不在其中就落到第一项上。加上给 Select 一个随引擎变的 key —— 换引擎时整个
 * 重挂,不存在"值还在、对应项已经没了"的那一帧。
 */
export function normalizeSource(source: string, sources: readonly string[]): string {
  if (sources.length === 0) return source; // 还没拉到,先别动
  return sources.includes(source) ? source : sources[0];
}

export function VoiceCloneSection() {
  const t = useI18n();
  const qc = useQueryClient();
  const config = useQuery({ queryKey: ["tts-config"], queryFn: getTtsConfig });
  const models = useQuery({
    queryKey: ["tts-models"],
    queryFn: listTtsModels,
    refetchInterval: (query) => pollWhileUnsettled(query.state.data),
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
  const engineValue = form.watch("engine");
  // 这个引擎能用哪些下载源,后端说了算 —— F5 要的 vocos 在 ModelScope 上没有。
  const sources = (models.data ?? []).find((item) => item.id === engineValue)?.sources ?? [];
  const engineLabel = (models.data ?? []).find((item) => item.id === engineValue)?.label ?? engineValue;

  const save = useMutation({
    // 存下去的就是显示出来的那一个 —— 归一化只有一处实现。
    mutationFn: (values: ConfigForm) =>
      updateTtsConfig({ ...values, source: normalizeSource(values.source, sources) }),
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
  // **上面选的 ≠ 已经生效的。** 下载用的是后端存着的那份配置,而不是这个表单里选中的。
  // 用户把「模型下载源」从镜像换成别的、没点保存就去点「重试」—— 跑的还是旧源,失败消息
  // 还是旧源那句,于是"我明明换了源"。改了没存时就直说,而不是让他去撞。
  const unsaved = form.formState.isDirty;
  // worker_ready 是后端针对「已保存」的引擎算的。选了别的引擎但还没保存时,对新引擎无从谈就绪
  // (要保存后 config 重取才知道)——所以选中引擎 ≠ 已保存引擎时按未就绪处理,顶部提醒也随之
  // 对应下拉里「选中」的引擎,而不再固定显示旧的已保存引擎(选 Fish Speech 却提示 F5-TTS 的根因)。
  const runtimeReady = (config.data?.worker_ready ?? false) && form.watch("engine") === config.data?.engine;
  // **解释器就绪 ≠ 能合成出真实音色**:前者只证明 `import f5_tts` 通得过,后者还要权重在盘上。
  // 此前横幅只看前者,于是这台机器上出现了自相矛盾的一页:顶上说「引擎已就绪,合成为真实音色」,
  // 底下同一页的卡片说「下载未完成,可能引擎未安装」—— 而权重目录里确实只有一个空的 refs/main。
  const weightsReady =
    (models.data ?? []).find((item) => item.id === form.watch("engine"))?.status === "installed";
  const ready = runtimeReady && weightsReady;

  return (
    <SettingsGroup title={t("voiceCloneTitle")} description={t("voiceCloneDesc")}>
      <SettingsBlock>
        {config.data && (
          <Alert variant={ready ? "default" : "destructive"}>
            {ready ? <CheckCircle2 size={14} /> : <CircleAlert size={14} />}
            <AlertDescription>
              {ready
                ? t("voiceCloneReady").replace("{python}", config.data.worker_python)
                : runtimeReady
                  ? t("voiceCloneWeightsMissing").replace("{engine}", engineLabel)
                  : t("voiceCloneNotReady").replace("{engine}", engineLabel)}
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
                    <Select
                      key={engineValue}
                      value={normalizeSource(field.value, sources)}
                      onValueChange={field.onChange}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {sources.map((id) => (
                          <SelectItem key={id} value={id}>
                            {SOURCE_LABELS[id] ?? id}
                          </SelectItem>
                        ))}
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
            {/* 「改了还没保存」讲的是**这个表单**的状态,所以只说一次、说在「保存」旁边。
                此前每张引擎卡片下面各挂一遍,同一句话在一屏里出现两三次,读起来像是每个引擎
                各自出了问题。 */}
            <div className="mt-1 flex items-center justify-end gap-2">
              {unsaved && <small className="text-[11.5px] text-muted-foreground">{t("ttsSaveFirst")}</small>}
              <Button type="submit" size="sm" loading={save.isPending}>
                {t("save")}
              </Button>
            </div>
          </form>
        </Form>
      </SettingsBlock>

      <SettingsBlock>
        <div className="grid gap-2">
          {models.data?.map((model) => (
            <EngineCard key={model.id} model={model} busy={busy} unsaved={unsaved} onDownload={() => download.mutate(model.id)} />
          ))}
        </div>
      </SettingsBlock>
    </SettingsGroup>
  );
}

function EngineCard({ model, busy, unsaved, onDownload }: { model: TtsEngine; busy?: boolean; unsaved?: boolean; onDownload: () => void }) {
  const t = useI18n();
  const pct = model.total_bytes > 0 ? Math.min(100, Math.round((model.downloaded_bytes / model.total_bytes) * 100)) : 0;
  const downloading = model.status === "downloading";
  return (
    <div className={cn("grid gap-2 rounded-lg border border-border bg-background px-3 py-2.5", model.status === "installed" && "border-[color-mix(in_oklab,var(--primary)_30%,var(--border))]")}>
      <div className="flex items-start justify-between gap-3">
        <div className="grid min-w-0 gap-[3px]">
          <div className="flex flex-wrap items-center gap-2 [&_strong]:text-[13px]">
            <strong>{model.label}</strong>
            <span className="text-[11px] tabular-nums text-muted-foreground">{formatBytes(model.expected_bytes)}</span>
          </div>
          <small className="text-[11.5px] text-muted-foreground">{model.detail}</small>
          {model.status === "installed" && !model.runtime_checked && (
            <small className="text-[11.5px] text-muted-foreground">{t("runtimeChecking")}</small>
          )}
          {model.status === "installed" && model.runtime_checked && !model.runtime_ready && (
            <small className="text-[11.5px] text-destructive">{t("voiceModelNoRuntime")}</small>
          )}

        </div>
        <div className="shrink-0">
          {/* **两件事分开说**:权重在不在盘上(status),和跑不跑得起来(runtime_ready)。
              转写那边刚修过同一个坑:此前这里只看前者,页面写着「已安装」,一点合成却说
              「没有可用的引擎」—— 而用户最容易做的事是去重下已经在盘上的那几个 GB。 */}
          {model.status === "installed" && model.runtime_checked && model.runtime_ready && (
            <span className="inline-flex items-center gap-[5px] text-xs font-medium text-primary">
              <CheckCircle2 size={14} /> {t("asrModelInstalled")}
            </span>
          )}
          {model.status === "installed" && model.runtime_checked && !model.runtime_ready && (
            <Button size="sm" variant="outline" disabled={busy || unsaved} title={unsaved ? t("ttsSaveFirst") : undefined} onClick={onDownload}>
              <Download size={13} /> {t("asrModelInstallRuntime")}
            </Button>
          )}
          {model.status === "missing" && (
            <Button size="sm" variant="outline" disabled={busy || unsaved} title={unsaved ? t("ttsSaveFirst") : undefined} onClick={onDownload}>
              <Download size={13} /> {t("asrModelDownload")}
            </Button>
          )}
          {downloading && (
            // 没有分母的阶段(装运行环境)不报百分比 —— 一个恒定的「0%」和"卡住了"长得一样。
            <span className="inline-flex items-center gap-[5px] text-xs tabular-nums text-muted-foreground">
              <Loader2 size={13} className="animate-openstudio-spin" />
              {model.total_bytes > 0 ? `${pct}%` : ""}
            </span>
          )}
          {model.status === "failed" && (
            <Button size="sm" variant="outline" disabled={busy || unsaved} title={unsaved ? t("ttsSaveFirst") : undefined} onClick={onDownload}>
              <RotateCw size={13} /> {t("asrModelRetry")}
            </Button>
          )}
        </div>
      </div>
      {downloading && (
        <div className="grid gap-[5px]">
          {/* **装运行环境和下权重是两件事**,量纲也不同:前者跑的是 pip(装 torch 等,几 GB
              但我们不知道总量),后者才是这个引擎的 1.5GB。没有分母时就别画进度条、也别摆
              「0 MB / 1.5 GB」—— 那个数是权重的,而此刻在跑的不是它,于是它看着就像卡住了。 */}
          {model.total_bytes > 0 ? (
            <>
              <Progress value={pct} />
              <div className="flex items-center justify-between gap-2 text-[11px] tabular-nums text-muted-foreground">
                <span>
                  {formatBytes(model.downloaded_bytes)} / {formatBytes(model.total_bytes)}
                </span>
                <span>
                  {formatSpeed(model.speed_bps)}
                  {model.speed_bps > 0 && model.message ? " · " : ""}
                  {model.message}
                </span>
              </div>
            </>
          ) : (
            <div className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
              {/* 没有分母时,分子和速度仍然值得说 —— 「已下载 5.2 GB · 12.4 MB/s」比一个
                  光转的圈有用得多,而且它是判断"卡住没有"的唯一依据。 */}
              <Loader2 size={12} className="shrink-0 animate-openstudio-spin" />
              {model.downloaded_bytes > 0 && (
                <span className="tabular-nums">{formatBytes(model.downloaded_bytes)}</span>
              )}
              {model.speed_bps > 0 && <span className="tabular-nums">{formatSpeed(model.speed_bps)}</span>}
              <span className="min-w-0 truncate">{model.message}</span>
            </div>
          )}
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
