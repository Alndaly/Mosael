import React from "react";
import {
  BookmarkPlus,
  Bot,
  Camera,
  Crop,
  FileText,
  Film,
  Images,
  Loader2,
  MessageSquareText,
  Monitor,
  PanelTop,
  Play,
  ScanText,
  TextSelect,
  TrendingUp,
  UserRound,
  X,
} from "lucide-react";

import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Truncate } from "@/components/ui/truncate";
import { listenKeys } from "@/lib/shortcuts";
import { cn } from "@/lib/utils";

import { ImagePanel } from "./ImagePanel";
import { RegionOverlay } from "./RegionOverlay";
import { ToolDrawer } from "./ToolDrawer";
import { VideoPanel } from "./VideoPanel";
import type { PageInfo, PageToolsBridge } from "./pageActions";
import { useImageTools } from "./useImageTools";
import { useNoteTools } from "./useNoteTools";
import { useShotTools } from "./useShotTools";
import { PAGE_TEMPLATES, useStartTools } from "./useStartTools";
import { toolAvailability, type PageTool } from "./toolAvailability";
import { useToolNotice } from "./useToolNotice";
import { useVideoTools } from "./useVideoTools";
import { useViewProfile } from "./viewProfile";

type Group = "shot" | "note" | "start" | null;
type Drawer = "video" | "images" | null;

/** 工具的补充说明(悬停说明里名字下面那一行)。 */
const TOOL_HINTS: Record<PageTool, MessageKey> = {
  shot: "browserToolsShotHint",
  video: "browserToolsVideoHint",
  images: "browserToolsImagesHint",
  note: "browserToolsNoteHint",
  start: "browserToolsStartHint",
};

const TEMPLATE_LOOK: Record<(typeof PAGE_TEMPLATES)[number], { label: MessageKey; icon: React.ReactNode }> = {
  viral_video_breakdown: { label: "browserToolsTemplateViral", icon: <TrendingUp /> },
  account_analysis: { label: "browserToolsTemplateAccount", icon: <UserRound /> },
  comment_insights: { label: "browserToolsTemplateComments", icon: <MessageSquareText /> },
};

/**
 * 浏览器会话顶栏的**页面工具区**:用户在前台这一页上点出来的采集与开工动作。
 *
 * **不遮挡网页。** 网页是原生视图,盖在一切 DOM 上 —— 下拉菜单画在网页区域里就会被盖住看不见。所以:
 * - 有子选项的在**顶栏里原地展开**成一排按钮,不往下掉,选了就收回;
 * - 要大块地方的(视频清单、图片网格)开成右侧栏,网页让出那一块(见 ToolDrawer);
 * - 框选时网页暂时藏起,原处铺一张冻结画面(见 RegionOverlay);
 * - 做完的提示(「已存进素材库」可点过去)也在顶栏里说(见 useToolNotice)。
 *
 * 只露图标:名字和一句补充说明在悬停说明里,点不了时(页面还没打开、还在加载、上一个操作没做完)说明里写为什么
 * (见 toolAvailability)。只作用于前台那一页,全部由用户点出来。
 * 每样能力的状态在各自的 hook 里(use*Tools),这里只摆按钮、侧栏和遮罩。
 */
export function BrowserSessionTools({
  workspaceId,
  state,
  barHeight,
}: {
  workspaceId: string;
  state: PublishViewState;
  barHeight: number;
}) {
  const tools = window.mosaelPageTools;
  if (!tools) return null;
  return <SessionTools tools={tools} workspaceId={workspaceId} state={state} barHeight={barHeight} />;
}

