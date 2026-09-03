import * as React from "react";
import { createRoot } from "react-dom/client";
import {
  Bot,
  Camera,
  CheckCircle2,
  CircleAlert,
  Download,
  Languages,
  Loader2,
  Play,
  RefreshCw,
  Search,
  Settings,
  Sparkles,
  Unplug,
  X,
} from "lucide-react";

import { Alert, AlertDescription } from "./components/ui/alert";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import { Card } from "./components/ui/card";
import { Input } from "./components/ui/input";
import { Label } from "./components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./components/ui/select";
import { Separator } from "./components/ui/separator";
import { cropScreenshot, frameDataUrlToBlob } from "./capture";
import { localeFromLanguage, translate, type MessageKey, type UiLocale } from "./i18n";
import { cn } from "./lib/utils";
import { MosaelClient, type BrowserProfile, type Job, type Project, type Workspace } from "./mosael/client";
import { mergePolledVideoContext } from "./platforms/detect";
import { videoPlatformLabel } from "./platforms/labels";
import type { CapturedVideoFrame, CaptureGeometry, ContentRequest, ContentResponse } from "./shared/protocol";
import type { Transcript, TranscriptCue, VideoContext } from "./shared/types";
import { alignSecondaryCues, languageMatches, transcriptTokensNeedSpace } from "./transcript";
import { resolveTranscriptSource } from "./transcript-source";

type Connection = {
  baseUrl: string;
  token: string;
  workspaceId: string;
  workspaceName: string;
  projectId: string;
  profileId: string;
};

type LocaleSetting = "auto" | UiLocale;
type SettingsNotice = { message: string; error: boolean } | null;
type TranscriptNotice = { message: string; kind: "loading" | "error" } | null;

const CONNECTION_KEY = "mosael.connection";
const LOCALE_KEY = "mosael.locale";
const NO_PROJECT = "__none__";
const NO_PROFILE = "__public__";

const TARGET_LANGUAGES = [
  ["zh-CN", "中文"],
  ["en", "English"],
  ["ja", "日本語"],
  ["ko", "한국어"],
  ["fr", "Français"],
  ["de", "Deutsch"],
  ["es", "Español"],
] as const;

