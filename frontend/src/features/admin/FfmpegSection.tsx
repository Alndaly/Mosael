import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, RotateCw } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { FailureCard } from "@/components/failure/FailureCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
export function FfmpegSection() {
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

  return (
    <AdminSection
      id="ffmpeg"
      title={t("ffmpegSectionTitle")}
      description={t("ffmpegSectionDesc")}
      actions={
        <Button size="sm" variant="outline" disabled={!data} loading={recheck.isPending} onClick={() => recheck.mutate()}>
          <RotateCw size={13} /> {t("ffmpegRecheck")}
        </Button>
      }
    >
      <div className={ADMIN_CARD}>
        {data ? <InUseRow data={data} /> : <AdminRow label={t("connecting")} />}
        <AdminRow
          stacked
          label={t("ffmpegPathLabel")}
          description={data?.pinned_by_environment ? t("ffmpegPathPinned") : t("ffmpegPathDesc")}
        >
          <form
            className="grid min-w-0 gap-1.5"
            onSubmit={(event) => {
              event.preventDefault();
              if (dirty && !save.isPending) save.mutate(value.trim());
            }}
          >
            <div className="flex min-w-0 gap-2">
              <Input
                aria-label={t("ffmpegPathLabel")}
                aria-invalid={save.isError || undefined}
                aria-describedby={save.isError ? errorId : undefined}
                className="font-mono"
                // 不拿一条真路径当占位:灰字的「/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg」看上去像已经填好了。
                placeholder={t("ffmpegPathPlaceholder")}
                spellCheck={false}
                value={value}
                disabled={!data || data.pinned_by_environment}
                onChange={(event) => {
                  setDraft(event.target.value);
                  if (save.isError) save.reset();
                }}
              />
              <Button type="submit" disabled={!dirty} loading={save.isPending}>
                {t("save")}
              </Button>
            </div>
            {save.isError && (
              <div id={errorId} role="alert">
                <FailureCard size="inline" lines={3} title={t("ffmpegPathRefused")} summary={errorText(save.error)} />
              </div>
            )}
          </form>
        </AdminRow>
      </div>
    </AdminSection>
  );
}

/** 正在用的那个 ffmpeg:在哪、什么版本、带字的导出能不能做。做不了的时候说原因和怎么办。 */
function InUseRow({ data }: { data: FfmpegSettings }) {
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
    </AdminRow>
  );
}
