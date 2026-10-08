import { SceneRouteMemory } from "@/features/scenes/sceneRouteMemory";
import { watchBodyPointerLock } from "@/lib/bodyPointerLock";
import { useCreateWorkspace, useWorkspaces } from "@/lib/workspaces";
import { FirstWorkspace } from "@/app/FirstWorkspace";
import { PageBoundary } from "@/app/PageBoundary";
import { JOBS_CREATED_EVENT } from "@/api/client";
import { assetKeys, projectKeys } from "@/api/queryKeys";
import React from "react";
import {
  QueryClientProvider,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Loader2,
  RotateCw,
  X,
} from "lucide-react";

import {
  api,
  importLocalAsset,
  type ProjectWithStats,
  type Workspace,
} from "@/api/client";
import { createAppQueryClient } from "@/app/queryClient";
import { AuthProvider, useAuth } from "@/app/auth";
import { AppearanceProvider } from "@/app/appearance";
import { CustomCssProvider } from "@/app/customCss";
import {
  PreferencesProvider,
  translateNow,
  useI18n,
  usePreferences,
} from "@/app/preferences";
import { Toaster, toast } from "sonner";
import { LoginView } from "@/features/auth/LoginView";
import { AppShell, type StudioView } from "@/components/layout/AppShell";
import { STUDIO_VIEWS } from "@/components/layout/navLabels";
import { PAGE_RENDERERS } from "@/app/pages";
import { CommandPalette } from "@/components/layout/CommandPalette";
import { LoadingState } from "@/components/layout/LoadingState";
import { ConfirmationCenter } from "@/features/agent/ConfirmationCenter";
import { useRefreshWhenCardsLand } from "@/features/agent/confirmationCaches";
import { VoiceDock } from "@/features/agent/VoiceDock";
import { RemoteVoiceConsentHost } from "@/features/voice/remoteVoiceConsent";
import { useAgentNavigation } from "@/features/agent/useAgentNavigation";
import { goHome } from "@/features/ai-studio/goToPlace";
import { PlugZap } from "lucide-react";

import { ServerPicker } from "@/components/app/ServerPicker";
import { APP_CHROME, ChromeAboveDialogs, installAppChromeGuards } from "@/components/ui/appChrome";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { ImagePreviewProvider } from "@/components/app/image-preview";
import { NativeViewStandIn } from "@/components/ui/nativeViewAside";
import { BrowserPreview } from "@/features/browser-pool/BrowserPreview";
import { LivePanels } from "@/features/browser-pool/LivePanels";
import { BrowserPageList } from "@/features/browser-pool/BrowserPageList";
import { installEmbeddedFocus, pageAfterPointer } from "@/features/browser-pool/embeddedFocus";
import { isImeKeystroke } from "@/lib/shortcuts";
import { canReviveDesktopBackend, reviveDesktopBackend } from "@/lib/desktopBackend";
import { MainStaleBadge } from "@/features/desktop/MainStaleBadge";
import { MainStaleNotice } from "@/features/desktop/MainStaleNotice";
import { BrowserDownloads } from "@/features/browser-pool/session-tools/BrowserDownloads";
import { BrowserSessionTools } from "@/features/browser-pool/session-tools/BrowserSessionTools";
import { BrowserToolsWorkspace } from "@/app/browserToolsWorkspace";
import { ComfyNavigationSwitch } from "@/features/plugins/ComfyNavigationSwitch";
import { comfyConnectionOf } from "@/features/plugins/comfyNavigation";
import { useKeepServiceAwake } from "@/features/plugins/localServiceStatus";
import { isWorkbenchPartition, useWorkbench } from "@/features/plugins/workbench/workbenchSession";
import { StartupLoading } from "@/components/layout/StartupLoading";
import { Input } from "@/components/ui/input";
import { WINDOW_CHROME_INSET } from "@/lib/windowChrome";
import { cn } from "@/lib/utils";
import { VIEW_RECORD_EVENTS, gotoRecord, listenDesktopDeepLinks, openBoard } from "@/lib/deepLink";
import { useCreateProject } from "@/lib/useCreateProject";
import { Hint, HintRegion, TooltipProvider } from "@/components/ui/tooltip";
import { RecordingProvider } from "@/features/media/RecordingProvider";
import { SectionBoundary } from "@/components/app/errorBoundary";

