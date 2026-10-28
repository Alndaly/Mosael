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
import { SETTINGS_FIELD_WIDTH } from "@/components/settings/settings-layout";
import type { TtsConfig, TtsEngine } from "@/api/domains/speech";
import { pollWhileUnsettled } from "@/lib/pollWhileUnsettled";
import { ADMIN_CARD, AdminRow, AdminSection } from "./adminLayout";
import { AdminDefaultMarker, AdminDefaultSelect, AdminOnlyOneNote, hasDefaultChoice } from "./defaultRow";
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

/** 权重表的一个能力分区:组头(小标题 + 一句说明)+ 组里的「默认」那一个控件 + 那一组的行。
 *  分组**只**是渲染时的分区 —— 下载、状态、进度、失败、重试仍是同一份 ModelDownloadRow 和同一个 mutation。
 *  「默认」永远在组说明之后、列表之前(和转写那一节同一个位置),而且只属于这一组 —— 克隆引擎的默认
 *  不该挂在含预置音色引擎的整节顶上。
 *
 *  间距和 `AdminSection` 同一档(`gap-3`):转写、人声分离、降噪那几节里「默认」卡和列表卡隔 12px,
 *  这里是同一种结构,不能因为多包了一层就成了 8px —— 截图上一眼就能看出这一节"挤"。 */
