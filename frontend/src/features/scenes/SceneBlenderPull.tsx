import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Box, Loader2, MonitorSmartphone, Plug, ArrowUpRight } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/transport";
import { errorText } from "@/api/errorMessage";
import { Button } from "@/components/ui/button";
import { usePreferences } from "@/app/preferences";
import { docsUrl } from "@/lib/deepLink";
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
  const { locale, t } = usePreferences();
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
      toast.success(t("sceneBlenderPulled").replace("{name}", result.name));
      // 相机取不回来是常态,不是错 —— 单独说一句,别混在成功提示里一闪而过。
      for (const warning of result.warnings) toast.warning(warning, { duration: 8000 });
      onCreated(result.scene_id);
    } catch (e) {
      toast.error(errorText(e));
    } finally {
      setBusy("");
    }
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" disabled={disabled}>
          <Box size={16} />
          {t("sceneBlenderPullButton")}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="scene-blender">
        <div className="scene-blender-heading">
          <div>
            <strong>{t("sceneBlenderPullTitle")}</strong>
            <p>{t("sceneBlenderPullSubtitle")}</p>
          </div>
        </div>
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
            icon={<Plug size={16} />}
            title={t("sceneBlenderErrorTitle")}
            body={String(connections.error)}
            action={
              <Button variant="secondary" size="sm" onClick={() => void connections.refetch()}>
                {t("retry")}
              </Button>
            }
          />
        ) : !connections.data?.local ? (
          <EmptyState
            size="compact"
            icon={<MonitorSmartphone size={16} />}
            title={t("sceneBlenderDesktopTitle")}
            body={t("sceneBlenderPullDesktopBody")}
            action={
              <a className="scene-blender-link" href={docsUrl("start/download", locale)} target="_blank" rel="noreferrer">
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
                  <small>{t("sceneBlenderPullHint")}</small>
                </span>
              </button>
            ))}
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