//: **ComfyUI 工作台按需加载。** 它只在桌面版、打开工作台时才出现,却带着智能体对话(tiptap / prosemirror)、Markdown 全家
//: 和整个插件工作台 —— 静态 import 时这些都在首屏关键路径上(首屏 JS 78 个文件 / 2.8 MB;改成懒加载、文案表按语言分块之后 32 个 / 1.3 MB)。
//: app/pageChunks.test.ts 盯着入口的静态依赖闭包,不让它们再回来。
const ComfyWorkbench = React.lazy(() => import("@/features/plugins/workbench/ComfyWorkbench").then((m) => ({ default: m.ComfyWorkbench })));

/** 内嵌视图那一圈出错时:请主进程把原生网页视图收起来(和「返回 Mosael」一样)—— 不然一块光秃秃的网页盖在一切上面,出口都没了。 */
const hideNativeView = () => void window.mosaelPublish?.hideView().catch(() => undefined);

//: 缓存窗口、获焦不重拉、4xx 不重试都在 app/queryClient 里说明。
const queryClient = createAppQueryClient((message) => toast.error(message), translateNow);

export function App() {
  // **整页点不动**的兜底:Radix 偶发把 body 的 pointer-events:none 留在那儿(浮层还开着就被
  // 卸载、或两个浮层的清理互相打架),此后整个应用只能刷新。挂在最外层 —— 留下锁的那个浮层
  // 可能是任何一处的 Select / 右键菜单 / 弹窗,盯住锁本身才兜得全。见 lib/bodyPointerLock。
  React.useEffect(() => watchBodyPointerLock(), []);
  // 内嵌浏览器的外壳盖在开着的弹窗上面:焦点进出外壳不让弹窗的焦点圈套拽回去(见 appChrome)。
  React.useEffect(() => installAppChromeGuards(document), []);
  // 进出内嵌浏览器时键盘焦点怎么走(回来落回打开之前的那个按钮,网页亮着时看不见的地方不收键)。
  React.useEffect(() => installEmbeddedFocus(), []);
  // 哪个请求建了任务,所有任务列表(任务中心、AI 工作台、转写面板……)都立刻刷新 ——
  // 它们的键都以 "jobs" 开头。见 api/transport 的 JOBS_CREATED_EVENT。
  React.useEffect(() => {
    const refresh = () => void queryClient.invalidateQueries({ queryKey: ["jobs"] });
    window.addEventListener(JOBS_CREATED_EVENT, refresh);
    return () => window.removeEventListener(JOBS_CREATED_EVENT, refresh);
  }, []);
  const [toolsWorkspace, setToolsWorkspace] = React.useState<string | null>(null);
  const toolsHost = React.useMemo(() => ({ workspaceId: toolsWorkspace, setWorkspaceId: setToolsWorkspace }), [toolsWorkspace]);
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserToolsWorkspace.Provider value={toolsHost}>
      <PreferencesProvider>
        <AppearanceProvider>
          {/* 自定义 CSS 包在外观里面:它压过应用自带的一切样式,自然也压过外观那几个令牌。 */}
          <CustomCssProvider>
            <TooltipProvider delayDuration={300}>
              <AuthProvider>
                <ImagePreviewProvider>
                  <AuthGate />
                  <AppToaster />
                  {/* 常驻在窗口上的这几块各自兜底:哪一块渲染出错只收起它自己、弹一条提示,不把整个窗口换成「出错了」
                      (见 components/app/errorBoundary 的 SectionBoundary)。 */}
                  <SectionBoundary mode="quiet"><MainStaleNotice /></SectionBoundary>
                  <PublishViewBar />
                  <SectionBoundary mode="quiet"><BrowserDownloads /></SectionBoundary>
                  <SectionBoundary mode="quiet"><BrowserPreview /></SectionBoundary>
                  <SectionBoundary mode="quiet" onCatch={hideNativeView}><LivePanels /></SectionBoundary>
                  {/* 整窗浮层让原生网页视图挪开时,铺在它原处的那张画面(见 nativeViewAside) */}
                  <SectionBoundary mode="quiet"><NativeViewStandIn /></SectionBoundary>
                </ImagePreviewProvider>
              </AuthProvider>
            </TooltipProvider>
          </CustomCssProvider>
        </AppearanceProvider>
      </PreferencesProvider>
      </BrowserToolsWorkspace.Provider>
    </QueryClientProvider>
  );
}

