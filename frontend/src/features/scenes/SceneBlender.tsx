import React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowDownToLine,
  ArrowUpRight,
  Box,
  Check,
  Download,
  Loader2,
  MonitorSmartphone,
  Plug,
  RefreshCw,
} from "lucide-react";
import { api, API_BASE, getAuthToken } from "@/api/transport";
import { usePreferences } from "@/app/preferences";
import { docsUrl } from "@/lib/deepLink";
import type { Scene, SceneContent } from "@/api/domains/scenes";
import { errorText } from "@/api/errorMessage";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/layout/EmptyState";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Pick } from "./SceneControls";

type Transfer = {
  id: string;
  instance_id: string;
  status: string;
  source_revision: number;
  scene_name: string | null;
  created_at: string;
  received_scene_id: string | null;
  warnings: string[] | null;
  error: string | null;
};
export function SceneBlender({
  scene,
  pending,
  busy,
  prepare,
  apply,
  work,
}: {
  scene: Scene;
  pending: boolean;
  busy: boolean;
  /** 这一刻可以发什么:**已经落库的**那个修订和当前镜头。GLB 由后端按这个修订自己生成 ——
   *  此前这里要交出一份浏览器导出的 blob,于是"发送场景"这件事必须有人开着这个页面,
   *  跑在后端的智能体做不到。 */
  prepare: () => Promise<{ revision: number; shotId: string }>;
  /** 把接回来的内容当成当前场景上的一次普通改动写下去 —— 可撤销,由自动保存落库。 */
  apply: (content: SceneContent) => void;
  work: (label: string, fn: () => Promise<void>) => Promise<void>;
}) {
  const { locale, t } = usePreferences();
  const [open, setOpen] = React.useState(false),
    [chosen, setChosen] = React.useState(""),
    [selectedTransfer, setSelectedTransfer] = React.useState("");
  const [message, setMessage] = React.useState(""),
    [failure, setFailure] = React.useState("");
  const [checked, setChecked] = React.useState(false);
  const query = `workspace_id=${encodeURIComponent(scene.workspace_id)}`;
  const base = `/api/scenes/${scene.id}/blender`;
  const connections = useQuery({
    queryKey: ["blender-connections"],
    enabled: open,
    queryFn: () =>
      api<{
        local: boolean;
        connections: { id: string; name: string; enabled: boolean }[];
      }>("/api/scenes/blender/connections"),
  });
  const transfers = useQuery({
    queryKey: ["blender-transfers", scene.id],
    enabled: open,
    queryFn: () => api<Transfer[]>(`${base}?${query}`),
  });
  const available =
    connections.data?.connections.filter((c) => c.enabled) ?? [];
  const instance = available.some((c) => c.id === chosen)
    ? chosen
    : (available[0]?.id ?? "");
  const readyTransfers =
    transfers.data?.filter(
      (one) => one.instance_id === instance && one.status === "ready",
    ) ?? [];
  const latest =
    readyTransfers.find((one) => one.id === selectedTransfer) ?? readyTransfers[0];
  React.useEffect(() => {
    setChecked(false);
    setMessage("");
    setFailure("");
    setSelectedTransfer("");
  }, [instance]);
  async function run(label: string, action: () => Promise<void>) {
    setFailure("");
    setMessage("");
    await work(label, async () => {
      try {
        await action();
      } catch (e) {
        setFailure(errorText(e));
      } finally {
        void transfers.refetch();
      }
    });
  }
  const unavailable = busy || !instance || !connections.data?.local;
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm">
          <Box size={15} />
          Blender
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="scene-blender">
        <div className="scene-blender-heading">
          <div>
            <strong>{t("sceneBlenderTitle")}</strong>
            <p>{t("sceneBlenderSubtitle")}</p>
          </div>
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("sceneBlenderRefresh")}
            disabled={busy}
            onClick={() => {
              void connections.refetch();
              void transfers.refetch();
            }}
          >
            <RefreshCw size={15} />
          </Button>
        </div>
        {/* 四个「还用不了」的状态。**每一个都要答出「接下来做什么」** —— 见 EmptyState 的说明:
            空状态最有价值的那一半是下一步,不是"这里是空的"。此前只有缺插件那一个给了出路,
            另外三个是裸的一行灰字,读者从「长得不一样」读出的是"这里坏了"。 */}
        {connections.isPending ? (
          <EmptyState
            size="compact"
            icon={<Loader2 size={16} className="animate-mosael-spin" />}
            title={t("sceneBlenderLoadingTitle")}
            body={t("sceneBlenderLoadingBody")}
          />
        ) : connections.error ? (
          <EmptyState
            size="compact"
            icon={<AlertTriangle size={16} />}
            title={t("sceneBlenderErrorTitle")}
            body={String(connections.error)}
            action={
              <Button variant="secondary" size="sm" onClick={() => void connections.refetch()}>
                <RefreshCw size={14} />
                {t("retry")}
              </Button>
            }
          />
        ) : !connections.data?.local ? (
          /* 团队服务器部署上这是**永久**状态,不是没配好:互通要把 .blend 写到本机磁盘、
             再由本机的 Blender 打开,而服务器上的后端够不到你的电脑。所以这里不给"去设置",
             给的是"这条路要怎么走"。 */
          <EmptyState
            size="compact"
            icon={<MonitorSmartphone size={16} />}
            title={t("sceneBlenderDesktopTitle")}
            body={t("sceneBlenderDesktopBody")}
            action={
              <a
                className="scene-blender-link"
                href={docsUrl("start/download", locale)}
                target="_blank"
                rel="noreferrer"
              >
                {t("sceneBlenderDownloadDesktop")} <ArrowUpRight size={14} />
              </a>
            }
          />
        ) : !available.length ? (
          <EmptyState
            size="compact"
            icon={<Plug size={16} />}
            title={t("sceneBlenderNotConnectedTitle")}
            body={t("sceneBlenderNotConnectedBody")}
            action={
              <div className="scene-blender-setup">
                <a href="#/plugins" onClick={() => setOpen(false)}>
                  {t("sceneBlenderPluginSettings")} <ArrowUpRight size={14} />
                </a>
                {/* 曾经指向 `tree/codex/scene-studio/...` —— 那是一条**开发分支**,远端只有 main,
                    所有人点进去都是 404。指南本来就有这一节,而且跟着界面语言走。 */}
                <a href={docsUrl("guides/scenes", locale)} target="_blank" rel="noreferrer">
                  {t("sceneBlenderInstallSteps")} <ArrowUpRight size={14} />
                </a>
              </div>
            }
          />
        ) : (
          <>
            <div className="scene-blender-connection">
              <Pick
                className="h-8"
                label={t("sceneBlenderConnection")}
                value={instance}
                options={available.map((c) => [c.id, c.name])}
                onChange={setChosen}
              />
              <Button
                size="sm"
                variant="secondary"
                disabled={unavailable}
                onClick={() =>
                  void run(t("sceneBlenderChecking"), async () => {
                    const result = await api<{ name: string }>(
                      `/api/scenes/blender/connections/${instance}/check`,
                      { method: "POST" },
                    );
                    setChecked(true);
                    setMessage(t("sceneBlenderConnected").replace("{name}", result.name));
                  })
                }
              >
                {checked ? <Check size={14} /> : <RefreshCw size={14} />}{t("sceneBlenderCheck")}
              </Button>
            </div>
            <button
              className="scene-blender-action"
              disabled={unavailable || pending}
              onClick={() =>
                void run(t("sceneBlenderSending"), async () => {
                  const ready = await prepare();
                  const result = await api<Transfer>(base, {
                    method: "POST",
                    body: JSON.stringify({
                      workspace_id: scene.workspace_id,
                      instance_id: instance,
                      revision: ready.revision,
                      shot_id: ready.shotId,
                    }),
                  });
                  setSelectedTransfer(result.id);
                  setMessage(t("sceneBlenderSent").replace("{name}", result.scene_name ?? ""));
                })
              }
            >
              <ArrowUpRight size={19} />
              <span>
                <strong>{t("sceneBlenderSend")}</strong>
                <small>
                  {pending
                    ? t("sceneBlenderWaitSave")
                    : t("sceneBlenderSendHint")}
                </small>
              </span>
            </button>
            {/* **默认落在当前场景上。** 此前只能另建一个新场景 —— 于是「在 Blender 里改一改
                再回来接着做」这条最常见的路,每走一遍就多出一个场景,镜头和历史都留在上一个里。
                接收在这里只是一次普通改动:⌘Z 撤得掉,版本记录里也躺着接收前的那一版。
                真要留原样的,下面还有「另存为新场景」。 */}
            <button
              className="scene-blender-action"
              disabled={unavailable || !latest}
              onClick={() =>
                void run(t("sceneBlenderReceive"), async () => {
                  const result = await api<Transfer & { content: SceneContent }>(
                    `${base}/${latest!.id}/receive?${query}&into_current=true`,
                    { method: "POST" },
                  );
                  apply(result.content);
                  setMessage(t("sceneBlenderReceivedCurrent"));
                })
              }
            >
              <ArrowDownToLine size={19} />
              <span>
                <strong>{t("sceneBlenderReceive")}</strong>
                <small>
                  {latest
                    ? t("sceneBlenderReceiveHint").replace("{name}", latest.scene_name ?? "")
                    : t("sceneBlenderReceiveEmpty")}
                </small>
              </span>
            </button>
            {readyTransfers.length > 1 && (
              <Pick
                label={t("sceneBlenderTransfers")}
                value={latest!.id}
                options={readyTransfers.map((one) => [
                  one.id,
                  `${new Date(one.created_at).toLocaleString()} · ${t("sceneHistoryRevision").replace("{n}", String(one.source_revision))}`,
                ])}
                onChange={setSelectedTransfer}
              />
            )}
            {latest && (
              <div className="scene-blender-result">
                <span>
                  {t("sceneBlenderSentAt")
                    .replace("{time}", new Date(latest.created_at).toLocaleString())
                    .replace("{n}", String(latest.source_revision))}
                </span>
                <small>{t("sceneBlenderReceiveNote")}</small>
                {latest.warnings?.map((warning, index) => (
                  <small key={index}>{warning}</small>
                ))}
                <div>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={unavailable}
                    onClick={() =>
                      void run(t("sceneBlenderReceiveAsNew"), async () => {
                        const result = await api<Transfer>(
                          `${base}/${latest.id}/receive?${query}`,
                          { method: "POST" },
                        );
                        setMessage(
                          result.received_scene_id
                            ? t("sceneBlenderReceivedNew")
                            : t("sceneBlenderReceived"),
                        );
                      })
                    }
                  >
                    {t("sceneBlenderSaveAsNew")}
                  </Button>
                  {latest.received_scene_id && (
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={busy || pending}
                      onClick={() => {
                        location.hash = `#/scenes?scene=${latest.received_scene_id}`;
                        setOpen(false);
                      }}
                    >
                      {t("sceneBlenderOpenReceived")} <ArrowUpRight size={14} />
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() =>
                      void run(t("sceneBlenderDownloading"), async () => {
                        const res = await fetch(
                          `${API_BASE}${base}/${latest.id}/project?${query}`,
                          {
                            headers: {
                              Authorization: `Bearer ${getAuthToken()}`,
                            },
                          },
                        );
                        if (!res.ok)
                          throw new Error(t("sceneBlenderDownloadFailed"));
                        const url = URL.createObjectURL(await res.blob()),
                          a = document.createElement("a");
                        a.href = url;
                        a.download = `${scene.name}.blend`;
                        a.click();
                        setTimeout(() => URL.revokeObjectURL(url), 1000);
                      })
                    }
                  >
                    <Download size={14} />
                    .blend
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
        {busy && (
          <p role="status" className="scene-blender-status">
            <Loader2 size={14} className="animate-spin" />
            {t("sceneBlenderBusy")}
          </p>
        )}
        {message && (
          <p role="status" className="scene-blender-status">
            {message}
          </p>
        )}
        {failure && (
          <p role="alert" className="scene-blender-error">
            {failure}
          </p>
        )}
        {transfers.error && <p role="alert">{t("sceneBlenderTransfersFailed")}</p>}
      </PopoverContent>
    </Popover>
  );
}