function EngineGroup({
  kind,
  title,
  description,
  before,
  children,
}: {
  kind: "clone" | "preset";
  title: string;
  description: string;
  /** 组说明之后、列表之前的那一行(默认行 / 只有一种实现时的那句话)。 */
  before?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section data-engine-group={kind} aria-label={title} className="grid min-w-0 gap-3">
      <div className="grid min-w-0 gap-0.5">
        <h3 className="m-0 text-ui-sm font-semibold leading-snug">{title}</h3>
        <p className="m-0 text-ui-xs leading-normal text-muted-foreground">{description}</p>
      </div>
      {before}
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

  // **一份配置铺回表单,只有这一个地方。** GET 回来时用;设完默认时也用 —— 写接口回读的也是
  // 同一份配置(见 makeDefault)。分两处写,迟早有一处忘了新的那个字段。
  const applyConfig = (data: TtsConfig) => {
    form.reset({
      engine: data.engine,
      python_path: data.python_path,
      fish_repo_dir: data.fish_repo_dir ?? "",
      fish_model_dir: data.fish_model_dir ?? "",
    });
  };

  React.useEffect(() => {
    if (!config.data) return;
    applyConfig(config.data);
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

  // **默认克隆引擎就是 TtsConfig.engine 这一个字段**,写它的路只有这一条 —— 那个下拉已经拿掉,
  // 否则同一个默认会有两处可写。表单里有还没保存的解释器路径时**连同它一起存**(和下载那条路一样
  // 先存再做):只把 engine 写回去、把用户刚打的路径丢掉,比多存一次糟得多。
  const makeDefault = useMutation({
    mutationFn: (engineId: string) => updateTtsConfig({ ...form.getValues(), engine: engineId }),
    onSuccess: (saved) => {
      // **默认改成功了,表单里的 `engine` 必须立刻跟上。** 只把配置查询标脏不够:回读是**另一次**
      // 请求,而用户往往紧接着就点「保存」—— 那一瞬间表单里还是旧 engine,PUT 会把它当成当前值
      // 写回去,刚设的默认就被悄悄改回。写入时本来就把表单里所有字段一起发了(见上面那段说明),
      // 所以按**这次写入的回读**整张表单重置是对的:engine 跟上,刚存下的路径也不再是「没保存」。
      applyConfig(saved);
      void qc.invalidateQueries({ queryKey: ["tts-config"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

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
  // 默认克隆引擎 = TtsConfig.engine 这一个字段。它的**唯一写入口**是克隆组顶上那个选择器;
  // 配置/权重表还没到(options = undefined)时那个控件什么都不画(见 defaultRow)。
  const cloneOptions = config.data
    ? cloneModels.map((model) => ({
        id: model.id,
        label: model.label,
        //: 设默认看的是权重在不在盘上(status);运行环境探没探完是另一件事。
        installed: model.status === "installed",
      }))
    : undefined;
  const savedClone = cloneModels.some((model) => model.id === config.data?.engine) ? config.data?.engine : undefined;
  // **同一个渲染器给两组用** —— 两组只是分区,不是两套下载/状态逻辑。
  const renderModelRow = (model: TtsEngine) => {
    const busy = startingId === model.id || model.status === "downloading";
    const preset = !clonesFromReference(model.id);
    // 默认只属于克隆引擎,而且只在这一组有 ≥2 个候选时才存在(见 defaultRow);配置还没到就不猜。
    const canSetDefault = !preset && Boolean(config.data) && hasDefaultChoice(cloneModels.length);
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
          // 已默认只是名字右边**一枚 badge**,不可点、也不占右边状态槽:改默认在克隆组顶上那个
          // 选择器里(唯一可写处)。
          tags={canSetDefault && config.data?.engine === model.id ? <AdminDefaultMarker /> : null}
          onDownload={() => download.mutate(model.id)}
        />
        {/* 预置音色引擎**不在这里切换**。不写这句的话,用户装好 Qwen3-TTS、在这张表里看到
            「已安装」,却只在「默认克隆引擎」里找它 —— 那个名字按后端只收 f5-tts/fish-speech,
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
    <AdminSection id="engine-clone" title={t("voiceCloneTitle")} description={t("voiceCloneDesc")}>
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
          {/* **默认只在这一组顶上那个选择器里设,那是唯一可写处**(见 defaultRow)。表单里的
              `engine` 只是把已保存的默认原样带回去保存(它没有可改的控件),所以同一个默认
              不会有两个写入口。 */}
          <FormField
            control={form.control}
            name="python_path"
            render={({ field }) => (
              <AdminRow label={t("voiceCloneInterpreter")} description={t("voiceCloneInterpreterHint")}>
                {/* 控件格:输入框 + 保存 —— **和「FFmpeg 路径」那一行同一个语法**。此前保存飘在
                    节头,不属于任何一行,读的人得先猜它存的是哪张表单。保存是这张 `<form>` 的
                    提交键,所以写 `type="submit"`(棘轮:design/buttonTypes);尺寸用默认档,
                    和旁边的输入框一样高(棘轮:design/controlRhythm)。
                    「改了还没保存」讲的是**这个表单**的状态,所以只说一次、贴在这颗保存下面
                    (此前每张引擎卡片下面各挂一遍,同一句话一屏两三次,像是每个引擎各自出了问题)。 */}
                <div className="flex min-w-0 flex-col items-end gap-1">
                  <div className="flex min-w-0 items-center gap-2">
                    <Input
                      className={SETTINGS_FIELD_WIDTH}
                      aria-label={t("voiceCloneInterpreter")}
                      placeholder="/path/to/venv/bin/python"
                      {...field}
                    />
                    <Button type="submit" loading={save.isPending}>
                      {t("save")}
                    </Button>
                  </div>
                  {unsaved && (
                    <small className="max-w-72 text-right text-ui-xs leading-normal text-muted-foreground">
                      {t("ttsSaveAndDownload")}
                    </small>
                  )}
                </div>
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
              before={
                <AdminDefaultSelect
                  label={t("voiceCloneEngine")}
                  options={cloneOptions}
                  value={savedClone}
                  placeholder={config.data?.engine ?? t("defaultNotSet")}
                  disabled={makeDefault.isPending}
                  onChange={(id) => makeDefault.mutate(id)}
                />
              }
            >
              {cloneModels.map(renderModelRow)}
            </EngineGroup>
          )}
          {presetModels.length > 0 && (
            <EngineGroup
              kind="preset"
              title={t("voiceCloneGroupPreset")}
              description={t("voiceCloneGroupPresetDesc")}
              // 预置音色只有一种实现(Qwen3-TTS),也就不存在"默认可设";克隆引擎那边才是默认所在。
              before={<AdminOnlyOneNote optionCount={models.data ? presetModels.length : undefined} />}
            >
              {presetModels.map(renderModelRow)}
            </EngineGroup>
          )}
        </div>
      )}
    </AdminSection>
  );
}