/** 这条工具栏的高度。**内嵌发布视图正是从这个像素处开始铺**(Electron 侧的
 *  EMBED_HEADER_HEIGHT),两者不等就会露出一条缝、缝里是 App 自己的顶栏。
 *  由 contracts/shared-constants.json 钉住。 */
export const PUBLISH_BAR_HEIGHT = 56;
/** 顶栏里的说明往下出,画在网页上面(见 HintRegion)。 */
const PUBLISH_BAR_REGION = { side: "bottom" as const };

/** Electron 内嵌发布视图可见时的顶部浏览器工具栏:后退/前进/刷新 + 地址栏 + 页面工具 + 返回 Mosael。
 *  条底可拖窗(-webkit-app-region: drag),控件各自 no-drag。 */
export function PublishViewBar() {
  const t = useI18n();
  const { workspaceId } = React.useContext(BrowserToolsWorkspace);
  const [state, setState] = React.useState<PublishViewState>({
    visible: false,
    accountId: null,
    accountName: null,
  });
  const [address, setAddress] = React.useState("");
  const [editing, setEditing] = React.useState(false);
  //: 开着的 ComfyUI 工作台(ADR 0038):那个连接的视图亮着时,顶栏和右边那一列是工作台的
  const workbench = useWorkbench();
  React.useEffect(
    () => window.mosaelPublish?.onViewState((next) => setState(next)),
    [],
  );
  // 地址随导航更新,但用户正在输入时不覆盖(否则打字被主进程回报打断)。
  React.useEffect(() => {
    if (!editing) setAddress(state.url ?? "");
  }, [state.url, editing]);
  //: ComfyUI 的视图亮着:背后的本机服务正被人用着,告诉宿主别因为闲置把它停了(ADR 0041)
  useKeepServiceAwake(state.visible ? comfyConnectionOf(state.partition) : null);
  if (!state.visible) return null;
  //: 顶栏 / 工作台出错时只收起这一圈:原生视图跟着收起(否则网页盖在一切上面、没有出口),弹一条提示。视图下次亮起是一个新的边界。
  if (isWorkbenchPartition(workbench.target, state.partition)) {
    return (
      <SectionBoundary mode="quiet" onCatch={hideNativeView}>
        <React.Suspense fallback={null}>
          <ComfyWorkbench barHeight={PUBLISH_BAR_HEIGHT} />
        </React.Suspense>
      </SectionBoundary>
    );
  }
  //: 这是一个 ComfyUI 连接的视图、却不在工作台里(渲染层重新加载过,工作台的会话没接上):顶栏照样给画布操控方式的开关
  const comfyConnection = comfyConnectionOf(state.partition);

  // 回车打开:和浏览器一样,键盘交给打开的那一页。
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const value = address.trim();
    if (value) void window.mosaelPublish?.navigate(value);
    (
      event.currentTarget.querySelector("input") as HTMLInputElement | null
    )?.blur();
    void window.mosaelPublish?.focusPage?.();
  };

  // 挂到 body 末尾:排在底下开着的弹窗后面,顶栏才拖得动窗口(见 ChromeAboveDialogs)
  return (
    <SectionBoundary mode="quiet" onCatch={hideNativeView}>
    <ChromeAboveDialogs>
    <div
      {...APP_CHROME}
      style={{ height: PUBLISH_BAR_HEIGHT }}
      className={cn(
        "fixed inset-x-0 top-0 z-[200] flex items-center gap-2 border-b border-border bg-panel px-2.5 [-webkit-app-region:drag] supports-[backdrop-filter]:bg-[var(--glass-chrome)] supports-[backdrop-filter]:[-webkit-backdrop-filter:blur(14px)_saturate(1.4)] supports-[backdrop-filter]:[backdrop-filter:blur(14px)_saturate(1.4)]",
        WINDOW_CHROME_INSET,
      )}
    >
      {/* 栏下面是原生网页视图,盖在一切 DOM 上:栏里的悬停说明交给浮层视图画在网页上面(见 HintRegion)。 */}
      <HintRegion.Provider value={PUBLISH_BAR_REGION}>
      <div className="[-webkit-app-region:no-drag] inline-flex items-center gap-0.5">
        <IconButton
          unstyled
          type="button"
          className="inline-flex h-7 w-7 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-foreground enabled:hover:bg-secondary disabled:cursor-default disabled:opacity-35"
          disabled={!state.canGoBack}
          onClick={(event) => {
            void window.mosaelPublish?.back();
            pageAfterPointer(event);
          }}
          label={t("navBack")}
        >
          <ChevronLeft size={16} />
        </IconButton>
        <IconButton
          unstyled
          type="button"
          className="inline-flex h-7 w-7 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-foreground enabled:hover:bg-secondary disabled:cursor-default disabled:opacity-35"
          disabled={!state.canGoForward}
          onClick={(event) => {
            void window.mosaelPublish?.forward();
            pageAfterPointer(event);
          }}
          label={t("navForward")}
        >
          <ChevronRight size={16} />
        </IconButton>
        <IconButton
          unstyled
          type="button"
          className="inline-flex h-7 w-7 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-foreground enabled:hover:bg-secondary disabled:cursor-default disabled:opacity-35"
          onClick={(event) => {
            void window.mosaelPublish?.reload();
            pageAfterPointer(event);
          }}
          label={state.loading ? t("navStop") : t("navReload")}
        >
          {state.loading ? <X size={15} /> : <RotateCw size={14} />}
        </IconButton>
      </div>
      <form
        className="[-webkit-app-region:no-drag] flex h-7 min-w-0 flex-1 items-center gap-1.5 rounded-lg border border-border bg-panel-inset px-2.5 focus-within:border-ring [&_input]:min-w-0 [&_input]:flex-1 [&_input]:border-0 [&_input]:bg-transparent [&_input]:text-ui-sm [&_input]:text-foreground [&_input]:outline-none [&_input:focus-visible]:ring-0"
        onSubmit={submit}
      >
        {state.loading && (
          <Loader2
            size={13}
            className="flex-none animate-mosael-spin text-muted-foreground"
          />
        )}
        <Input
          value={address}
          spellCheck={false}
          placeholder={t("addressPlaceholder")}
          onChange={(event) => setAddress(event.target.value)}
          onFocus={(event) => {
            setEditing(true);
            event.target.select();
          }}
          onBlur={() => {
            setEditing(false);
            setAddress(state.url ?? "");
          }}
          onKeyDown={(event) => {
            // Esc:不改了,地址回到当前页,键盘回到网页。
            if (event.key !== "Escape" || isImeKeystroke(event)) return;
            setAddress(state.url ?? "");
            event.currentTarget.blur();
            void window.mosaelPublish?.focusPage?.();
          }}
        />
      </form>
      {/* 和这一排的前进后退、地址栏同高(28px);工作台的顶栏用 32 那一档(见 ComfyNavigationSwitch 的 size) */}
      {comfyConnection && <ComfyNavigationSwitch key={comfyConnection} connectionId={comfyConnection} size="xs" />}
      {workspaceId && (
        // key:换了一个视图(或同一视图换了档案)就是另一段会话,上一页的侧栏、下载、勾选都不该带过来。
        <BrowserSessionTools key={`${state.accountId}:${state.partition ?? ""}`} workspaceId={workspaceId} state={state} barHeight={PUBLISH_BAR_HEIGHT} />
      )}
      {/* 开发时主进程过期:窗口底部那条提示被网页视图盖住了,顶栏里常驻一个小标记(正式打包的应用永远没有)。 */}
      <MainStaleBadge />
      {/* 离开这个窗口的主出口:留着字(图标认不出「回到 Mosael」),说明里补一句连按两次 Esc 也能回来。 */}
      <Hint label={t("publishBackHint")}>
        <Button
          variant="outline"
          size="xs"
          data-publish-back=""
          className="[-webkit-app-region:no-drag] shrink-0"
          onClick={() => void window.mosaelPublish?.hideView()}
        >
          <ArrowLeft />
          {t("publishBackToApp")}
        </Button>
      </Hint>
      </HintRegion.Provider>
    </div>
    {/* 左侧页面列表。不能放进上面那条栏里:栏的 backdrop-filter 会让 fixed 定位相对它而不是窗口。
        key:换了一个会话就是另一份列表。 */}
    <BrowserPageList key={state.accountId ?? ""} state={state} top={PUBLISH_BAR_HEIGHT} />
    </ChromeAboveDialogs>
    </SectionBoundary>
  );
}

