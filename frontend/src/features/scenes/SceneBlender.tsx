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
import type { Scene, SceneContent } from "@/api/domains/scenes";
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
  prepare: () => Promise<{ revision: number; shotId: string; blob: Blob }>;
  /** 把接回来的内容当成当前场景上的一次普通改动写下去 —— 可撤销,由自动保存落库。 */
  apply: (content: SceneContent) => void;
  work: (label: string, fn: () => Promise<void>) => Promise<void>;
}) {
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
      (t) => t.instance_id === instance && t.status === "ready",
    ) ?? [];
  const latest =
    readyTransfers.find((t) => t.id === selectedTransfer) ?? readyTransfers[0];
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
        setFailure(e instanceof Error ? e.message : String(e));
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
            <strong>与 Blender 互通</strong>
            <p>搭好场景，再去打磨细节</p>
          </div>
          <Button
            variant="ghost"
            size="icon"
            aria-label="刷新 Blender 连接"
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
            title="正在读取连接"
            body="在找这台电脑上可用的 Blender。"
          />
        ) : connections.error ? (
          <EmptyState
            size="compact"
            icon={<AlertTriangle size={16} />}
            title="读不到连接列表"
            body={String(connections.error)}
            action={
              <Button variant="secondary" size="sm" onClick={() => void connections.refetch()}>
                <RefreshCw size={14} />
                重试
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
            title="需要桌面版 Mosael"
            body="互通要把场景写到你这台电脑上、再交给同机的 Blender 打开。当前后端不在你的电脑上，够不到它。"
            action={
              <a
                className="scene-blender-link"
                href="https://mosael.com"
                target="_blank"
                rel="noreferrer"
              >
                下载桌面版 <ArrowUpRight size={14} />
              </a>
            }
          />
        ) : !available.length ? (
          <EmptyState
            size="compact"
            icon={<Plug size={16} />}
            title="还没接上 Blender"
            body="装好 Blender MCP 插件和配套 Add-on，在 Blender 里开启连接，这里就能选到它。"
            action={
              <div className="scene-blender-setup">
                <a href="#/plugins" onClick={() => setOpen(false)}>
                  前往插件设置 <ArrowUpRight size={14} />
                </a>
                <a
                  href="https://github.com/Alndaly/Mosael/tree/codex/scene-studio/plugins/examples/blender"
                  target="_blank"
                  rel="noreferrer"
                >
                  查看安装步骤 <ArrowUpRight size={14} />
                </a>
              </div>
            }
          />
        ) : (
          <>
            <div className="scene-blender-connection">
              <Pick
                label="Blender 连接"
                value={instance}
                options={available.map((c) => [c.id, c.name])}
                onChange={setChosen}
              />
              <Button
                size="sm"
                variant="secondary"
                disabled={unavailable}
                onClick={() =>
                  void run("检查 Blender", async () => {
                    const result = await api<{ name: string }>(
                      `/api/scenes/blender/connections/${instance}/check`,
                      { method: "POST" },
                    );
                    setChecked(true);
                    setMessage(`已连接 · ${result.name}`);
                  })
                }
              >
                {checked ? <Check size={14} /> : <RefreshCw size={14} />}检测
              </Button>
            </div>
            <button
              className="scene-blender-action"
              disabled={unavailable || pending}
              onClick={() =>
                void run("发送到 Blender", async () => {
                  const ready = await prepare();
                  const body = new FormData();
                  body.set("workspace_id", scene.workspace_id);
                  body.set("instance_id", instance);
                  body.set("revision", String(ready.revision));
                  body.set("shot_id", ready.shotId);
                  body.set("file", ready.blob, "scene.glb");
                  const result = await api<Transfer>(base, {
                    method: "POST",
                    body,
                  });
                  setSelectedTransfer(result.id);
                  setMessage(`已发送 · ${result.scene_name}`);
                })
              }
            >
              <ArrowUpRight size={19} />
              <span>
                <strong>发送当前场景</strong>
                <small>
                  {pending
                    ? "等待场景保存完成…"
                    : "模型与镜头 · 在 Blender 中独立打开"}
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
                void run("接收 Blender 修改", async () => {
                  const result = await api<Transfer & { content: SceneContent }>(
                    `${base}/${latest!.id}/receive?${query}&into_current=true`,
                    { method: "POST" },
                  );
                  apply(result.content);
                  setMessage("已接收，当前场景已更新（⌘Z 可撤销）。");
                })
              }
            >
              <ArrowDownToLine size={19} />
              <span>
                <strong>接收 Blender 修改</strong>
                <small>
                  {latest
                    ? `用「${latest.scene_name}」更新当前场景 · 可撤销`
                    : "发送场景后即可接收加工结果"}
                </small>
              </span>
            </button>
            {readyTransfers.length > 1 && (
              <Pick
                label="发送记录"
                value={latest!.id}
                options={readyTransfers.map((t) => [
                  t.id,
                  `${new Date(t.created_at).toLocaleString()} · 版本 ${t.source_revision}`,
                ])}
                onChange={setSelectedTransfer}
              />
            )}
            {latest && (
              <div className="scene-blender-result">
                <span>
                  发送于 {new Date(latest.created_at).toLocaleString()} · 版本{" "}
                  {latest.source_revision}
                </span>
                <small>几何体作为整体模型接收；镜头保留为可编辑关键帧。</small>
                {latest.warnings?.map((warning, index) => (
                  <small key={index}>{warning}</small>
                ))}
                <div>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={unavailable}
                    onClick={() =>
                      void run("接收为新场景", async () => {
                        const result = await api<Transfer>(
                          `${base}/${latest.id}/receive?${query}`,
                          { method: "POST" },
                        );
                        setMessage(
                          result.received_scene_id
                            ? "已接收，生成了独立的新场景。"
                            : "已接收。",
                        );
                      })
                    }
                  >
                    另存为新场景
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
                      打开接收的场景 <ArrowUpRight size={14} />
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() =>
                      void run("下载 Blender 工程", async () => {
                        const res = await fetch(
                          `${API_BASE}${base}/${latest.id}/project?${query}`,
                          {
                            headers: {
                              Authorization: `Bearer ${getAuthToken()}`,
                            },
                          },
                        );
                        if (!res.ok)
                          throw new Error("工程下载失败，请重新接收后再试。");
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
            正在与 Blender 通信…
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
        {transfers.error && <p role="alert">同步记录读取失败，请刷新重试。</p>}
      </PopoverContent>
    </Popover>
  );
}
