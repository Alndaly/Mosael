import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, Loader2, RotateCw } from "lucide-react";
import { toast } from "sonner";

import { type SeparationEngine, installSeparationEngine, listSeparationEngines } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { pollWhileUnsettled } from "@/lib/pollWhileUnsettled";
import { ADMIN_CARD, AdminRow, AdminRowNote, AdminRowState, AdminSection } from "./adminLayout";

/**
 * 管理 → 引擎 → 人声/背景音分离(ADR-0016)。
 *
 * **为什么这一节必须存在**:不装它,第一次分离会在工作流跑到一半时静默建 venv、装 torch、
 * 拉权重 —— 几分钟到几十分钟,期间界面上只有一个转圈,而用户完全不知道正在往自己机器上装
 * 一个 GB 级的东西。把它提出来,装是一次**显式**的动作,进度和失败原因都有地方说。
 * 装只给部署管理员(routes/separation.install_separation_engine),所以在管理页。
 *
 * 和转写那一节共用同一套形状,但只有**一件**事要说:跑不跑得起来。权重是第一次分离时
 * 引擎自己拉的,所以这里没有"文件在不在盘上"那一半。
 */
export function SeparationEnginesSection() {
  const t = useI18n();
  const qc = useQueryClient();
  const engines = useQuery({
    queryKey: ["separation-engines"],
    queryFn: listSeparationEngines,
    refetchInterval: (query) => pollWhileUnsettled(query.state.data),
  });
  const install = useMutation({
    mutationFn: (engine: string) => installSeparationEngine(engine),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["separation-engines"] }),
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <AdminSection id="engine-separation" title={t("separationTitle")} description={t("separationDesc")}>
      <div className={ADMIN_CARD}>
        {engines.data?.map((engine) => (
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

function EngineRow({
  engine,
  busy,
  onInstall,
}: {
  engine: SeparationEngine;
  busy?: boolean;
  onInstall: () => void;
}) {
  const t = useI18n();
  return (
    <AdminRow
      label={engine.label}
      // 「约」不是客套:装下来的实际大小取决于这台机器要哪个 torch 轮子。
      meta={[t("separationSize")]}
      description={t("separationEngineDetail")}
      notes={
        <>
          {/* 「还没测过」和「测过了、跑不起来」是两回事 —— 探一次要起子进程 import torch,
              不能卡在请求里,所以刚打开这一页时可能还没有答案。说成"未安装"是拿未知冒充结论。 */}
          {!engine.runtime_checked && engine.status !== "installing" && <AdminRowNote>{t("runtimeChecking")}</AdminRowNote>}
          {/* 原因**原样显示**:失败时是 pip 说的那句话(用户至少能搜一下),没装好时是
              「运行环境不完整」—— 后者此前没有地方说,于是半装的环境只剩一个光秃秃的「未安装」。 */}
          {engine.runtime_checked && engine.message && (
            <AdminRowNote tone={engine.status === "failed" ? "destructive" : "muted"}>{engine.message}</AdminRowNote>
          )}
        </>
      }
    >
      {engine.status === "installed" && (
        <AdminRowState tone="success" icon={<CheckCircle2 size={14} />}>
          {t("separationInstalled")}
        </AdminRowState>
      )}
      {/* 没有分母就不报百分比 —— 一个恒定的「0%」和"卡住了"长得一样(转写那一节同款)。
          没测过也不摆按钮:这一刻还不知道它装没装,而「安装」和「已安装」都是结论。 */}
      {(engine.status === "installing" || (engine.status === "missing" && !engine.runtime_checked)) && (
        <AdminRowState icon={<Loader2 size={13} className="animate-mosael-spin" />} />
      )}
      {engine.status === "missing" && engine.runtime_checked && (
        <Button size="sm" variant="outline" loading={busy} onClick={onInstall}>
          <Download size={13} /> {t("separationInstall")}
        </Button>
      )}
      {engine.status === "failed" && (
        <Button size="sm" variant="outline" loading={busy} onClick={onInstall}>
          <RotateCw size={13} /> {t("separationRetry")}
        </Button>
      )}
    </AdminRow>
  );
}
