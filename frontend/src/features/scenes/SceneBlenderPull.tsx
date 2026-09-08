import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Box, Loader2, MonitorSmartphone, Plug, ArrowUpRight } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/transport";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/layout/EmptyState";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

/**
 * 从 Blender 当前打开的场景直接建一个 Mosael 场景。
 *
 * 它和 3D 详情页里那个「与 Blender 互通」是**两个方向**:那边是一趟往返(先发送、再接收
 * 那一份),这边是单向取回,不要求先发送过 —— 人手上常常先有一个 Blender 工程,而此前
 * 没有任何入口能把它带进来。所以入口放在列表页:那正是"我要开始一个场景"的地方。
 */
export function SceneBlenderPull({
  workspaceId,
  disabled,
  onCreated,
}: {
  workspaceId: string;
  disabled?: boolean;
  onCreated: (sceneId: string) => void;
}) {
  const [open, setOpen] = React.useState(false);
  const [busy, setBusy] = React.useState("");
  const connections = useQuery({
    queryKey: ["blender-connections"],
    enabled: open,
    queryFn: () =>
      api<{
        local: boolean;
        connections: { id: string; name: string; enabled: boolean }[];
      }>("/api/scenes/blender/connections"),
  });
  const available = (connections.data?.connections ?? []).filter((c) => c.enabled);

  async function pull(instanceId: string) {
    setBusy(instanceId);
    try {
      const result = await api<{ scene_id: string; name: string; warnings: string[] }>(
        `/api/scenes/blender/pull?workspace_id=${encodeURIComponent(workspaceId)}&instance_id=${encodeURIComponent(instanceId)}`,
        { method: "POST" },
      );
      setOpen(false);
      toast.success(`已取回「${result.name}」`);
      // 相机取不回来是常态,不是错 —— 单独说一句,别混在成功提示里一闪而过。
      for (const warning of result.warnings) toast.warning(warning, { duration: 8000 });
      onCreated(result.scene_id);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" disabled={disabled}>
          <Box size={16} />
          从 Blender 获取
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="scene-blender">
        <div className="scene-blender-heading">
          <div>
            <strong>取回 Blender 当前场景</strong>
            <p>几何体整体导入 · 镜头在这里重新设计</p>
          </div>
        </div>
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
            icon={<Plug size={16} />}
            title="读不到连接列表"
            body={String(connections.error)}
            action={
              <Button variant="secondary" size="sm" onClick={() => void connections.refetch()}>
                重试
              </Button>
            }
          />
        ) : !connections.data?.local ? (
          <EmptyState
            size="compact"
            icon={<MonitorSmartphone size={16} />}
            title="需要桌面版 Mosael"
            body="取回要读你这台电脑上的 Blender。当前后端不在你的电脑上，够不到它。"
            action={
              <a className="scene-blender-link" href="https://mosael.com" target="_blank" rel="noreferrer">
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
              </div>
            }
          />
        ) : (
          <div className="scene-blender-pull-list">
            {available.map((connection) => (
              <button
                key={connection.id}
                className="scene-blender-action"
                disabled={!!busy}
                onClick={() => void pull(connection.id)}
              >
                {busy === connection.id ? (
                  <Loader2 size={19} className="animate-mosael-spin" />
                ) : (
                  <Box size={19} />
                )}
                <span>
                  <strong>{connection.name}</strong>
                  <small>取回它当前打开的那个场景</small>
                </span>
              </button>
            ))}
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
