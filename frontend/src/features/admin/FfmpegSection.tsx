import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, RotateCw } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { FailureCard } from "@/components/failure/FailureCard";
import { SETTINGS_FIELD_WIDTH } from "@/components/settings/settings-layout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { ADMIN_CARD, AdminRow, AdminRowNote, AdminRowState, AdminSection } from "./adminLayout";

type FfmpegSettings = components["schemas"]["FfmpegSettingsOut"];

const QUERY_KEY = ["settings-ffmpeg"] as const;
const ENDPOINT = "/api/settings/ffmpeg";

/**
 * 管理 → 引擎 → FFmpeg(ADR 0048 第一步)。
 *
 * 导出、缩略图、波形、转写都要 ffmpeg;带字幕 / 花字 / AI 标识的导出还要两条路之一:浏览器渲染文字,或者 ffmpeg 带 libass。
 * Homebrew 默认装的 ffmpeg 是精简版、没有 libass,而发布版上浏览器那条路还没随包带 —— 这类导出就在建任务之前被拒。
 * 此前那句报错让人设环境变量,从 Finder 起的应用做不到;探测的结论也只进了日志。这一节把两件事摆出来:
 * 正在用的那个 ffmpeg 探出来是什么样,和填路径的那一格(存在库里,保存即生效)。
 *
 * 找没找到、有没有 libass、带字的导出走哪条路,都是后端探的(domain/media_tools),这里只照着说。
 */