/** Sonner 跟随应用主题;样式对齐全平面(细边框、无投影由 CSS 覆盖)。 */
function AppToaster() {
  const { theme } = usePreferences();
  return (
    <Toaster
      theme={theme}
      position="bottom-right"
      gap={8}
      toastOptions={{
        className:
          "rounded-lg! border! border-floating-border! bg-popover! text-ui-sm! text-foreground! shadow-none!",
      }}
    />
  );
}

/**
 * 登录/建工作区之前的全屏过渡页(连接中、选工作区…)。这些页面不挂 AppShell,而无边框窗口
 * 的拖拽区一向由 AppShell 顶栏提供 —— 少了它,窗口在这些状态下**完全拖不动**(启动连接
 * 可能要好几秒)。这里统一补一条顶部透明拖拽带,内部交互元素标 no-drag。
 */
function PreShellScreen({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-screen place-items-center text-muted-foreground">
      <div
        className="fixed inset-x-0 top-0 z-[5] hidden h-11 [.is-desktop_&]:block [-webkit-app-region:drag]"
        aria-hidden
      />
      <div className="[&_:is(button,a,input,[role=button])]:[-webkit-app-region:no-drag]">
        {children}
      </div>
    </div>
  );
}

function AuthGate() {
  const t = useI18n();
  const { status } = useAuth();
  if (status === "loading")
    return (
      <PreShellScreen>
        <StartupLoading label={t("connecting")} detail={t("connectingHint")} />
      </PreShellScreen>
    );
  //: **连不上 ≠ 没登录。** 摆一屏登录页等于告诉用户「你的会话结束了」,而其实令牌还在、
  //: 只是后端这会儿没答应(本机进程,重启和休眠唤醒都是常态)。给他真正有用的两件事:
  //: 再试一次,或者换一个后端地址。
  if (status === "offline") return <OfflineView />;
  if (status === "anonymous") return <LoginView />;
  return <WorkspaceGate />;
}

