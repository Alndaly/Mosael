import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, Loader2, RotateCw } from "lucide-react";
import { toast } from "sonner";

import {
  type DenoiseEngine,
  installDenoiseEngine,
  listDenoiseEngines,
  setDefaultDenoiseEngine,
} from "@/api/client";
import { useI18n } from "@/app/preferences";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { Button } from "@/components/ui/button";
import { formatBytes } from "@/lib/bytes";
import { pollWhileUnsettled } from "@/lib/pollWhileUnsettled";
import { ADMIN_CARD, AdminRow, AdminRowNote, AdminRowState, AdminSection, AdminTag } from "./adminLayout";
import { AdminDefaultMarker, AdminDefaultSelect } from "./defaultRow";

/**
 * 管理 → 引擎 → 降噪(ADR-0017)。
 *
 * 一节看全这台机器上的**本机**降噪方式:哪些随应用带着、哪个要下载、哪些会去掉音乐。
 * 只有要下载的那种有按钮 —— 往这台机器上放一个可执行文件是显式的一步,不藏在"点一下降噪"后面,
 * 而且只给部署管理员(routes/denoise.install_denoise_engine),所以在管理页。
 *
 * **降噪有三种实现,所以有默认可设。** 默认行放在节说明之后、列表之前(`AdminDefaultSelect`,
 * 和转写模型同一个零件、同一条规则),整节只有那一处能改;列表行只负责下载/状态,已默认的那一行
 * 只剩一枚不可点的淡标记。它是**部署默认**:每个人在「设置 → 能力提供方 → 降噪」里选过的那一家
 * 会覆盖它 —— 行说明里写清了这一层,别让人以为在这里设了就一定生效。
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
  const setDefault = useMutation({
    mutationFn: (engine: string) => setDefaultDenoiseEngine(engine),
    //: **从后端重新读整张列表**:默认只有一个,原来那一个也得跟着改口(回包只是改完的那一行)。
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["denoise-engines"] }),
    //: 后端会拒(没装好 / 不认识的 id)—— 原因原样说出来,点了没反应的控件等于坏了。
    onError: (error: Error) => toast.error(error.message),
  });

  //: 部署默认只可能是**内置引擎**(插件连接属于某个人,见 domain/denoise_defaults)。和下面那份
  //: 列表同一个筛选:这一节列的就是本机引擎。
  const builtins = engines.data?.filter((engine) => engine.engine.startsWith("builtin:"));
  const options = builtins?.map((engine) => ({
    id: engine.engine,
    label: engine.label,
    installed: isInstalled(engine),
    //: 不要下载、只是这台机器上用不了时给真正的原因(别让用户去找一个不存在的下载按钮)。
    reason: isInstalled(engine) || engine.installable ? undefined : engine.setup_hint || t("denoiseUnavailableLabel"),
  }));
  const defaultEngine = builtins?.find((engine) => engine.is_default);

  return (
    <AdminSection id="engine-denoise" title={t("denoiseEnginesTitle")} description={t("denoiseEnginesDesc")}>
      {/* 默认只有在这一节有**多种**可选引擎时才存在(见 defaultRow);数据没到就不画。
          整节只有这一处能改默认,列表行不承担。 */}
      <AdminDefaultSelect
        label={t("denoiseDefaultTitle")}
        description={t("denoiseDefaultHint")}
        options={options}
        value={defaultEngine?.engine}
        placeholder={t("denoiseDefaultAuto")}
        disabled={setDefault.isPending}
        onChange={(engine) => setDefault.mutate(engine)}
      />
      <div className={ADMIN_CARD}>
        {/* 这一节管的是**本机引擎**的安装;接口里也有这个人配好的降噪插件(ADR 0032,id 是连接 id,
            它们在设置「能力提供方」里),这里不列 —— 那是某个成员自己的连接,不是这台机器上的东西。 */}
        {builtins?.map((engine) => (
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

/** 这一种现在能不能直接用:要下载的看下载状态,其余的看运行环境探没探过。 */
function isInstalled(engine: DenoiseEngine): boolean {
  return engine.installable ? engine.status === "installed" : engine.ready;
}

function EngineRow({ engine, busy, onInstall }: { engine: DenoiseEngine; busy: boolean; onInstall: () => void }) {
  const t = useI18n();
  const installed = isInstalled(engine);
  return (
    <AdminRow
      label={engine.label}
      meta={[
        engine.installable && engine.size_bytes > 0 && engine.status !== "installed"
          ? t("denoiseSizeApprox").replace("{size}", formatBytes(engine.size_bytes))
          : null,
      ]}
      tags={
        <>
          {engine.removes_music && <AdminTag tone="warning">{t("denoiseRemovesMusicBadge")}</AdminTag>}
          {/* 已默认只是**一枚淡标记**,不可点:改默认在节顶那一行里(唯一可写处)。 */}
          {engine.is_default && <AdminDefaultMarker />}
        </>
      }
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