export function FfmpegSection({ workspaceId }: { workspaceId: string }) {
  const t = useI18n();
  const qc = useQueryClient();
  const config = useQuery({ queryKey: QUERY_KEY, queryFn: () => api<FfmpegSettings>(ENDPOINT) });
  const [draft, setDraft] = React.useState<string | null>(null);
  const save = useMutation({
    mutationFn: (path: string) => api<FfmpegSettings>(ENDPOINT, { method: "PUT", body: JSON.stringify({ path }) }),
    onSuccess: (data) => {
      qc.setQueryData(QUERY_KEY, data);
      setDraft(null);
      toast.success(t("saved"));
    },
    // 填的路径用不了(不是绝对路径、没有这个文件、跑起来不像 ffmpeg):后端那句话贴着输入框留着,一改输入就消失 ——
    // 不再弹一遍全局的报错提示。
    meta: { silentError: true },
  });
  const recheck = useMutation({
    mutationFn: () => api<FfmpegSettings>(`${ENDPOINT}/recheck`, { method: "POST" }),
    onSuccess: (data) => qc.setQueryData(QUERY_KEY, data),
    onError: (error) => toast.error(errorText(error)),
  });

  const data = config.data;
  const value = draft ?? data?.path ?? "";
  const dirty = data != null && value.trim() !== data.path;
  const errorId = React.useId();
  //: 环境变量钉住了:这一格填了也不生效(后端 apply 直接跳过)。打不了字就不会骗人 —— 连带
  //: 「保存」永远不 dirty,placeholder 也换成「由环境变量决定」,不再说「留空:用 PATH 上的 ffmpeg」。
  const pinned = data?.pinned_by_environment === true;
  //: 禁用态的原因(为什么不能填 + 去哪改)挂在这条说明上,由 aria-describedby 指过来:光变灰不算说明。
  const pinnedHintId = React.useId();

  return (
    <AdminSection id="ffmpeg" title={t("ffmpegSectionTitle")} description={t("ffmpegSectionDesc")}>
      <div className={ADMIN_CARD}>
        {data ? (
          <InUseRow
            data={data}
            //: 重新检测只重探「正在用的 ffmpeg」这一行 —— 按钮就放在这一行的右格,和保存那颗同一套。
            //: 挂在节头 actions 里时,按钮和它管的东西分家(维护者:「位置为何是独立出去的」)。
            action={
              <Button size="sm" variant="outline" disabled={!data} loading={recheck.isPending} onClick={() => recheck.mutate()}>
                <RotateCw size={13} /> {t("ffmpegRecheck")}
              </Button>
            }
          />
        ) : (
          <AdminRow label={t("connecting")} />
        )}
        {data?.install?.available && !data.libass && <InstallRow workspaceId={workspaceId} install={data.install} onDone={() => qc.invalidateQueries({ queryKey: QUERY_KEY })} />}
        {/* 和「TTS 解释器」同一套行语法:左边标题 + 说明,右边控件格(输入框 + 保存)。此前控件堆在
            字下面、占满整行 —— 同一页两套行,看着像两个页面拼起来的。宽度取 SETTINGS_FIELD_WIDTH,
            和那一格一样。 */}
        <AdminRow
          label={t("ffmpegPathLabel")}
          //: 钉住时左格说完两件事:为什么填了不生效(原文),和去哪改(环境变量 + 重启,不是这页)。
          //: 两句分开渲染、同一个 id 包住 —— aria-describedby 指过来时读得到完整原因。
          description={
            pinned ? (
              <span id={pinnedHintId}>
                <span className="block">{t("ffmpegPathPinned")}</span>
                <span className="block">{t("ffmpegPathPinnedWhere")}</span>
              </span>
            ) : (
              t("ffmpegPathDesc")
            )
          }
          //: 后端挡下的那句话横贯整行、留在这一行下面:塞进右边那一格会把 280px 的输入框挤窄,
          //: 放左格又比说明还大。一改输入就消失(见 onChange)。
          footer={
            save.isError ? (
              <div id={errorId} role="alert">
                <FailureCard size="inline" lines={3} title={t("ffmpegPathRefused")} summary={errorText(save.error)} />
              </div>
            ) : undefined
          }
        >
          <form
            className="flex min-w-0 items-center gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (dirty && !save.isPending) save.mutate(value.trim());
            }}
          >
            <Input
              aria-label={t("ffmpegPathLabel")}
              aria-invalid={save.isError || undefined}
              //: 禁用态也要说得清:原因(为什么 + 去哪改)和填错的报错各挂一个,谁在就指谁。
              aria-describedby={[pinned ? pinnedHintId : null, save.isError ? errorId : null].filter(Boolean).join(" ") || undefined}
              className={cn(SETTINGS_FIELD_WIDTH, "font-mono")}
              // 不拿一条真路径当占位:灰字的「/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg」看上去像已经填好了。
              //: 钉住时更不能再写「留空就用 PATH」—— 环境变量说了算,这格留空也轮不到 PATH。
              placeholder={pinned ? t("ffmpegPathPlaceholderPinned") : t("ffmpegPathPlaceholder")}
              spellCheck={false}
              value={value}
              disabled={!data || pinned}
              onChange={(event) => {
                setDraft(event.target.value);
                if (save.isError) save.reset();
              }}
            />
            <Button type="submit" disabled={!dirty} loading={save.isPending}>
              {t("save")}
            </Button>
          </form>
        </AdminRow>
      </div>
    </AdminSection>
  );
}

/** 正在用的那个 ffmpeg:在哪、什么版本、带字的导出能不能做。做不了的时候说原因和怎么办。 */
/**
 * 「让 Mosael 装一个完整版」。**只在现在这个烧不了字、而清单里又有对得上的构建时才摆**:
 * 能用的时候摆一颗按钮只会让人以为要手动做点什么。
 *
 * 装是一次后台任务(后端 domain/media_tools_install):下载、核对 sha256、解包、验一遍(跑得起来 +
 * 能烧字),验过了才写进上面那一格。这里只跟着那颗任务的进度说话 —— 进度、取消都在任务中心。
 */
