import React from "react";
import { AlertCircle, CheckCircle2, Download, Loader2, RotateCw } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { formatBytes, formatSpeed } from "@/lib/bytes";
import { AdminRow, AdminRowNote, AdminRowState } from "./adminLayout";

/** 转写模型和配音引擎共有的那一半:权重在不在盘上、跑不跑得起来、正在下多少。 */
export type DownloadableModel = {
  label: string;
  detail: string;
  status: string;
  runtime_ready: boolean;
  runtime_checked: boolean;
  downloaded_bytes: number;
  total_bytes: number;
  expected_bytes: number;
  total_is_estimate: boolean;
  speed_bps: number;
  message: string;
};

/**
 * 管理 →「引擎」里转写和声音克隆两节的一行可下载的模型。
 *
 * 两页此前各抄了一份一模一样的卡片(连注释都是同一段),改一边忘一边是迟早的事。
 * 现在两边只在三处不同,由调用方传进来:名字旁多一项元信息(转写的引擎族)、跑不起来时的那句话、
 * 以及按钮上的说明(点不动时为什么、能点时点了会怎样)。
 */
export function ModelDownloadRow({
  model,
  meta,
  noRuntimeText,
  busy,
  busyReason,
  actionHint,
  onDownload,
}: {
  model: DownloadableModel;
  /** 名字后面、大小前面的元信息,比如引擎族。 */
  meta?: React.ReactNode;
  /** 权重在盘上、但这台机器上没有能跑它的解释器时说的那句话。 */
  noRuntimeText: string;
  busy?: boolean;
  /** 动作按钮因为 busy 点不动时说为什么。禁用了却不给理由,看起来就是坏了。 */
  busyReason?: string;
  /** 能点时按钮上的补充说明(点了会先做什么)。 */
  actionHint?: string;
  onDownload: () => void;
}) {
  const t = useI18n();
  const pct = model.total_bytes > 0 ? Math.min(100, Math.round((model.downloaded_bytes / model.total_bytes) * 100)) : 0;
  const downloading = model.status === "downloading";
  const installed = model.status === "installed";
  // 「约」不是客套:问不到下载源时这个数是写死的估算,而用户会拿它当准数
  // (然后发现进度条走到 93% 就完成了)。问到了就不带「约」—— 那才是实测。
  const size = model.total_is_estimate
    ? t("sizeApprox").replace("{size}", formatBytes(model.expected_bytes))
    : formatBytes(model.expected_bytes);

  const action = (icon: React.ReactNode, label: string) => (
    <Hint label={busy ? undefined : actionHint} disabledReason={busy ? busyReason : undefined}>
      <Button size="sm" variant="outline" loading={busy} onClick={onDownload}>
        {icon} {label}
      </Button>
    </Hint>
  );

  return (
    <AdminRow
      label={model.label}
      meta={[meta, size]}
      description={model.detail}
      notes={
        <>
          {/* 「还没测过」和「测过了、跑不起来」是两回事 —— 探测要起子进程 import torch,
              不能卡在请求里,所以刚打开时可能还没有答案。说成"未就绪"是拿未知冒充结论。 */}
          {installed && !model.runtime_checked && <AdminRowNote>{t("runtimeChecking")}</AdminRowNote>}
          {installed && model.runtime_checked && !model.runtime_ready && (
            <AdminRowNote tone="destructive">{noRuntimeText}</AdminRowNote>
          )}
          {/* **装运行环境和下模型是两件事**,量纲也不同:前者跑的是 pip(装 torch 等,几 GB
              但我们不知道总量),后者才是这个模型的大小。没有分母时就别画进度条、也别摆
              「0 MB / 2.2 GB」—— 那个数是模型的,而此刻在跑的不是它。
              分子和速度仍然值得说 —— 「5.2 GB · 12.4 MB/s」比一个光转的圈有用得多,
              而且它是判断"卡住没有"的唯一依据。 */}
          {downloading && model.total_bytes <= 0 && (
            <AdminRowNote icon={<Loader2 size={12} className="animate-mosael-spin" />}>
              {model.downloaded_bytes > 0 && <span className="tabular-nums">{formatBytes(model.downloaded_bytes)}</span>}
              {model.speed_bps > 0 && <span className="tabular-nums">{formatSpeed(model.speed_bps)}</span>}
              <Truncate>{model.message}</Truncate>
            </AdminRowNote>
          )}
          {model.status === "failed" && (
            <AdminRowNote tone="destructive" icon={<AlertCircle size={13} />}>
              {model.message}
            </AdminRowNote>
          )}
        </>
      }
      footer={
        downloading && model.total_bytes > 0 ? (
          <div className="grid gap-1.5">
            <Progress value={pct} className="h-1" />
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
          </div>
        ) : undefined
      }
    >
      {/* **两件事分开说**:文件在不在盘上(status),和跑不跑得起来(runtime_ready)。
          它们完全可以一真一假 —— 模型缓存是别的工具下的,而这台机器上没有任何解释器装了
          对应的包。只看前者的话,页面写着「已安装」、一用就报找不到环境,而用户最容易做的事
          是去重下已经在盘上的那几个 GB。 */}
      {installed && model.runtime_checked && model.runtime_ready && (
        <AdminRowState tone="success" icon={<CheckCircle2 size={14} />}>
          {t("asrModelInstalled")}
        </AdminRowState>
      )}
      {installed && model.runtime_checked && !model.runtime_ready && action(<Download size={13} />, t("asrModelInstallRuntime"))}
      {model.status === "missing" && action(<Download size={13} />, t("asrModelDownload"))}
      {downloading && (
        // 没有分母的阶段(装运行环境)不报百分比 —— 一个恒定的「0%」和"卡住了"长得一样。
        <AdminRowState icon={<Loader2 size={13} className="animate-mosael-spin" />}>
          {model.total_bytes > 0 ? `${pct}%` : null}
        </AdminRowState>
      )}
      {model.status === "failed" && action(<RotateCw size={13} />, t("asrModelRetry"))}
    </AdminRow>
  );
}
