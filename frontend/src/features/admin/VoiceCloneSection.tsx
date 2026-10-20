import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { CheckCircle2, CircleAlert } from "lucide-react";
import { toast } from "sonner";

import {
  downloadTtsModel,
  getTtsConfig,
  listTtsModels,
  updateTtsConfig,
} from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Form, FormField } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SETTINGS_FIELD_WIDTH } from "@/components/settings/settings-layout";
import type { TtsEngine } from "@/api/domains/speech";
import { pollWhileUnsettled } from "@/lib/pollWhileUnsettled";
import { ADMIN_CARD, AdminRow, AdminSection } from "./adminLayout";
import { ModelDownloadRow } from "./ModelDownloadRow";


type ConfigForm = { engine: string; python_path: string; fish_repo_dir: string; fish_model_dir: string };

/**
 * 这张权重表同时装着**两种能力**的引擎,所以按能力分两区渲染。
 *
 * **能力从哪儿来?** `/api/tts/models` 没有能力字段。`clones_voices` 长在 `/api/voices/engines` 上,
 * 语义是"能把配音库里的嗓子复刻到远端"(目前只有百炼 CosyVoice),**不是**"零样本克隆/预置音色" ——
 * 拿它分组会把这一节分错。所以这里认后端引擎目录(`ai/runtime/tts_models.CATALOG`)的 id:
 * f5-tts / fish-speech 是克隆引擎,qwen-tts 是预置音色引擎。新增引擎时要在这里表态;认不出的
 * 落到预置音色那一区 —— 至少不会被误标成"能克隆"。
 */
const CLONE_ENGINE_IDS = new Set(["f5-tts", "fish-speech"]);

function clonesFromReference(engineId: string): boolean {
  return CLONE_ENGINE_IDS.has(engineId);
}

/** 权重表的一个能力分区:组头(小标题 + 一句说明)+ 那一组的行。
 *  分组**只**是渲染时的分区 —— 下载、状态、进度、失败、重试仍是同一份 ModelDownloadRow 和同一个 mutation。 */
function EngineGroup({
  kind,
  title,
  description,
  children,
}: {
  kind: "clone" | "preset";
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section data-engine-group={kind} aria-label={title} className="grid min-w-0 gap-2">
      <div className="grid min-w-0 gap-0.5">
        <h3 className="m-0 text-ui-sm font-semibold leading-snug">{title}</h3>
        <p className="m-0 text-ui-xs leading-normal text-muted-foreground">{description}</p>
      </div>
      <div className={ADMIN_CARD}>{children}</div>
    </section>
  );
}

/** 管理 → 引擎 → 语音合成引擎:选默认克隆引擎、指定装了引擎的 Python 解释器,并下载引擎权重。这几项存在整台部署
    共用的那一行 TtsConfig 里,写入只给部署管理员(routes/voices.set_tts_config:解释器路径会进子进程的 argv;
    下载同理),所以在管理页。**模型下载源不在这里**:本机识别(NSFW)、Mosael 起的本机 ComfyUI 下模型读的也是它,
    它是这一页顶上「下载源」里的一行(体检 UM-16)。 */