function OfflineView() {
  const t = useI18n();
  const { retry } = useAuth();
  //: 桌面版的后端连崩被认输时,先请主进程重拉它、等它就绪,再重试(见 lib/desktopBackend)。
  const [reviving, setReviving] = React.useState(false);
  const revive = () => {
    if (!canReviveDesktopBackend()) {
      retry();
      return;
    }
    setReviving(true);
    void reviveDesktopBackend().then(() => {
      setReviving(false);
      retry();
    });
  };
  return (
    <PreShellScreen>
      <div className="grid max-w-sm justify-items-center gap-3 px-6 text-center">
        <PlugZap size={28} className="text-muted-foreground/70" />
        <p className="m-0 text-ui-md font-semibold text-foreground">{t("offlineTitle")}</p>
        <p className="m-0 text-ui-sm leading-relaxed text-muted-foreground">{t("offlineBody")}</p>
        <Button onClick={revive} loading={reviving} className="mt-1">
          {t("retry")}
        </Button>
        <ServerPicker />
      </div>
    </PreShellScreen>
  );
}

const ACTIVE_WORKSPACE_KEY = "mosael:workspace";

function readStoredWorkspaceId(): string | null {
  try {
    return localStorage.getItem(ACTIVE_WORKSPACE_KEY);
  } catch {
    return null;
  }
}