function InstallRow({ workspaceId, install, onDone }: {
  workspaceId: string;
  install: NonNullable<FfmpegSettings["install"]>;
  onDone: () => void;
}) {
  const t = useI18n();
  const [jobId, setJobId] = React.useState<string | null>(null);
  const start = useMutation({
    mutationFn: () => api<{ id: string }>(`${ENDPOINT}/install`, { method: "POST", body: JSON.stringify({ workspace_id: workspaceId }) }),
    onSuccess: (job) => setJobId(job.id),
    onError: (error) => toast.error(errorText(error)),
  });
  //: 装的时候盯那颗任务:成了就重问这一格(路径和后端探出来的结论都会变),没成就把原因摆出来。
  const job = useQuery({
    queryKey: ["job", jobId] as const,
    //: 和这一页别的请求同一个口(`api`),不另引一个客户端的封装 —— 这一页只关心状态和进度。
    queryFn: () => api<{ status: string; progress: number; error: string | null }>(`/api/jobs/${jobId}`),
    enabled: Boolean(jobId),
    refetchInterval: (query) => (query.state.data && ["succeeded", "failed", "cancelled"].includes(query.state.data.status) ? false : 1000),
  });
  const status = job.data?.status;
  React.useEffect(() => {
    if (status === "succeeded") {
      setJobId(null);
      onDone();
    }
  }, [status, onDone]);
  return (
    <AdminRow
      label={t("ffmpegInstallLabel")}
      description={t("ffmpegInstallDesc").replace("{version}", install.version || t("ffmpegInstallUnknownVersion"))}
      notes={
        <>
          {jobId && status && status !== "succeeded" && (
            <AdminRowNote>
              {status === "failed" ? t("ffmpegInstallFailed") : t("ffmpegInstallWorking").replace("{percent}", String(Math.round((job.data?.progress ?? 0) * 100)))}
            </AdminRowNote>
          )}
          {job.data?.status === "failed" && job.data.error && <AdminRowNote tone="destructive">{job.data.error}</AdminRowNote>}
        </>
      }
    >
      <div className="flex min-w-0 items-center gap-2">
        <Button
          size="sm"
          disabled={Boolean(jobId)}
          loading={start.isPending || Boolean(jobId)}
          onClick={() => start.mutate()}
        >
          <Download size={13} /> {t("ffmpegInstallAction")}
        </Button>
        <span className="min-w-0 text-ui-xs text-muted-foreground">
          {t("ffmpegInstallTarget").replace("{target}", install.target).replace("{archives}", String(install.archives))}
        </span>
      </div>
    </AdminRow>
  );
}

/** 「重新检测」跟着这一行走:它重探的就是这一行说的那个 ffmpeg,所以放在右格里,不挂节头。 */
function InUseRow({ data, action }: { data: FfmpegSettings; action?: React.ReactNode }) {
  const t = useI18n();
  const refused = data.found && data.text_burn_in == null;
  return (
    <AdminRow
      label={t("ffmpegInUse")}
      meta={[data.found && data.version ? t("ffmpegVersion").replace("{version}", data.version) : null]}
      description={<code className="timecode select-all font-normal">{data.in_use}</code>}
      notes={
        <>
          {!data.found && <AdminRowNote tone="destructive">{t("ffmpegNotFound")}</AdminRowNote>}
          {refused && (
            <AdminRowNote tone="destructive">
              {t(data.pinned_by_environment ? "ffmpegNoTextBurnInPinned" : "ffmpegNoTextBurnIn")}
            </AdminRowNote>
          )}
          {data.found && !data.libass && data.text_burn_in === "browser" && <AdminRowNote>{t("ffmpegTextByBrowser")}</AdminRowNote>}
          {/* 正在用的这一份就是 Mosael 装的那个:说清楚,免得下次升级时以为是系统里那个。 */}
          {data.install?.installed && data.in_use === data.install.installed && <AdminRowNote>{t("ffmpegInstalledByMosael")}</AdminRowNote>}
        </>
      }
    >
      {!data.found ? (
        <AdminRowState>{t("ffmpegMissingState")}</AdminRowState>
      ) : data.libass ? (
        <AdminRowState tone="success" icon={<CheckCircle2 size={14} />}>
          {t("ffmpegHasLibass")}
        </AdminRowState>
      ) : (
        <AdminRowState>{t("ffmpegNoLibass")}</AdminRowState>
      )}
      {action}
    </AdminRow>
  );
}
