import React from "react";
import {
  Camera,
  Crop,
  Loader2,
  Monitor,
  PanelTop,
  X,
} from "lucide-react";

import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { listenKeys } from "@/lib/shortcuts";
import { cn } from "@/lib/utils";

import { RegionOverlay } from "./RegionOverlay";
import type { PageToolsBridge } from "./pageActions";
import { useShotTools } from "./useShotTools";
import { useToolNotice } from "./useToolNotice";

type Group = "shot" | null;

/**
 * 浏览器会话顶栏的**页面工具区**:用户在前台这一页上点出来的采集与开工动作。
 *
 * **不遮挡网页。** 网页是原生视图,盖在一切 DOM 上 —— 下拉菜单画在网页区域里就会被盖住看不见。所以:
 * - 有子选项的在**顶栏里原地展开**成一排按钮,不往下掉,选了就收回;
 * - 框选时网页暂时藏起,原处铺一张冻结画面(见 RegionOverlay);
 * - 做完的提示(「已存进素材库」可点过去)也在顶栏里说(见 useToolNotice)。
 *
 * 平时只露图标,指针移到工具区(或键盘焦点进来)时文字标签展开。只作用于前台那一页,全部由用户点出来。
 * 每样能力的状态在各自的 hook 里(use*Tools),这里只摆按钮和遮罩。
 */
export function BrowserSessionTools({
  workspaceId,
  barHeight,
}: {
  workspaceId: string;
  state: PublishViewState;
  barHeight: number;
}) {
  const tools = window.mosaelPageTools;
  if (!tools) return null;
  return <SessionTools tools={tools} workspaceId={workspaceId} barHeight={barHeight} />;
}

function SessionTools({
  tools,
  workspaceId,
  barHeight,
}: {
  tools: PageToolsBridge;
  workspaceId: string;
  barHeight: number;
}) {
  const t = useI18n();
  const [group, setGroup] = React.useState<Group>(null);
  const notice = useToolNotice();

  const shot = useShotTools(tools, workspaceId, notice);
  const busy = shot.busy;

  React.useEffect(() => {
    if (!group) return;
    return listenKeys(window, (event) => {
      if (event.key === "Escape") setGroup(null);
    });
  }, [group]);

  const tool = (key: string, icon: React.ReactNode, label: MessageKey, onClick: () => void, active = false) => (
    <Button
      key={key}
      type="button"
      variant="ghost"
      size="xs"
      data-page-tool={key}
      aria-pressed={active}
      title={t(label)}
      disabled={busy}
      onClick={onClick}
      className={cn("gap-1.5 px-1.5", active && "bg-secondary")}
    >
      {icon}
      <span className="hidden group-hover/tools:inline group-focus-within/tools:inline">{t(label)}</span>
    </Button>
  );
  // 选了就收回去:做到哪了由状态条说,工具区回到平时的样子,下一样工具马上点得到。
  const choice = (key: string, icon: React.ReactNode, label: MessageKey, onClick: () => void) => (
    <Button
      key={key}
      type="button"
      variant="outline"
      size="xs"
      data-page-choice={key}
      disabled={busy}
      onClick={() => {
        setGroup(null);
        onClick();
      }}
    >
      {icon} {t(label)}
    </Button>
  );
  const { notice: shown, say } = notice;

  return (
    <>
      {shown && (
        <div
          role="status"
          data-page-tools-notice={shown.tone}
          className={cn(
            "[-webkit-app-region:no-drag] inline-flex min-w-0 max-w-[340px] items-center gap-1.5 rounded-md border border-border bg-panel-inset px-2 py-1 text-ui-xs",
            shown.tone === "error" && "text-destructive",
          )}
        >
          {shown.tone === "busy" && <Loader2 size={12} className="flex-none animate-mosael-spin" />}
          <span className="min-w-0 truncate" title={shown.text}>{shown.text}</span>
          {shown.action && (
            <button type="button" className="flex-none cursor-pointer border-0 bg-transparent p-0 text-ui-xs font-medium text-primary hover:underline" onClick={shown.action.run}>
              {shown.action.label}
            </button>
          )}
          {shown.tone !== "busy" && (
            <button type="button" className="flex-none cursor-pointer border-0 bg-transparent p-0 text-muted-foreground" onClick={() => say(null)} aria-label={t("browserToolsClose")}>
              <X size={12} />
            </button>
          )}
        </div>
      )}
      <div role="toolbar" aria-label={t("browserToolsLabel")} className="group/tools [-webkit-app-region:no-drag] inline-flex flex-none items-center gap-0.5" data-page-tools="">
        {group === "shot" ? (
          <>
            {choice("visible", <Monitor />, "browserToolsShotVisible", () => shot.shoot.mutate("visible"))}
            {choice("full", <PanelTop />, "browserToolsShotFull", () => shot.shoot.mutate("full"))}
            {choice("region", <Crop />, "browserToolsShotRegion", () => shot.beginRegion.mutate())}
          </>
        ) : (
          <>
            {tool("shot", <Camera />, "browserToolsShot", () => setGroup("shot"))}
          </>
        )}
        {group && (
          <Button type="button" variant="ghost" size="icon-xs" onClick={() => setGroup(null)} title={t("browserToolsCollapse")} aria-label={t("browserToolsCollapse")}>
            <X />
          </Button>
        )}
      </div>
      {shot.region && <RegionOverlay top={barHeight} frame={shot.region} onDone={shot.onRegionDone} />}
    </>
  );
}