function persistWorkspaceId(id: string) {
  try {
    localStorage.setItem(ACTIVE_WORKSPACE_KEY, id);
  } catch {
    /* 隐私模式:退化为内存态 */
  }
}

function WorkspaceGate() {
  const t = useI18n();
  const workspaces = useWorkspaces();
  // The active workspace is persisted so a refresh — or a newer workspace appearing at
  // list[0] (newest first) — can't switch the user out of the workspace their jobs/projects live in.
  const [activeId, setActiveId] = React.useState<string | null>(
    readStoredWorkspaceId,
  );
  const selectWorkspace = React.useCallback((id: string) => {
    persistWorkspaceId(id);
    setActiveId(id);
  }, []);
  const createWorkspace = useCreateWorkspace({ onCreated: (created) => selectWorkspace(created.id) });
  const list = workspaces.data;
  const workspace =
    list?.find((item) => item.id === activeId) ?? list?.[0] ?? null;

  // Stamp the resolved workspace so the very first load (empty storage) pins list[0].
  React.useEffect(() => {
    if (workspace && workspace.id !== activeId) {
      persistWorkspaceId(workspace.id);
      setActiveId(workspace.id);
    }
  }, [workspace, activeId]);

  if (workspaces.isLoading)
    return (
      <PreShellScreen>
        <StartupLoading
          label={t("workspaceLoading")}
          detail={t("workspaceLoadingHint")}
        />
      </PreShellScreen>
    );
  if (!workspace) {
    return (
      <PreShellScreen>
        <FirstWorkspace pending={createWorkspace.isPending} onCreate={(name) => createWorkspace.mutate(name)} />
      </PreShellScreen>
    );
  }
  return (
    <Studio
      workspace={workspace}
      workspaces={list ?? []}
      onSelectWorkspace={selectWorkspace}
    />
  );
}

// 路由认哪些页面,和侧栏/面包屑认哪些页面,是同一件事 —— 手抄第三遍就会漏第三次。
const VALID_VIEWS: readonly string[] = STUDIO_VIEWS;