export function VoiceCloneSection() {
  const t = useI18n();
  const qc = useQueryClient();
  const config = useQuery({
    queryKey: ["tts-config"],
    queryFn: getTtsConfig,
    // 解释器探测是后台跑的(要起子进程 import f5_tts,实测 7 秒),所以这个接口**不等**它,
    // 先回「还没测」。没测完就隔一会儿再问一次,否则那句「已就绪 · 解释器 …」永远补不上。
    refetchInterval: (query) => (query.state.data && query.state.data.worker_checked === false ? 1500 : false),
  });
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
        fish_repo_dir: z.string(),
        fish_model_dir: z.string(),
      }),
    ),
    defaultValues: { engine: "f5-tts", python_path: "", fish_repo_dir: "", fish_model_dir: "" },
  });
  const engineValue = form.watch("engine");
  const engineLabel = (models.data ?? []).find((item) => item.id === engineValue)?.label ?? engineValue;

  React.useEffect(() => {
    if (!config.data) return;
    form.reset({
      engine: config.data.engine,
      python_path: config.data.python_path,
      fish_repo_dir: config.data.fish_repo_dir ?? "",
      fish_model_dir: config.data.fish_model_dir ?? "",
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.data]);

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
  // **只看这一个引擎自己在不在下**,不看别人。它们各有各的 venv 和权重目录、跑在各自的
  // 一次性子进程里,同时装不会互相弄坏 —— 而"一个在下,所有按钮都变灰"此前正是这么来的。
  const startingId = download.isPending ? download.variables : null;
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
  // 还要求真的拿到了路径:探测没跑完时后端回的是空串,而「已就绪 · 解释器 」后面跟一片空白
  // 比不显示更糟 —— 那看起来像解释器路径丢了。
  const showsPython = ready && selected === config.data?.engine && Boolean(config.data?.worker_python);

  // 权重表按能力分两区。**只在这里过滤,不在别处再抄一遍**:行本身仍是那个 ModelDownloadRow。
  const engineModels = models.data ?? [];
  const cloneModels = engineModels.filter((model) => clonesFromReference(model.id));
  const presetModels = engineModels.filter((model) => !clonesFromReference(model.id));
  // **同一个渲染器给两组用** —— 两组只是分区,不是两套下载/状态逻辑。
  const renderModelRow = (model: TtsEngine) => {
    const busy = startingId === model.id || model.status === "downloading";
    const preset = !clonesFromReference(model.id);
    return (
      <div key={model.id}>
        <ModelDownloadRow
          model={model}
          noRuntimeText={t("voiceModelNoRuntime")}
          busy={busy}
          // **禁用了就要说为什么。** 按钮此前只是静静地变灰 —— 用户看到的是"点了没反应",
          // 而不是"这一个正在下"。和「重试点不动」是同一类:不给理由的禁用等于坏掉。
          busyReason={t("ttsThisDownloading")}
          actionHint={unsaved ? t("ttsSaveAndDownload") : undefined}
          onDownload={() => download.mutate(model.id)}
        />
        {/* 预置音色引擎**不在这里切换**。不写这句的话,用户装好 Qwen3-TTS、在这张表里看到
            「已安装」,却只在上面的「默认克隆引擎」里找它 —— 那个下拉按后端只收 f5-tts/fish-speech,
            它本来就不属于那里。指路要指向真实存在的入口:剪辑台的「配音」、创作页的「语音」。 */}
        {preset && (
          <p className="m-0 px-4 pb-3 text-ui-xs leading-normal text-muted-foreground">
            {t("voiceClonePickElsewhere")}
          </p>
        )}
      </div>
    );
  };

  return (
    <AdminSection
      id="engine-clone"
      title={t("voiceCloneTitle")}
      description={t("voiceCloneDesc")}
      actions={
        <>
          {/* 「改了还没保存」讲的是**这个表单**的状态,所以只说一次、说在「保存」旁边。
              此前每张引擎卡片下面各挂一遍,同一句话在一屏里出现两三次,读起来像是每个引擎
              各自出了问题。 */}
          {unsaved && <small className="text-ui-xs text-muted-foreground">{t("ttsSaveAndDownload")}</small>}
          <Button size="sm" loading={save.isPending} onClick={submit}>
            {t("save")}
          </Button>
        </>
      }
    >
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
        <form className={ADMIN_CARD} onSubmit={submit} noValidate>
          <FormField
            control={form.control}
            name="engine"
            render={({ field }) => (
              <AdminRow label={t("voiceCloneEngine")}>
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger className={SETTINGS_FIELD_WIDTH} aria-label={t("voiceCloneEngine")}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="f5-tts">F5-TTS</SelectItem>
                    <SelectItem value="fish-speech">Fish Speech</SelectItem>
                  </SelectContent>
                </Select>
              </AdminRow>
            )}
          />
          <FormField
            control={form.control}
            name="python_path"
            render={({ field }) => (
              <AdminRow label={t("voiceCloneInterpreter")} description={t("voiceCloneInterpreterHint")}>
                <Input
                  className={SETTINGS_FIELD_WIDTH}
                  aria-label={t("voiceCloneInterpreter")}
                  placeholder="/path/to/venv/bin/python"
                  {...field}
                />
              </AdminRow>
            )}
          />
          {/* pip 镜像、模型下载源不在这里 —— 它们是这一页顶上的「下载源」。转写、人声分离装依赖读的也是 pip 那一行,
              本机识别、本机 ComfyUI 下模型读的也是模型下载源;挂在克隆名下时,想给它们换源的人得来「声音克隆」里找。 */}
        </form>
      </Form>

      {engineModels.length > 0 && (
        <div className="grid min-w-0 gap-4">
          {cloneModels.length > 0 && (
            <EngineGroup
              kind="clone"
              title={t("voiceCloneGroupClones")}
              description={t("voiceCloneGroupClonesDesc")}
            >
              {cloneModels.map(renderModelRow)}
            </EngineGroup>
          )}
          {presetModels.length > 0 && (
            <EngineGroup
              kind="preset"
              title={t("voiceCloneGroupPreset")}
              description={t("voiceCloneGroupPresetDesc")}
            >
              {presetModels.map(renderModelRow)}
            </EngineGroup>
          )}
        </div>
      )}
    </AdminSection>
  );
}