function SessionTools({
  tools,
  workspaceId,
  state,
  barHeight,
}: {
  tools: PageToolsBridge;
  workspaceId: string;
  state: PublishViewState;
  barHeight: number;
}) {
  const t = useI18n();
  const [group, setGroup] = React.useState<Group>(null);
  const [drawer, setDrawer] = React.useState<Drawer>(null);
  const page: PageInfo = { url: state.url ?? "", title: state.title ?? "" };
  const notice = useToolNotice();
  const profileId = useViewProfile(workspaceId, state.partition);

  const shot = useShotTools(tools, workspaceId, notice);
  const video = useVideoTools(tools, workspaceId, page, profileId, notice);
  const images = useImageTools(tools, workspaceId, notice);
  const note = useNoteTools(tools, workspaceId, notice);
  const start = useStartTools(workspaceId, page, profileId, notice);
  const busy = shot.busy || note.isPending || start.busy;

  const openDrawer = (next: Drawer) => {
    setGroup(null);
    setDrawer(next);
    if (next === "video") video.find.mutate();
    if (next === "images") images.find.mutate();
  };
  React.useEffect(() => {
    if (!group) return;
    return listenKeys(window, (event) => {
      if (event.key === "Escape") setGroup(null);
    });
  }, [group]);

  const unavailable = toolAvailability(state, busy);
  // 只留图标:名字和一句补充说明在悬停说明里(IconButton 的 label / hint),点不了时说明里写为什么。
  const tool = (key: PageTool, icon: React.ReactNode, label: MessageKey, onClick: () => void, active = false) => {
    const reason = unavailable[key];
    return (
      <IconButton
        key={key}
        data-page-tool={key}
        aria-pressed={active}
        label={t(label)}
        hint={t(TOOL_HINTS[key])}
        disabled={reason !== null}
        disabledReason={reason ? t(reason) : undefined}
        onClick={onClick}
        className={cn(active && "bg-secondary")}
      >
        {icon}
      </IconButton>
    );
  };
  // 选了就收回去:做到哪了由状态条说,工具区回到平时的样子,下一样工具马上点得到。
  const choice = (key: string, icon: React.ReactNode, label: MessageKey, onClick: () => void) => (
    <Button
      key={key}
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
            "[-webkit-app-region:no-drag] inline-flex min-w-0 items-center gap-1.5 rounded-md border border-border bg-panel-inset px-2 py-1 text-ui-xs",
            // 报错要读得完:宽一些、折成两行(56px 的顶栏放得下),还长就悬停看全文;做好了 / 进行中的一行就够。
            shown.tone === "error" ? "max-w-[420px] text-destructive" : "max-w-[340px]",
          )}
        >
          {shown.tone === "busy" && <Loader2 size={12} className="flex-none animate-mosael-spin" />}
          <Truncate data-page-tools-notice-text="" lines={shown.tone === "error" ? 2 : 1}>
            {shown.text}
          </Truncate>
          {shown.action && (
            <button type="button" className="flex-none cursor-pointer border-0 bg-transparent p-0 text-ui-xs font-medium text-primary hover:underline" onClick={shown.action.run}>
              {shown.action.label}
            </button>
          )}
          {shown.tone !== "busy" && (
            <IconButton unstyled className="flex-none cursor-pointer border-0 bg-transparent p-0 text-muted-foreground" onClick={() => say(null)} label={t("browserToolsClose")}>
              <X size={12} />
            </IconButton>
          )}
        </div>
      )}
      {video.active && shown?.tone !== "busy" && (
        <button
          type="button"
          data-page-tools-download=""
          className="[-webkit-app-region:no-drag] inline-flex flex-none cursor-pointer items-center gap-1.5 rounded-md border border-border bg-panel-inset px-2 py-1 text-ui-xs text-foreground"
          onClick={() => openDrawer("video")}
        >
          <Loader2 size={12} className="animate-mosael-spin" />
          {t("browserToolsDownloading").replace("{p}", String(Math.round(video.active.progress * 100)))}
        </button>
      )}
      <div role="toolbar" aria-label={t("browserToolsLabel")} className="[-webkit-app-region:no-drag] inline-flex flex-none items-center gap-0.5" data-page-tools="">
        {group === "shot" ? (
          <>
            {choice("visible", <Monitor />, "browserToolsShotVisible", () => shot.shoot.mutate("visible"))}
            {choice("full", <PanelTop />, "browserToolsShotFull", () => shot.shoot.mutate("full"))}
            {choice("region", <Crop />, "browserToolsShotRegion", () => shot.beginRegion.mutate())}
          </>
        ) : group === "note" ? (
          <>
            {choice("article", <ScanText />, "browserToolsNoteArticle", () => note.mutate("article"))}
            {choice("selection", <TextSelect />, "browserToolsNoteSelection", () => note.mutate("selection"))}
          </>
        ) : group === "start" ? (
          <>
            {PAGE_TEMPLATES.map((id) =>
              choice(id, TEMPLATE_LOOK[id].icon, TEMPLATE_LOOK[id].label, () => start.template.mutate(id)),
            )}
            {choice("agent", <Bot />, "browserToolsAgent", () => start.agent.mutate())}
          </>
        ) : (
          <>
            {tool("shot", <Camera />, "browserToolsShot", () => setGroup("shot"))}
            {tool("video", <Film />, "browserToolsVideo", () => openDrawer("video"), drawer === "video")}
            {tool("images", <Images />, "browserToolsImages", () => openDrawer("images"), drawer === "images")}
            {tool("note", <FileText />, "browserToolsNote", () => setGroup("note"))}
            {tool("start", <Play />, "browserToolsStart", () => setGroup("start"))}
          </>
        )}
        {group && (
          <IconButton size="icon-xs" onClick={() => setGroup(null)} label={t("browserToolsCollapse")} shortcut="Esc">
            <X />
          </IconButton>
        )}
      </div>
      {drawer === "video" && (
        <ToolDrawer top={barHeight} title={t("browserToolsVideoTitle")} onClose={() => setDrawer(null)}>
          <VideoPanel
            probe={video.probe}
            probing={video.find.isPending}
            platform={video.platform}
            downloads={video.downloads}
            starting={video.download.isPending ? (video.download.variables?.url ?? "page") : null}
            onDownload={(candidate) => video.download.mutate(candidate)}
            onCancel={(jobId) => video.cancel.mutate(jobId)}
            onRefresh={() => video.find.mutate()}
          />
        </ToolDrawer>
      )}
      {drawer === "images" && (
        <ToolDrawer
          top={barHeight}
          title={t("browserToolsImagesTitle")}
          onClose={() => setDrawer(null)}
          actions={
            images.anyReady ? (
              <Button variant="ghost" size="xs" onClick={images.toggleAll}>
                {images.selected.size ? t("browserToolsImagesSelectNone") : t("browserToolsImagesSelectAll")}
              </Button>
            ) : undefined
          }
          footer={
            <Button size="sm" disabled={images.selected.size === 0} loading={images.save.isPending} onClick={() => images.save.mutate()}>
              <BookmarkPlus /> {t("browserToolsImagesSave").replace("{n}", String(images.selected.size))}
            </Button>
          }
        >
          <ImagePanel images={images.images} loading={images.find.isPending} selected={images.selected} onToggle={images.toggle} />
        </ToolDrawer>
      )}
      {shot.region && <RegionOverlay top={barHeight} frame={shot.region} onDone={shot.onRegionDone} />}
    </>
  );
}