function readHash(): { view: StudioView; projectId: string | null } {
  // Hash routing survives file:// packaging — the fragment never hits HTTP.
  const raw = window.location.hash.replace(/^#\/?/, "");
  const [path, query] = raw.split("?");
  const view = VALID_VIEWS.includes(path) ? (path as StudioView) : "home";
  const projectId = new URLSearchParams(query ?? "").get("p");
  return { view, projectId };
}

function writeHash(view: StudioView, projectId: string | null) {
  const noteQuery = ["notes", "scenes", "boards", "entities"].includes(view) && window.location.hash.startsWith(`#/${view}?`) ? window.location.hash.split("?")[1] : "";
  const query = noteQuery ? `?${noteQuery}` : projectId ? `?p=${projectId}` : "";
  const next = `#/${view}${query}`;
  if (window.location.hash !== next)
    window.history.replaceState(null, "", next);
}

function Studio({
  workspace,
  workspaces,
  onSelectWorkspace,
}: {
  workspace: Workspace;
  workspaces: Workspace[];
  onSelectWorkspace: (id: string) => void;
}) {
  const { voiceDock, setVoiceDock } = usePreferences();
  const t = useI18n();
  const qc = useQueryClient();
  // 自动放行、飞书、别的设备批掉的卡执行完了,这边的素材库 / 时间线也要跟着刷(见 confirmationCaches)。
  useRefreshWhenCardsLand(workspace.id);
  // 顶栏页面工具存东西进的是这个工作区(见 BrowserToolsWorkspace)。
  const { setWorkspaceId: reportToolsWorkspace } = React.useContext(BrowserToolsWorkspace);
  React.useEffect(() => {
    reportToolsWorkspace(workspace.id);
    return () => reportToolsWorkspace(null);
  }, [workspace.id, reportToolsWorkspace]);
  const initial = React.useMemo(readHash, []);
  const [view, setView] = React.useState<StudioView>(initial.view);
  const [projectId, setProjectId] = React.useState<string | null>(
    initial.projectId,
  );

  const [sceneNavigation] = React.useState(() => {
    const routes = new SceneRouteMemory();
    routes.visit(workspace.id, window.location.hash);
    return routes;
  });
  const routeWorkspace = React.useRef(workspace.id);
  const navigate = (next: StudioView) => {
    sceneNavigation.visit(workspace.id, window.location.hash);
    // Set the destination before mounting SceneStudio: its initial state reads the URL.
    if (next === "scenes") window.location.hash = sceneNavigation.restore(workspace.id);
    setView(next);
  };

  // Switching workspaces: the open project belongs to the previous workspace, so
  // drop it and return home. The ref skips the initial mount (hash restore).
  const lastWorkspaceRef = React.useRef(workspace.id);
  React.useEffect(() => {
    if (lastWorkspaceRef.current !== workspace.id) {
      lastWorkspaceRef.current = workspace.id;
      routeWorkspace.current = workspace.id;
      setProjectId(null);
      setView("home");
    }
  }, [workspace.id]);

  React.useEffect(() => {
    writeHash(view, projectId);
  }, [view, projectId]);

  React.useEffect(() => {
    const onHashChange = () => {
      const next = readHash();
      sceneNavigation.visit(routeWorkspace.current, window.location.hash);
      setView(next.view);
      if (next.projectId) setProjectId(next.projectId);
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);
  const projects = useQuery({
    queryKey: projectKeys.list(workspace.id),
    queryFn: () =>
      api<ProjectWithStats[]>(`/api/projects?workspace_id=${workspace.id}`),
    staleTime: 0,
    refetchInterval: view === "home" ? 5_000 : false,
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
  });
  const project =
    projects.data?.find((item) => item.id === projectId) ??
    projects.data?.[0] ??
    null;

  const openProject = (id: string) => {
    setProjectId(id);
    setView("editor");
  };

  // 智能体说"带你去看看"时,界面真的过去。挂在 Studio 这一层是因为它要跨页面生效,
  // 而且**助手面板收起来时也要管用** —— 免提对话下这条路是唯一的一条。
  useAgentNavigation({
    workspaceId: workspace.id,
    onNavigate: (next, id) => {
      // 白名单在后端 mcp_server._VIEWS 那一侧,这里再挡一道:两边都可能先改。
      if (!VALID_VIEWS.includes(next)) return;
      if (next === "editor" && id) openProject(id);
      //: 画板走信箱:人已经在画板页上时只改 hash 没反应(见 lib/deepLink 的 openBoard)。
      else if (next === "boards" && id) openBoard(id);
      else if (id && ["scenes", "notes", "entities"].includes(next)) window.location.hash = `#/${next}?${next === "scenes" ? "scene" : next === "notes" ? "note" : "entity"}=${encodeURIComponent(id)}`;
      //: 工作流的 id:和 mosael:// 深链、任务中心「前往」同一条路(打开那一条工作流)。
      else if (next === "workflows" && id) gotoRecord("/workflows", VIEW_RECORD_EVENTS.workflows, id);
      else navigate(next as StudioView);
    },
  });
  // 新建项目的入口不止首页一处(顶栏切换器、剪辑页空态也有),所以在这里建一次往下传,
  // 而不是各页各建一个 —— 见 useCreateProject 里那条「先写缓存再跳转」的说明。
  const createProject = useCreateProject(workspace.id, openProject);

  // 桌面端外部唤起:mosael:// 深链(只导航)与拖到应用图标上的媒体文件(入库)。
  // 挂在 App 这一层,是因为它要跨页面生效——不能等某个页面挂载了才开始听。
  React.useEffect(() => {
    return listenDesktopDeepLinks((paths) => {
      void Promise.allSettled(
        paths.map((p) => importLocalAsset(workspace.id, p)),
      ).then((settled) => {
        const ok = settled.filter((r) => r.status === "fulfilled").length;
        if (ok) {
          void qc.invalidateQueries({ queryKey: assetKeys.all(workspace.id) });
          toast.success(t("importedAssets").replace("{n}", String(ok)));
        }
        const failed = settled.length - ok;
        if (failed)
          toast.error(t("importFailed").replace("{n}", String(failed)));
      });
    });
  }, [workspace.id, qc, t]);

  return (
    <RecordingProvider workspaceId={workspace.id}>
      <AppShell
        view={view}
        onViewChange={navigate}
        workspaceId={workspace.id}
        workspaceName={workspace.name}
        workspaces={workspaces}
        onSelectWorkspace={onSelectWorkspace}
        projectName={project?.name ?? null}
        projects={(projects.data ?? []).map((p) => ({ id: p.id, name: p.name }))}
        currentProjectId={project?.id ?? null}
        onSwitchProject={openProject}
        onCreateProject={() => createProject.mutate()}
        creatingProject={createProject.isPending}
      >
        {/* 页面按需加载(见 app/pages.tsx),所以渲染出口统一兜一层 —— 每个页面各写一次
            Suspense 的话,漏写的那一页在首次打开时会直接抛,而不是转一下菊花。 */}
        {/* 按需加载多了一种此前不存在的失败:那一块 JS 没取到。React.lazy 会把它**往上抛**,
            而 Suspense 不接错误 —— 没有这层边界的话整棵树卸掉,用户拿到一个永久白屏,
            连回上一页都做不到。见 app/PageBoundary。 */}
        <PageBoundary resetKey={view}>
        <React.Suspense fallback={<LoadingState label={t("pageLoading")} />}>
        {PAGE_RENDERERS[view]({
          workspace,
          project,
          projects: projects.data ?? [],
          projectsLoad: { pending: projects.isPending, error: projects.isError ? projects.error : null, retrying: projects.isFetching, retry: () => void projects.refetch() },
          openProject,
          createProject: () => createProject.mutate(),
          creatingProject: createProject.isPending,
          t,
        })}
        </React.Suspense>
        </PageBoundary>
        {/* 浮在页面上的这几块各自兜底,换一页就重新挂上(见 SectionBoundary 的 quiet)。 */}
        <SectionBoundary mode="quiet" resetKey={view}>
        <CommandPalette
          workspace={workspace}
          projects={projects.data ?? []}
          onNavigate={navigate}
          onOpenProject={openProject}
          onCreateProject={() => createProject.mutate()}
          creatingProject={createProject.isPending}
        />
        </SectionBoundary>
        <SectionBoundary mode="quiet" resetKey={view}>
        <ConfirmationCenter workspaceId={workspace.id} goHome={(session) => goHome(workspace.id, session)} />
        </SectionBoundary>
        {/* 把配音库的嗓子交给远端引擎念、这个账号第一次用它时那一问(ADR 0037)。挂在应用级:配音、字幕配音、
            画板、对话音色几处都会撞上同一个 409,确认框只有一个。 */}
        <SectionBoundary mode="quiet" resetKey={view}><RemoteVoiceConsentHost /></SectionBoundary>
        {/* 免提浮标挂在**应用级**,不挂在助手面板里:它存在的意义正是"手在别处、面板收起来了"
            的时候还叫得动。默认不浮,由设置里那个开关决定(本地偏好,见 app/preferences)。 */}
        {voiceDock && <SectionBoundary mode="quiet" resetKey={view}><VoiceDock workspaceId={workspace.id} onClose={() => setVoiceDock(false)} /></SectionBoundary>}
      </AppShell>
    </RecordingProvider>
  );
}
