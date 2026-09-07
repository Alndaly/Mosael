import React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowDownToLine,
  ArrowUpRight,
  Box,
  Check,
  Download,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { api, API_BASE, getAuthToken } from "@/api/transport";
import type { Scene } from "@/api/domains/scenes";
import { Button } from "@/components/ui/button";
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
  work,
}: {
  scene: Scene;
  pending: boolean;
  busy: boolean;
  prepare: () => Promise<{ revision: number; shotId: string; blob: Blob }>;
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
        {connections.isPending ? (
          <p role="status">正在读取连接…</p>
        ) : connections.error ? (
          <p role="alert">连接列表读取失败，请刷新重试。</p>
        ) : !connections.data?.local ? (
          <p>请使用本机桌面后端，并在同一台电脑上打开 Blender。</p>
        ) : !available.length ? (
          <div className="scene-blender-setup">
            <p>先安装 Blender MCP 插件和配套 Add-on，在 Blender 中开启连接。</p>
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
            <button
              className="scene-blender-action"
              disabled={unavailable || !latest}
              onClick={() =>
                void run("接收 Blender 修改", async () => {
                  await api<Transfer>(
                    `${base}/${latest!.id}/receive?${query}`,
                    { method: "POST" },
                  );
                  setMessage("已接收，生成了独立的新场景。");
                })
              }
            >
              <ArrowDownToLine size={19} />
              <span>
                <strong>接收 Blender 修改</strong>
                <small>
                  {latest
                    ? `从「${latest.scene_name}」创建新场景`
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
                    variant="ghost"
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