function formatTime(seconds: number): string {
  const safe = Math.max(0, Number.isFinite(seconds) ? seconds : 0);
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const secs = Math.floor(safe % 60);
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`
    : `${minutes}:${String(secs).padStart(2, "0")}`;
}

function safeFilename(value: string): string {
  return value.replace(/[\\/:*?"<>|]/g, "-").replace(/\s+/g, " ").trim().slice(0, 120) || "video";
}

async function storedConnection(): Promise<Connection | null> {
  const stored = await chrome.storage.local.get(CONNECTION_KEY);
  const value = stored[CONNECTION_KEY];
  return value && typeof value === "object" ? (value as Connection) : null;
}

async function storedLocale(): Promise<LocaleSetting> {
  const stored = await chrome.storage.local.get(LOCALE_KEY);
  const value = stored[LOCALE_KEY];
  return value === "zh-CN" || value === "en" ? value : "auto";
}

async function activeBrowserTab(): Promise<chrome.tabs.Tab | null> {
  const tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  return tabs[0] || null;
}

async function sendToTab<T>(tab: chrome.tabs.Tab | null, message: ContentRequest, t: (key: MessageKey) => string): Promise<T> {
  if (!tab?.id) throw new Error(t("noActiveTab"));
  try {
    const response = (await chrome.tabs.sendMessage(tab.id, message)) as ContentResponse;
    if (!response?.ok) throw new Error(response?.error || t("pageUnresponsive"));
    return response.data as T;
  } catch (cause) {
    const messageText = cause instanceof Error ? cause.message : String(cause);
    if (/Receiving end does not exist|Could not establish connection/i.test(messageText)) {
      throw new Error(t("refreshVideoPage"));
    }
    throw cause;
  }
}

function cueMatches(cue: TranscriptCue, translationText: string, query: string): boolean {
  const normalized = query.trim().toLocaleLowerCase();
  return !normalized
    || cue.text.toLocaleLowerCase().includes(normalized)
    || translationText.toLocaleLowerCase().includes(normalized);
}

function Highlight({ value, query }: { value: string; query: string }): React.ReactNode {
  const normalized = query.trim();
  if (!normalized) return value;
  const index = value.toLocaleLowerCase().indexOf(normalized.toLocaleLowerCase());
  if (index < 0) return value;
  return (
    <>
      {value.slice(0, index)}
      <mark className="rounded-sm bg-primary/25 px-0.5 text-inherit">{value.slice(index, index + normalized.length)}</mark>
      {value.slice(index + normalized.length)}
    </>
  );
}

function localizePageError(message: string, t: (key: MessageKey) => string): string {
  if (/Failed to fetch|NetworkError|Load failed|fetch failed|字幕服务暂时无法连接|字幕服务响应超时|字幕服务请求失败/i.test(message)) {
    return t("transcriptFetchFailed");
  }
  if (/没有可用字幕|没有返回字幕|字幕内容为空|Unexpected end of JSON/i.test(message)) return t("noCaptions");
  return message;
}

function App(): React.ReactElement {
  const [localeSetting, setLocaleSetting] = React.useState<LocaleSetting>("auto");
  const [hydrated, setHydrated] = React.useState(false);
  const locale = localeSetting === "auto" ? localeFromLanguage(navigator.language) : localeSetting;
  const t = React.useCallback(
    (key: MessageKey, params: Record<string, string | number> = {}) => translate(locale, key, params),
    [locale],
  );

  const [connection, setConnection] = React.useState<Connection | null>(null);
  const [settingsOpen, setSettingsOpen] = React.useState(false);
  const [server, setServer] = React.useState("http://127.0.0.1:8800");
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [settingsNotice, setSettingsNotice] = React.useState<SettingsNotice>(null);
  const [connecting, setConnecting] = React.useState(false);
  const [workspaces, setWorkspaces] = React.useState<Workspace[]>([]);
  const [projects, setProjects] = React.useState<Project[]>([]);
  const [profiles, setProfiles] = React.useState<BrowserProfile[]>([]);

  const [activeTab, setActiveTab] = React.useState<chrome.tabs.Tab | null>(null);
  const activeTabRef = React.useRef<chrome.tabs.Tab | null>(null);
  const [context, setContext] = React.useState<VideoContext | null>(null);
  const [transcript, setTranscript] = React.useState<Transcript | null>(null);
  const [translations, setTranslations] = React.useState<string[] | null>(null);
  const [secondaryLanguageLabel, setSecondaryLanguageLabel] = React.useState("");
  const [targetLanguage, setTargetLanguage] = React.useState("zh-CN");
  const [query, setQuery] = React.useState("");
  const [transcriptNotice, setTranscriptNotice] = React.useState<TranscriptNotice>(null);
  const [canGenerate, setCanGenerate] = React.useState(false);
  const [translationBusy, setTranslationBusy] = React.useState(false);
  const [generationBusy, setGenerationBusy] = React.useState(false);
  const [generationLabel, setGenerationLabel] = React.useState("");
  const [importBusy, setImportBusy] = React.useState(false);
  const [captureBusy, setCaptureBusy] = React.useState(false);
  const [toast, setToast] = React.useState("");
  const refreshVersion = React.useRef(0);
  const cueRefs = React.useRef(new Map<number, HTMLLIElement>());

  const persistConnection = React.useCallback(async (next: Connection | null) => {
    setConnection(next);
    if (next) {
      await chrome.storage.local.set({ [CONNECTION_KEY]: next });
    } else {
      await chrome.storage.local.remove(CONNECTION_KEY);
    }
  }, []);

  const showToast = React.useCallback((message: string) => setToast(message), []);
  React.useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 3400);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const apiFor = React.useCallback((value = connection): MosaelClient => {
    if (!value?.token) throw new Error(t("connectionRequired"));
    return new MosaelClient({ baseUrl: value.baseUrl, token: value.token });
  }, [connection, t]);

  const loadDestinations = React.useCallback(async (value: Connection, available?: Workspace[]) => {
    const api = apiFor(value);
    const nextWorkspaces = available || await api.listWorkspaces();
    if (nextWorkspaces.length === 0) throw new Error(t("noWorkspace"));
    const workspace = nextWorkspaces.find((item) => item.id === value.workspaceId) || nextWorkspaces[0];
    const [nextProjects, nextProfiles] = await Promise.all([
      api.listProjects(workspace.id),
      api.listBrowserProfiles(workspace.id),
    ]);
    const next = {
      ...value,
      workspaceId: workspace.id,
      workspaceName: workspace.name,
      projectId: nextProjects.some((item) => item.id === value.projectId) ? value.projectId : "",
      profileId: nextProfiles.some((item) => item.id === value.profileId && item.enabled) ? value.profileId : "",
    };
    setWorkspaces(nextWorkspaces);
    setProjects(nextProjects);
    setProfiles(nextProfiles.filter((item) => item.enabled));
    await persistConnection(next);
  }, [apiFor, persistConnection, t]);

  const refreshActivePage = React.useCallback(async () => {
    const version = ++refreshVersion.current;
    const tab = await activeBrowserTab();
    let nextContext: VideoContext | null = null;
    activeTabRef.current = tab;
    setActiveTab(tab);
    setContext(null);
    setTranscript(null);
    setTranslations(null);
    setSecondaryLanguageLabel("");
    setCanGenerate(false);
    setTranscriptNotice({ message: t("readingPage"), kind: "loading" });
    try {
      nextContext = await sendToTab<VideoContext>(tab, { type: "GET_CONTEXT" }, t);
      if (version !== refreshVersion.current) return;
      if (!nextContext.supported && connection?.token && connection.workspaceId) {
        try {
          const support = await apiFor(connection).supportsVideoUrl(connection.workspaceId, nextContext.url);
          if (support.supported) {
            nextContext = {
              ...nextContext,
              supported: true,
              platform: "generic",
              extractor: support.extractor,
            };
          }
        } catch {
          // URL classification is an enhancement. A disconnected backend must not replace the
          // more useful page-level state with a connection error.
        }
      }
      if (version !== refreshVersion.current) return;
      setContext(nextContext);
      if (!nextContext.supported) {
        setTranscriptNotice(null);
        return;
      }
      setTranscriptNotice({ message: t("readingTranscript"), kind: "loading" });
      const resolved = await resolveTranscriptSource(
        () => sendToTab<Transcript>(tab, { type: "GET_TRANSCRIPT" }, t),
        connection?.token && connection.workspaceId
          ? () => apiFor(connection).findTranscriptFromVideo(connection.workspaceId, nextContext!.url)
          : undefined,
      );
      const nextTranscript = resolved.transcript;
      if (version !== refreshVersion.current) return;
      setTranscript(nextTranscript);
      setTargetLanguage(/^zh/i.test(nextTranscript.language) ? "en" : "zh-CN");
      setTranscriptNotice(null);
    } catch (cause) {
      if (version !== refreshVersion.current) return;
      const raw = cause instanceof Error ? cause.message : String(cause);
      setTranscriptNotice({ message: localizePageError(raw, t), kind: "error" });
      setCanGenerate(Boolean(nextContext?.supported));
    }
  }, [apiFor, connection, t]);

  React.useEffect(() => {
    document.documentElement.lang = locale;
    document.title = locale === "zh-CN" ? "Mosael 视频助手" : "Mosael Video Assistant";
  }, [locale]);

  React.useEffect(() => {
    void (async () => {
      const [savedLocale, savedConnection] = await Promise.all([storedLocale(), storedConnection()]);
      setLocaleSetting(savedLocale);
      if (savedConnection) {
        setConnection(savedConnection);
        setServer(savedConnection.baseUrl);
        try {
          await loadDestinations(savedConnection);
        } catch (cause) {
          setSettingsNotice({ message: cause instanceof Error ? cause.message : String(cause), error: true });
          setSettingsOpen(true);
        }
      }
      setHydrated(true);
    })();
  // Storage hydration deliberately runs once. Page refresh starts in the effect below with the restored locale.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  React.useEffect(() => {
    if (hydrated) void refreshActivePage();
  }, [hydrated, refreshActivePage]);

  React.useEffect(() => {
    const listener = (message: unknown) => {
      if ((message as { type?: string })?.type === "ACTIVE_TAB_CHANGED") void refreshActivePage();
    };
    chrome.runtime.onMessage.addListener(listener);
    return () => chrome.runtime.onMessage.removeListener(listener);
  }, [refreshActivePage]);

  React.useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden && activeTabRef.current) {
        void sendToTab<VideoContext>(activeTabRef.current, { type: "GET_CONTEXT" }, t)
          .then((polled) => setContext((current) => mergePolledVideoContext(current, polled)))
          .catch(() => undefined);
      }
    }, 600);
    return () => window.clearInterval(timer);
  }, [t]);

  const activeCueIndex = React.useMemo(() => {
    if (!transcript || !context) return -1;
    return transcript.cues.findIndex((cue) => context.currentTime >= cue.start && context.currentTime < cue.end);
  }, [context, transcript]);

  React.useEffect(() => {
    if (activeCueIndex < 0) return;
    cueRefs.current.get(activeCueIndex)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeCueIndex]);

  const requireConnection = React.useCallback((): Connection => {
    if (connection?.token && connection.workspaceId) return connection;
    setSettingsOpen(true);
    throw new Error(t("connectionRequired"));
  }, [connection, t]);

  const connect = async (event: React.FormEvent) => {
    event.preventDefault();
    setConnecting(true);
    setSettingsNotice({ message: t("connecting"), error: false });
    try {
      const api = new MosaelClient({ baseUrl: server });
      const auth = await api.login(username, password);
      const available = await api.listWorkspaces();
      const workspace = available[0];
      if (!workspace) throw new Error(t("noWorkspace"));
      const next = {
        baseUrl: api.baseUrl,
        token: auth.token,
        workspaceId: workspace.id,
        workspaceName: workspace.name,
        projectId: "",
        profileId: "",
      };
      setConnection(next);
      setPassword("");
      await loadDestinations(next, available);
      setSettingsNotice({ message: t("connectionSuccess"), error: false });
    } catch (cause) {
      setSettingsNotice({ message: cause instanceof Error ? cause.message : String(cause), error: true });
    } finally {
      setConnecting(false);
    }
  };

  const disconnect = async () => {
    try {
      if (connection?.token) await apiFor().logout();
    } catch {
      // Local credentials are removed even if the backend is currently unavailable.
    }
    await persistConnection(null);
    setWorkspaces([]);
    setProjects([]);
    setProfiles([]);
    setSettingsNotice({ message: t("disconnectedMessage"), error: false });
  };

  const changeLocale = async (value: string) => {
    const next = value === "zh-CN" || value === "en" ? value : "auto";
    setLocaleSetting(next);
    await chrome.storage.local.set({ [LOCALE_KEY]: next });
  };

  const changeWorkspace = async (workspaceId: string) => {
    if (!connection) return;
    const workspace = workspaces.find((item) => item.id === workspaceId);
    if (!workspace) return;
    await loadDestinations({ ...connection, workspaceId, workspaceName: workspace.name, projectId: "" });
  };

  const changeProject = async (projectId: string) => {
    if (!connection) return;
    await persistConnection({ ...connection, projectId: projectId === NO_PROJECT ? "" : projectId });
  };

  const changeProfile = async (profileId: string) => {
    if (!connection) return;
    await persistConnection({ ...connection, profileId: profileId === NO_PROFILE ? "" : profileId });
  };

  const generateTranscript = async () => {
    if (!context?.supported) throw new Error(t("supportedVideoRequired"));
    const destination = requireConnection();
    setGenerationBusy(true);
    setGenerationLabel(t("preparingVideo"));
    try {
      const generated = await apiFor(destination).generateTranscriptFromVideo({
        workspaceId: destination.workspaceId,
        projectId: destination.projectId || null,
        url: context.url,
        title: context.title,
        profileId: destination.profileId || null,
        onProgress: (stage: "import" | "transcribe", job: Job) => {
          const percent = Math.round(Math.max(0, Math.min(1, Number(job.progress) || 0)) * 100);
          const progress = percent ? ` ${percent}%` : "";
          setGenerationLabel(t(stage === "import" ? "downloadingVideo" : "transcribingAudio", { progress }));
        },
      });
      const nextTranscript: Transcript = {
        trackId: `mosael:${generated.assetId}`,
        language: generated.language,
        languageLabel: generated.language ? `Mosael · ${generated.language}` : "Mosael",
        cues: generated.cues,
        tracks: [],
      };
      setTranscript(nextTranscript);
      setTranslations(null);
      setSecondaryLanguageLabel("");
      setTargetLanguage(/^zh/i.test(generated.language) ? "en" : "zh-CN");
      setCanGenerate(false);
      setTranscriptNotice(null);
      showToast(t("generatedTranscript", { count: generated.cues.length }));
    } finally {
      setGenerationBusy(false);
      setGenerationLabel("");
    }
  };

  const showBilingual = async () => {
    if (!transcript) throw new Error(t("noTranscriptToTranslate"));
    const siteTrack = transcript.tracks.find(
      (track) => track.id !== transcript.trackId && languageMatches(track.language, targetLanguage),
    );
    setTranslationBusy(true);
    try {
      if (siteTrack) {
        const secondary = await sendToTab<Transcript>(activeTab, { type: "GET_TRANSCRIPT", trackId: siteTrack.id }, t);
        setTranslations(alignSecondaryCues(transcript.cues, secondary.cues));
        setSecondaryLanguageLabel(secondary.languageLabel);
      } else {
        const destination = requireConnection();
        const result = await apiFor(destination).translate(
          destination.workspaceId,
          transcript.cues.map((cue) => cue.text),
          targetLanguage,
        );
        setTranslations(result);
        setSecondaryLanguageLabel(TARGET_LANGUAGES.find(([value]) => value === targetLanguage)?.[1] || targetLanguage);
      }
      showToast(t("translatedTranscript", { count: transcript.cues.length }));
    } finally {
      setTranslationBusy(false);
    }
  };

  const importCurrentVideo = async () => {
    if (!context?.supported) throw new Error(t("supportedVideoRequired"));
    const destination = requireConnection();
    setImportBusy(true);
    try {
      const job = await apiFor(destination).importVideo(
        destination.workspaceId,
        destination.projectId || null,
        context.url,
        context.title,
        destination.profileId || null,
      );
      showToast(t("importCreated", { id: job.id }));
    } finally {
      setImportBusy(false);
    }
  };

  const captureCurrentFrame = async () => {
    if (!activeTab?.windowId || !context?.playable) throw new Error(t("playableVideoRequired"));
    const destination = requireConnection();
    setCaptureBusy(true);
    try {
      let frame: CapturedVideoFrame | null = null;
      try {
        frame = await sendToTab<CapturedVideoFrame>(activeTab, { type: "CAPTURE_VIDEO_FRAME" }, t);
      } catch {
        // Cross-origin media can taint a canvas. In that browser-enforced case, temporarily hide
        // every HTML overlay above the video before cropping the tab surface.
      }
      let blob: Blob;
      let title: string;
      let currentTime: number;
      if (frame) {
        blob = frameDataUrlToBlob(frame.dataUrl);
        title = frame.title;
        currentTime = frame.currentTime;
      } else {
        const geometry = await sendToTab<CaptureGeometry>(activeTab, { type: "PREPARE_FRAME_CAPTURE" }, t);
        try {
          const screenshot = await chrome.tabs.captureVisibleTab(activeTab.windowId, { format: "png" });
          blob = await cropScreenshot(screenshot, geometry);
        } finally {
          await sendToTab(activeTab, { type: "RESTORE_FRAME_CAPTURE" }, t).catch(() => undefined);
        }
        title = geometry.title;
        currentTime = geometry.currentTime;
      }
      const name = `${safeFilename(title)}-${currentTime.toFixed(1)}s.png`;
      await apiFor(destination).uploadFrame(destination.workspaceId, destination.projectId || null, name, blob);
      showToast(t("frameImported", { name }));
    } finally {
      setCaptureBusy(false);
    }
  };

  const run = (operation: () => Promise<void>) => void operation().catch((cause) => {
    showToast(cause instanceof Error ? cause.message : String(cause));
  });

  const filteredCues = React.useMemo(() => transcript?.cues
    .map((cue, index) => ({ cue, index, translated: translations?.[index] || "" }))
    .filter(({ cue, translated }) => cueMatches(cue, translated, query)) || [], [query, transcript, translations]);

  const transcriptLanguage = transcript
    ? secondaryLanguageLabel
      ? `${transcript.languageLabel} + ${secondaryLanguageLabel}`
      : transcript.languageLabel
    : "";

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-border bg-background/85 px-4 backdrop-blur-xl">
        <picture className="block size-10 shrink-0" aria-hidden="true">
          <source srcSet="mosael-icon-dark.png" media="(prefers-color-scheme: dark)" />
          <img src="mosael-icon-light.png" alt="" className="size-full object-contain" draggable={false} />
        </picture>
        <div className="min-w-0 flex-1 leading-tight">
          <div className="truncate text-sm font-bold">{t("brand")}</div>
          <div className="mt-1 truncate text-xs text-muted-foreground">{connection?.workspaceName || t("disconnected")}</div>
        </div>
        <Button variant="ghost" size="icon" title={t("refresh")} aria-label={t("refresh")} onClick={() => void refreshActivePage()}>
          <RefreshCw />
        </Button>
        <Button variant="ghost" size="icon" title={t("settings")} aria-label={t("settings")} onClick={() => setSettingsOpen(true)}>
          <Settings />
        </Button>
      </header>

      {settingsOpen ? (
        <main className="space-y-6 p-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h1 className="text-xl font-bold">{t("connectionTitle")}</h1>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{t("connectionDescription")}</p>
            </div>
            <Button variant="ghost" size="icon" aria-label={t("done")} onClick={() => setSettingsOpen(false)}><X /></Button>
          </div>

          <div className="space-y-2">
            <Label>{t("interfaceLanguage")}</Label>
            <Select value={localeSetting} onValueChange={(value) => void changeLocale(value)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="auto">{t("automaticLanguage")}</SelectItem>
                <SelectItem value="zh-CN">{t("chinese")}</SelectItem>
                <SelectItem value="en">{t("english")}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <Separator />

          {!connection?.token ? (
            <form className="space-y-4" onSubmit={(event) => void connect(event)}>
              <div className="space-y-2"><Label htmlFor="server">{t("backendUrl")}</Label><Input id="server" type="url" value={server} onChange={(event) => setServer(event.target.value)} required /></div>
              <div className="space-y-2"><Label htmlFor="username">{t("username")}</Label><Input id="username" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required /></div>
              <div className="space-y-2"><Label htmlFor="password">{t("password")}</Label><Input id="password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></div>
              <Button className="w-full" type="submit" loading={connecting}>{connecting ? t("connecting") : t("connect")}</Button>
            </form>
          ) : (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label>{t("workspace")}</Label>
                <Select value={connection.workspaceId} onValueChange={(value) => run(() => changeWorkspace(value))}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>{workspaces.map((item) => <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>{t("projectOptional")}</Label>
                <Select value={connection.projectId || NO_PROJECT} onValueChange={(value) => run(() => changeProject(value))}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NO_PROJECT}>{t("noProject")}</SelectItem>
                    {projects.map((item) => <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>{t("browserIdentityOptional")}</Label>
                <Select value={connection.profileId || NO_PROFILE} onValueChange={(value) => run(() => changeProfile(value))}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NO_PROFILE}>{t("publicAccess")}</SelectItem>
                    {profiles.map((item) => <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>)}
                  </SelectContent>
                </Select>
                <p className="text-xs leading-relaxed text-muted-foreground">{t("browserIdentityHelp")}</p>
              </div>
              <Button className="w-full" variant="destructive" onClick={() => void disconnect()}><Unplug />{t("disconnect")}</Button>
            </div>
          )}

          {settingsNotice ? (
            <Alert variant={settingsNotice.error ? "destructive" : "default"}>
              {settingsNotice.error ? null : <CheckCircle2 />}
              <AlertDescription>{settingsNotice.message}</AlertDescription>
            </Alert>
          ) : null}
        </main>
      ) : (
        <main>
          {context?.supported ? (
            <>
              <section className="space-y-3 border-b border-border p-4">
                <div className="flex items-center gap-2"><Badge>{context.platform ? videoPlatformLabel(context.platform, context.url) : ""}</Badge><span className="text-xs text-muted-foreground">{context.duration > 0 ? formatTime(context.duration) : ""}</span></div>
                <h1 className="break-words text-base font-bold leading-snug">{context.title}</h1>
                <div className="grid grid-cols-1 gap-2 min-[440px]:grid-cols-2">
                  <Button variant="outline" loading={importBusy} onClick={() => run(importCurrentVideo)}><Download />{t("importVideo")}</Button>
                  <Button variant="outline" loading={captureBusy} disabled={!context.playable} title={!context.playable ? t("playableVideoRequired") : undefined} onClick={() => run(captureCurrentFrame)}><Camera />{t("captureFrame")}</Button>
                </div>
              </section>

              <section>
                <div className="sticky top-16 z-20 flex flex-col items-stretch gap-3 min-[430px]:flex-row min-[430px]:items-center min-[430px]:justify-between border-b border-border bg-background/90 px-4 py-3 backdrop-blur-xl">
                  <div className="min-w-0"><div className="font-bold">{t("transcript")}</div><div className="mt-1 truncate text-xs text-muted-foreground">{transcriptLanguage}</div></div>
                  {transcript ? (
                  <div className="flex items-center gap-2 min-[430px]:shrink-0">
                    <Select value={targetLanguage} onValueChange={(value) => { setTargetLanguage(value); setTranslations(null); setSecondaryLanguageLabel(""); }}>
                      <SelectTrigger className="h-9 min-w-0 flex-1 border-input bg-field px-3 text-sm min-[430px]:w-[112px] min-[430px]:flex-none" aria-label={t("targetLanguage")}><Languages className="size-4 shrink-0" /><SelectValue /></SelectTrigger>
                      <SelectContent>{TARGET_LANGUAGES.map(([value, label]) => <SelectItem key={value} value={value}>{label}</SelectItem>)}</SelectContent>
                    </Select>
                    <Button variant="outline" size="sm" loading={translationBusy} onClick={() => run(showBilingual)}>{t("bilingualSubtitles")}</Button>
                  </div>
                  ) : null}
                </div>

                {transcript ? (
                <div className="p-4 pb-2">
                  <div className="relative"><Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" /><Input className="pl-9" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("searchTranscript")} /></div>
                </div>
                ) : null}

                {transcriptNotice ? (
                  <div className="px-4 py-8 text-center">
                    <div className={cn("mx-auto grid size-10 place-items-center rounded-full bg-muted text-muted-foreground", transcriptNotice.kind === "error" && "bg-destructive/10 text-destructive")}>
                      {transcriptNotice.kind === "loading" ? <Loader2 className="size-5 animate-spin" /> : <CircleAlert className="size-5" />}
                    </div>
                    <p className={cn("mx-auto mt-3 max-w-xs text-sm leading-relaxed text-muted-foreground", transcriptNotice.kind === "error" && "text-destructive")}>{transcriptNotice.message}</p>
                    {canGenerate ? <Button className="mt-5 w-full" loading={generationBusy} onClick={() => run(generateTranscript)}><Bot />{generationLabel || t("generateTranscript")}</Button> : null}
                  </div>
                ) : null}

                {transcript && filteredCues.length === 0 ? <div className="px-4 py-8 text-center text-sm text-muted-foreground">{t("noMatches")}</div> : null}

                <ol className="space-y-1 px-2 pb-6">
                  {filteredCues.map(({ cue, index, translated }) => (
                    <li key={`${cue.start}-${index}`} ref={(node) => { if (node) cueRefs.current.set(index, node); else cueRefs.current.delete(index); }}>
                      <div className={cn(
                        "flex w-full items-start rounded-xl px-3 py-2.5 text-left",
                        activeCueIndex === index && "bg-primary/15",
                      )}>
                        <Button
                          variant="ghost"
                          className="mr-1 h-auto w-12 shrink-0 justify-start rounded-md p-0 pt-0.5 font-mono text-[11px] font-normal text-muted-foreground"
                          disabled={!context.playable}
                          onClick={() => run(async () => { await sendToTab(activeTab, { type: "SEEK", seconds: cue.start }, t); setContext((current) => current ? { ...current, currentTime: cue.start } : current); })}
                        >
                          {formatTime(cue.start)}
                        </Button>
                        <span className="min-w-0 flex-1 break-words leading-relaxed">
                          {cue.tokens?.length ? cue.tokens.map((token, tokenIndex) => (
                            <React.Fragment key={`${token.start}-${tokenIndex}`}>
                              {tokenIndex > 0 && transcriptTokensNeedSpace(cue.tokens![tokenIndex - 1].text, token.text) ? " " : null}
                              <Button
                                variant="ghost"
                                className={cn(
                                  "inline h-auto min-w-0 rounded-sm px-0.5 py-0 align-baseline font-normal leading-[inherit] text-inherit",
                                  context && context.currentTime >= token.start && context.currentTime < token.end && "bg-primary/25",
                                )}
                                disabled={!context.playable}
                                onClick={() => run(async () => { await sendToTab(activeTab, { type: "SEEK", seconds: token.start }, t); setContext((current) => current ? { ...current, currentTime: token.start } : current); })}
                              >
                                <Highlight value={token.text} query={query} />
                              </Button>
                            </React.Fragment>
                          )) : (
                            <Button
                              variant="ghost"
                              className="inline h-auto min-w-0 whitespace-normal rounded-sm p-0 text-left align-baseline font-normal leading-[inherit] text-inherit"
                              disabled={!context.playable}
                              onClick={() => run(async () => { await sendToTab(activeTab, { type: "SEEK", seconds: cue.start }, t); setContext((current) => current ? { ...current, currentTime: cue.start } : current); })}
                            >
                              <Highlight value={cue.text} query={query} />
                            </Button>
                          )}
                          {translated ? <span className="mt-1 block text-xs leading-relaxed text-muted-foreground"><Highlight value={translated} query={query} /></span> : null}
                        </span>
                      </div>
                    </li>
                  ))}
                </ol>
              </section>
            </>
          ) : (
            <section className="grid min-h-[calc(100vh-4rem)] place-items-center p-8 text-center">
              <Card className="w-full border-0 bg-transparent p-6">
                <div className="mx-auto grid size-14 place-items-center rounded-2xl bg-primary/15 text-primary"><Play /></div>
                <h1 className="mt-5 text-lg font-bold">{t("openVideo")}</h1>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{transcriptNotice?.message || t("openVideoDescription")}</p>
              </Card>
            </section>
          )}
        </main>
      )}

      {toast ? (
        <Alert className="fixed bottom-4 left-4 right-4 z-50 border-border bg-popover">
          <Sparkles />
          <AlertDescription>{toast}</AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root");
createRoot(root).render(<App />);
