import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, Loader2, RotateCw } from "lucide-react";
import { toast } from "sonner";

import { type DenoiseEngine, installDenoiseEngine, listDenoiseEngines } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { Button } from "@/components/ui/button";
import { formatBytes } from "@/lib/bytes";
import { pollWhileUnsettled } from "@/lib/pollWhileUnsettled";
import { ADMIN_CARD, AdminRow, AdminRowNote, AdminRowState, AdminSection, AdminTag } from "./adminLayout";

/**
 * 管理 → 引擎 → 降噪(ADR-0017)。
 *
 * 一节看全这台机器上的**本机**降噪方式:哪些随应用带着、哪个要下载、哪些会去掉音乐。
 * 只有要下载的那种有按钮 —— 往这台机器上放一个可执行文件是显式的一步,不藏在"点一下降噪"后面,
 * 而且只给部署管理员(routes/denoise.install_denoise_engine),所以在管理页。
 *
 * 这一节不认识任何引擎:名字、说明、没准备好时的提示都由后端给。
 */
export function DenoiseEnginesSection() {
  const t = useI18n();
  const qc = useQueryClient();
  const engines = useQuery({
    queryKey: ["denoise-engines"],
    queryFn: listDenoiseEngines,
    refetchInterval: (query) => pollWhileUnsettled(query.state.data),
  });
  const install = useMutation({
    mutationFn: (engine: string) => installDenoiseEngine(engine),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["denoise-engines"] }),
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <AdminSection id="engine-denoise" title={t("denoiseEnginesTitle")} description={t("denoiseEnginesDesc")}>
      <div className={ADMIN_CARD}>
        {/* 这一节管的是**本机引擎**的安装;接口里也有这个人配好的降噪插件(ADR 0032,id 是连接 id,
            它们在设置「能力提供方」里),这里不列 —— 那是某个成员自己的连接,不是这台机器上的东西。 */}
        {engines.data
          ?.filter((engine) => engine.engine.startsWith("builtin:"))
          .map((engine) => (
            <EngineRow
              key={engine.engine}
              engine={engine}
              busy={(install.isPending && install.variables === engine.engine) || engine.status === "installing"}
              onInstall={() => install.mutate(engine.engine)}
            />
          ))}
        {engines.isLoading && <AdminRow label={t("connecting")} />}
      </div>
    </AdminSection>
  );
}

function EngineRow({ engine, busy, onInstall }: { engine: DenoiseEngine; busy: boolean; onInstall: () => void }) {
  const t = useI18n();
  const installed = engine.installable ? engine.status === "installed" : engine.ready;
  return (
    <AdminRow
      label={engine.label}
      meta={[
        engine.installable && engine.size_bytes > 0 && engine.status !== "installed"
          ? t("denoiseSizeApprox").replace("{size}", formatBytes(engine.size_bytes))
          : null,
      ]}
      tags={engine.removes_music && <AdminTag tone="warning">{t("denoiseRemovesMusicBadge")}</AdminTag>}
      description={<InlineMarkdown text={engine.description} />}
      notes={
        <>
          {/* 不需要装、但现在用不了的(比如 ffmpeg 没带 RNNoise 滤镜):说清原因。 */}
          {!engine.installable && !engine.ready && engine.setup_hint && (
            <AdminRowNote tone="foreground">{engine.setup_hint}</AdminRowNote>
          )}
          {engine.status === "unsupported" && <AdminRowNote tone="foreground">{t("denoiseUnsupported")}</AdminRowNote>}
          {/* 失败原因**原样显示**:校验不符、连不上 GitHub,用户能照着那句话去查。 */}
          {engine.status === "failed" && engine.message && <AdminRowNote tone="destructive">{engine.message}</AdminRowNote>}
          {engine.status === "installing" && engine.message && <AdminRowNote>{engine.message}</AdminRowNote>}
        </>
      }
    >
      {installed && (
        <AdminRowState tone="success" icon={<CheckCircle2 size={14} />}>
          {t(engine.installable ? "denoiseInstalled" : "denoiseReadyLabel")}
        </AdminRowState>
      )}
      {!engine.installable && !engine.ready && <AdminRowState>{t("denoiseUnavailableLabel")}</AdminRowState>}
      {engine.status === "installing" && <AdminRowState icon={<Loader2 size={13} className="animate-mosael-spin" />} />}
      {engine.status === "missing" && (
        <Button size="sm" variant="outline" loading={busy} onClick={onInstall}>
          <Download size={13} /> {t("denoiseInstall")}
        </Button>
      )}
      {engine.status === "failed" && (
        <Button size="sm" variant="outline" loading={busy} onClick={onInstall}>
          <RotateCw size={13} /> {t("denoiseRetry")}
        </Button>
      )}
    </AdminRow>
  );
}
