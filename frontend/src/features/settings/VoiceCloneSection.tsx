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
  const engineValue = form.watch("engine");
  // 这个引擎能用哪些下载源,后端说了算 —— F5 要的 vocos 在 ModelScope 上没有。
  const sources = (models.data ?? []).find((item) => item.id === engineValue)?.sources ?? [];
  const engineLabel = (models.data ?? []).find((item) => item.id === engineValue)?.label ?? engineValue;

  // **归一化放在 reset 这一步**,让表单里存的就是下拉显示得出来的那个值。
  //
  // 此前是把归一化包在下拉的 `value=` 上,于是表单里是 modelscope、下拉显示 hf —— 两者不一致。
  // Radix Select 会用一次 `onValueChange("")` 来"纠正"这种不一致,而 react-hook-form 把它
  // 记成一次用户改动:一个字没动,页面却说「改了还没保存」,而下拉显示的又不是存着的那个值。
  // 用户看到的就是「保存点了没用」「每次进来都要再存一次」。真机上抓到的渲染序列:
  //   source='hf-mirror'(默认值) → 'modelscope'(reset) → ''(Radix 纠正) + dirty
  //
  // 等 sources 到齐再落:它是异步来的,空着的时候归一化不出任何东西(见 normalizeSource)。
  //: 归一化要用**配置里那个引擎**的选项,不是表单当前那个。表单的 engine 也要等 reset,
  //: 所以第一次 reset 时 `sources` 还是默认引擎(f5)的 —— 拿它去归一化 fish 存着的
  //: modelscope,会落成 hf,然后引擎一变又 reset 一次成 modelscope,而下拉早已挂载,
  //: 于是又撞上"挂载后从外部改 value"那一下。
  const savedSources = (models.data ?? []).find((item) => item.id === config.data?.engine)?.sources ?? [];
  const sourceKey = savedSources.join(",");
  //: 配置**已经落进表单**了没有。不是"数据到了没有"——数据到达和 reset 之间隔着一帧,
  //: 而下拉正是在那一帧挂载的(实测:sources 与 config 同帧到齐,Select 挂载时表单里还是默认值)。
  const [loaded, setLoaded] = React.useState(false);
  React.useEffect(() => {
    if (!config.data || savedSources.length === 0) return;
    form.reset({
      engine: config.data.engine,
      python_path: config.data.python_path,
      source: normalizeSource(config.data.source, savedSources),
      pip_index: config.data.pip_index ?? "",
      fish_repo_dir: config.data.fish_repo_dir ?? "",
      fish_model_dir: config.data.fish_model_dir ?? "",
    });
    setLoaded(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.data, sourceKey]);

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
    // **有未保存的改动就先存再下。** 下载读的是后端存着的配置,所以此前这里的做法是把按钮
    // 禁用掉、让用户先去页顶点「保存」。但用户改下载源**正是为了**重下 —— 意图很清楚,
    // 而他看到的是一个点不动的「重试」和一条离得老远的横幅(真机上的反馈就是"无法点击")。
    // 两步并成一步,顺序仍然是先存后下,读到的配置还是那份存下去的。
    mutationFn: async (id: string) => {
      if (form.formState.isDirty) {
        await save.mutateAsync(form.getValues());
      }
      return downloadTtsModel(id);
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["tts-models"] }),
    onError: (error: Error) => toast.error(error.message),
  });
  const busy = download.isPending || (models.data ?? []).some((m) => m.status === "downloading");
  // **上面选的 ≠ 已经生效的。** 下载用的是后端存着的那份配置,而不是这个表单里选中的。
  // 用户把「模型下载源」从镜像换成别的、没点保存就去点「重试」—— 跑的还是旧源,失败消息
  // 还是旧源那句,于是"我明明换了源"。改了没存时就直说,而不是让他去撞。
  const unsaved = form.formState.isDirty;
  // **横幅和底下的卡片必须给同一个答案。** 两者都问 models 里**被选中那个引擎**的那一行:
  // `status` 说权重在不在盘上,`runtime_ready` 说跑不跑得起来,`runtime_checked` 说这个
  // 答案算出来了没有。
  //
  // 此前横幅问的是配置级的 `worker_ready` —— 后端只对**已保存**的那个引擎算它,于是"在下拉
  // 里换一个引擎"必然得到"未就绪"。真机上就是这一幕:选 Fish Speech,横幅红着说它没装、
  // 让人去点下载,而同一页底下写着「Fish Speech S2 Pro · 11.0 GB · 已安装」,后端也回
  // `runtime_ready: true`。**拿一个回答不了这个问题的来源去回答它,只会得到假话。**
  const selected = form.watch("engine");
  const row = (models.data ?? []).find((item) => item.id === selected);
  // **解释器就绪 ≠ 能合成出真实音色**:前者只证明 `import f5_tts` 通得过,后者还要权重在盘上。
  const weightsReady = row?.status === "installed";
  const runtimeReady = Boolean(row?.runtime_ready);
  // 探测是后台跑的。**"还不知道"不能显示成"不行"** —— 那会让人去重下一个已经在盘上的模型。
  const runtimeChecking = Boolean(row) && !row?.runtime_checked;
  const ready = runtimeReady && weightsReady;
  // 解释器路径只对**已保存**的那个引擎成立(后端就是按它算的),换了还没存就别拿它当证据。
  const showsPython = ready && selected === config.data?.engine;

  return (
    <SettingsGroup title={t("voiceCloneTitle")} description={t("voiceCloneDesc")}>
      <SettingsBlock>
        {config.data && (
          <Alert variant={ready || runtimeChecking ? "default" : "destructive"}>
            {ready ? <CheckCircle2 size={14} /> : <CircleAlert size={14} />}
            <AlertDescription>
              {ready
                ? showsPython
                  ? t("voiceCloneReady").replace("{python}", config.data.worker_python)
                  : t("voiceCloneReadyOther").replace("{engine}", engineLabel)
                : runtimeChecking
                  ? t("runtimeChecking")
                  : runtimeReady
                    ? t("voiceCloneWeightsMissing").replace("{engine}", engineLabel)
                    : t("voiceCloneNotReady").replace("{engine}", engineLabel)}
            </AlertDescription>
          </Alert>
        )}

        <Form {...form}>
          <form className="grid gap-2.5 [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-ui-sm [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none" onSubmit={submit} noValidate>
            <FormField
              control={form.control}
              name="engine"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t("voiceCloneEngine")}</FormLabel>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="f5-tts">F5-TTS</SelectItem>
                      <SelectItem value="fish-speech">Fish Speech</SelectItem>
                    </SelectContent>
                  </Select>
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
                  {/* **选项和配置都到齐之前不挂载它。**
                      Radix Select 对「挂载之后从外部改 value」反应不正常:实测渲染序列是
                      `hf-mirror`(默认值) → `hf`(配置落下) → `''`(它自己清空并回调),
                      而 react-hook-form 把最后那一下记成用户改动。于是一个字没动,页面却说
                      「改了还没保存」,下拉显示的也不是存着的值 —— 用户看到的就是
                      「保存点了没用」「每次进来都要再存一次」。
                      等 reset **真的落进表单**了再挂(不是等数据到达——那中间隔着一帧,
                      下拉正好在那一帧挂载),它的 value 从一开始就是最终值,不存在"事后被改"。
                      不用「加 key 让它重挂」那招:重挂本身同样会带出一次 change。 */}
                  {!loaded ? (
                    // 占位不能用 SelectTrigger —— 它必须长在 Select 里面。
                    <div className="flex h-9 w-full items-center rounded-md border border-input bg-transparent px-3 py-2 text-sm text-muted-foreground">
                      {t("optionsLoading")}
                    </div>
                  ) : (
                    <Select
                      key={engineValue}
                      // 直接用表单里的值:reset 那一步已经归一化过,两者不再有不一致可言。
                      value={field.value}
                      onValueChange={field.onChange}
                    >
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {sources.map((id) => (
                          <SelectItem key={id} value={id}>
                            {SOURCE_LABELS[id] ?? id}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
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
                  <Select value={field.value || "pypi"} onValueChange={(value) => field.onChange(value === "pypi" ? "" : value)}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="pypi">{t("voiceClonePipPypi")}</SelectItem>
                      <SelectItem value="tsinghua">{t("voiceClonePipTsinghua")}</SelectItem>
                      <SelectItem value="aliyun">{t("voiceClonePipAliyun")}</SelectItem>
                      <SelectItem value="tencent">{t("voiceClonePipTencent")}</SelectItem>
                    </SelectContent>
                  </Select>
                  <FormDescription>{t("voiceClonePipIndexHint")}</FormDescription>
                </FormItem>
              )}
            />
            {/* 「改了还没保存」讲的是**这个表单**的状态,所以只说一次、说在「保存」旁边。
                此前每张引擎卡片下面各挂一遍,同一句话在一屏里出现两三次,读起来像是每个引擎
                各自出了问题。 */}
            <div className="mt-1 flex items-center justify-end gap-2">
              {unsaved && <small className="text-ui-xs text-muted-foreground">{t("ttsSaveAndDownload")}</small>}
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
          <div className="flex flex-wrap items-center gap-2 [&_strong]:text-ui-md">
            <strong>{model.label}</strong>
            {/* 「约」不是客套:这个数问不到下载源时退回的是目录里写死的估算,而用户会拿它当准数
                (然后发现进度条走到 93% 就完成了)。问到了就不带「约」—— 那才是实测。 */}
            <span className="text-ui-xs tabular-nums text-muted-foreground">
              {model.total_is_estimate ? t("sizeApprox").replace("{size}", formatBytes(model.expected_bytes)) : formatBytes(model.expected_bytes)}
            </span>
          </div>
          <small className="text-ui-xs text-muted-foreground">{model.detail}</small>
          {model.status === "installed" && !model.runtime_checked && (
            <small className="text-ui-xs text-muted-foreground">{t("runtimeChecking")}</small>
          )}
          {model.status === "installed" && model.runtime_checked && !model.runtime_ready && (
            <small className="text-ui-xs text-destructive">{t("voiceModelNoRuntime")}</small>
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
            <Button size="sm" variant="outline" disabled={busy} title={unsaved ? t("ttsSaveAndDownload") : undefined} onClick={onDownload}>
              <Download size={13} /> {t("asrModelInstallRuntime")}
            </Button>
          )}
          {model.status === "missing" && (
            <Button size="sm" variant="outline" disabled={busy} title={unsaved ? t("ttsSaveAndDownload") : undefined} onClick={onDownload}>
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
            <Button size="sm" variant="outline" disabled={busy} title={unsaved ? t("ttsSaveAndDownload") : undefined} onClick={onDownload}>
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
              <div className="flex items-center justify-between gap-2 text-ui-xs tabular-nums text-muted-foreground">
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
            <div className="flex items-center gap-1.5 text-ui-xs text-muted-foreground">
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
        <div className="flex items-center gap-1.5 text-ui-xs text-destructive">
          <AlertCircle size={13} /> {model.message}
        </div>
      )}
    </div>
  );
}
