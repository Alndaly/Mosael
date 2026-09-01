import { cropScreenshot } from "./capture";
import { OpenStudioClient, type Project, type Workspace } from "./openstudio/client";
import type { CaptureGeometry, ContentRequest, ContentResponse } from "./shared/protocol";
import type { Transcript, TranscriptCue, VideoContext } from "./shared/types";

type Connection = {
  baseUrl: string;
  token: string;
  workspaceId: string;
  workspaceName: string;
  projectId: string;
};

const CONNECTION_KEY = "openstudio.connection";

function element<T extends HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) throw new Error(`Missing #${id}`);
  return node as T;
}

const ui = {
  connectionStatus: element("connection-status"),
  settingsButton: element<HTMLButtonElement>("settings-button"),
  refreshButton: element<HTMLButtonElement>("refresh-button"),
  settingsView: element("settings-view"),
  videoView: element("video-view"),
  closeSettings: element<HTMLButtonElement>("close-settings-button"),
  loginForm: element<HTMLFormElement>("login-form"),
  serverInput: element<HTMLInputElement>("server-input"),
  usernameInput: element<HTMLInputElement>("username-input"),
  passwordInput: element<HTMLInputElement>("password-input"),
  connectButton: element<HTMLButtonElement>("connect-button"),
  connectedSettings: element("connected-settings"),
  workspaceSelect: element<HTMLSelectElement>("workspace-select"),
  projectSelect: element<HTMLSelectElement>("project-select"),
  disconnectButton: element<HTMLButtonElement>("disconnect-button"),
  settingsMessage: element("settings-message"),
  videoHeader: element("video-header"),
  platformBadge: element("platform-badge"),
  videoDuration: element("video-duration"),
  videoTitle: element("video-title"),
  importButton: element<HTMLButtonElement>("import-button"),
  captureButton: element<HTMLButtonElement>("capture-button"),
  emptyState: element("empty-state"),
  transcriptSection: element("transcript-section"),
  transcriptLanguage: element("transcript-language"),
  targetLanguage: element<HTMLSelectElement>("target-language"),
  translateButton: element<HTMLButtonElement>("translate-button"),
  searchInput: element<HTMLInputElement>("search-input"),
  transcriptStatus: element("transcript-status"),
  cueList: element<HTMLOListElement>("cue-list"),
  toast: element("toast"),
};

let connection: Connection | null = null;
let activeTab: chrome.tabs.Tab | null = null;
let context: VideoContext | null = null;
let transcript: Transcript | null = null;
let translations: string[] | null = null;
let refreshVersion = 0;
let toastTimer = 0;
let activeCueIndex: string | null = null;

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

function showToast(message: string): void {
  window.clearTimeout(toastTimer);
  ui.toast.textContent = message;
  ui.toast.hidden = false;
  toastTimer = window.setTimeout(() => { ui.toast.hidden = true; }, 3200);
}

function showSettings(open: boolean): void {
  ui.settingsView.hidden = !open;
  ui.videoView.hidden = open;
}

async function storedConnection(): Promise<Connection | null> {
  const result = await chrome.storage.local.get(CONNECTION_KEY);
  const value = result[CONNECTION_KEY];
  return value && typeof value === "object" ? (value as Connection) : null;
}

async function saveConnection(next: Connection | null): Promise<void> {
  connection = next;
  if (next) await chrome.storage.local.set({ [CONNECTION_KEY]: next });
  else await chrome.storage.local.remove(CONNECTION_KEY);
  renderConnection();
}

function client(): OpenStudioClient {
  if (!connection?.token) throw new Error("请先连接 Open Studio");
  return new OpenStudioClient({ baseUrl: connection.baseUrl, token: connection.token });
}

function renderConnection(): void {
  if (connection?.token) {
    ui.connectionStatus.textContent = connection.workspaceName || "已连接";
    ui.loginForm.hidden = true;
    ui.connectedSettings.hidden = false;
    ui.serverInput.value = connection.baseUrl;
  } else {
    ui.connectionStatus.textContent = "未连接";
    ui.loginForm.hidden = false;
    ui.connectedSettings.hidden = true;
  }
}

async function loadDestinations(workspaces?: Workspace[]): Promise<void> {
  if (!connection) return;
  const api = client();
  const available = workspaces || await api.listWorkspaces();
  if (available.length === 0) throw new Error("当前账户还没有工作区");
  const workspace = available.find((item) => item.id === connection?.workspaceId) || available[0];
  connection.workspaceId = workspace.id;
  connection.workspaceName = workspace.name;
  ui.workspaceSelect.replaceChildren(...available.map((item) => new Option(item.name, item.id, false, item.id === workspace.id)));
  const projects = await api.listProjects(workspace.id);
  renderProjects(projects);
  await saveConnection({ ...connection });
}

function renderProjects(projects: Project[]): void {
  const options = [new Option("不指定项目", "")];
  options.push(...projects.map((item) => new Option(item.name, item.id)));
  ui.projectSelect.replaceChildren(...options);
  ui.projectSelect.value = projects.some((item) => item.id === connection?.projectId) ? connection?.projectId || "" : "";
  if (connection) connection.projectId = ui.projectSelect.value;
}

async function activeBrowserTab(): Promise<chrome.tabs.Tab | null> {
  const tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  return tabs[0] || null;
}

async function sendToTab<T>(message: ContentRequest): Promise<T> {
  if (!activeTab?.id) throw new Error("没有活动标签页");
  try {
    const response = (await chrome.tabs.sendMessage(activeTab.id, message)) as ContentResponse;
    if (!response?.ok) throw new Error(response?.error || "页面没有响应");
    return response.data as T;
  } catch (cause) {
    const messageText = cause instanceof Error ? cause.message : String(cause);
    if (/Receiving end does not exist|Could not establish connection/i.test(messageText)) {
      throw new Error("请刷新当前视频页面，让扩展完成连接");
    }
    throw cause;
  }
}

function renderVideoContext(): void {
  const supported = Boolean(context?.supported);
  ui.videoHeader.hidden = !supported;
  ui.emptyState.hidden = supported;
  ui.transcriptSection.hidden = !supported;
  if (!context || !supported) return;
  ui.platformBadge.textContent = context.platform === "youtube" ? "YouTube" : "哔哩哔哩";
  ui.videoDuration.textContent = context.duration > 0 ? formatTime(context.duration) : "";
  ui.videoTitle.textContent = context.title;
}

function cueMatches(cue: TranscriptCue, translation: string, query: string): boolean {
  const normalized = query.trim().toLocaleLowerCase();
  return !normalized || cue.text.toLocaleLowerCase().includes(normalized) || translation.toLocaleLowerCase().includes(normalized);
}

function highlightedText(value: string, query: string): DocumentFragment {
  const fragment = document.createDocumentFragment();
  const normalized = query.trim();
  if (!normalized) {
    fragment.append(value);
    return fragment;
  }
  const index = value.toLocaleLowerCase().indexOf(normalized.toLocaleLowerCase());
  if (index < 0) {
    fragment.append(value);
    return fragment;
  }
  fragment.append(value.slice(0, index));
  const mark = document.createElement("mark");
  mark.textContent = value.slice(index, index + normalized.length);
  fragment.append(mark, value.slice(index + normalized.length));
  return fragment;
}

function renderCues(): void {
  if (!transcript) return;
  const query = ui.searchInput.value;
  const nodes: HTMLLIElement[] = [];
  transcript.cues.forEach((cue, index) => {
    const translated = translations?.[index] || "";
    if (!cueMatches(cue, translated, query)) return;
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "cue-button";
    button.dataset.index = String(index);
    button.dataset.start = String(cue.start);
    button.dataset.end = String(cue.end);
    button.setAttribute("aria-label", `${formatTime(cue.start)} ${cue.text}`);
    const time = document.createElement("span");
    time.className = "cue-time";
    time.textContent = formatTime(cue.start);
    const body = document.createElement("span");
    body.className = "cue-text";
    body.append(highlightedText(cue.text, query));
    if (translated) {
      const translation = document.createElement("span");
      translation.className = "cue-translation";
      translation.append(highlightedText(translated, query));
      body.append(translation);
    }
    button.append(time, body);
    button.addEventListener("click", () => void sendToTab({ type: "SEEK", seconds: cue.start }));
    item.append(button);
    nodes.push(item);
  });
  ui.cueList.replaceChildren(...nodes);
  ui.transcriptStatus.textContent = nodes.length === 0 ? "没有匹配的逐字稿" : "";
  ui.transcriptStatus.hidden = nodes.length > 0;
  activeCueIndex = null;
  updateActiveCue(context?.currentTime || 0);
}

function updateActiveCue(seconds: number): void {
  let active: HTMLButtonElement | null = null;
  for (const node of ui.cueList.querySelectorAll<HTMLButtonElement>(".cue-button")) {
    const isActive = seconds >= Number(node.dataset.start) && seconds < Number(node.dataset.end);
    node.classList.toggle("active", isActive);
    if (isActive) active = node;
  }
  const nextIndex = active?.dataset.index || null;
  if (active && nextIndex !== activeCueIndex && !active.matches(":hover")) {
    active.scrollIntoView({ block: "nearest" });
  }
  activeCueIndex = nextIndex;
}

async function refreshActivePage(): Promise<void> {
  const version = ++refreshVersion;
  activeTab = await activeBrowserTab();
  transcript = null;
  translations = null;
  ui.cueList.replaceChildren();
  ui.transcriptStatus.hidden = false;
  ui.transcriptStatus.textContent = "正在读取当前页面…";
  try {
    context = await sendToTab<VideoContext>({ type: "GET_CONTEXT" });
    if (version !== refreshVersion) return;
    renderVideoContext();
    if (!context.supported) return;
    ui.transcriptStatus.textContent = "正在读取逐字稿…";
    transcript = await sendToTab<Transcript>({ type: "GET_TRANSCRIPT" });
    if (version !== refreshVersion) return;
    ui.transcriptLanguage.textContent = transcript.languageLabel;
    ui.targetLanguage.value = /^zh/i.test(transcript.language) ? "en" : "zh-CN";
    renderCues();
  } catch (cause) {
    if (version !== refreshVersion) return;
    const message = cause instanceof Error ? cause.message : String(cause);
    if (context?.supported) {
      renderVideoContext();
      ui.transcriptStatus.hidden = false;
      ui.transcriptStatus.textContent = message;
    } else {
      context = null;
      renderVideoContext();
      ui.emptyState.querySelector("h1")!.textContent = "无法读取当前页面";
      ui.emptyState.querySelector("p")!.textContent = message;
    }
  }
}

async function requireConnection(): Promise<Connection> {
  if (connection?.token && connection.workspaceId) return connection;
  showSettings(true);
  throw new Error("请先连接 Open Studio 并选择素材工作区");
}

async function translateTranscript(): Promise<void> {
  if (!transcript) throw new Error("当前没有可翻译的逐字稿");
  const destination = await requireConnection();
  ui.translateButton.disabled = true;
  ui.translateButton.textContent = "翻译中…";
  try {
    translations = await client().translate(destination.workspaceId, transcript.cues.map((cue) => cue.text), ui.targetLanguage.value);
    renderCues();
    showToast(`已翻译 ${translations.length} 条逐字稿`);
  } finally {
    ui.translateButton.disabled = false;
    ui.translateButton.textContent = "翻译";
  }
}

async function importCurrentVideo(): Promise<void> {
  if (!context?.supported) throw new Error("当前不是受支持的视频页面");
  const destination = await requireConnection();
  ui.importButton.disabled = true;
  try {
    const job = await client().importVideo(destination.workspaceId, destination.projectId || null, context.url, context.title);
    showToast(`导入任务已创建（${job.id}）`);
  } finally {
    ui.importButton.disabled = false;
  }
}

async function captureCurrentFrame(): Promise<void> {
  if (!activeTab?.windowId) throw new Error("没有活动视频标签页");
  const destination = await requireConnection();
  ui.captureButton.disabled = true;
  try {
    const geometry = await sendToTab<CaptureGeometry>({ type: "GET_CAPTURE_GEOMETRY" });
    const screenshot = await chrome.tabs.captureVisibleTab(activeTab.windowId, { format: "png" });
    const blob = await cropScreenshot(screenshot, geometry);
    const name = `${safeFilename(geometry.title)}-${geometry.currentTime.toFixed(1)}s.png`;
    await client().uploadFrame(destination.workspaceId, destination.projectId || null, name, blob);
    showToast(`当前帧已导入素材库：${name}`);
  } finally {
    ui.captureButton.disabled = false;
  }
}

ui.settingsButton.addEventListener("click", () => showSettings(true));
ui.closeSettings.addEventListener("click", () => showSettings(false));
ui.refreshButton.addEventListener("click", () => void refreshActivePage());
ui.searchInput.addEventListener("input", renderCues);
ui.translateButton.addEventListener("click", () => void translateTranscript().catch((cause) => showToast(String(cause.message || cause))));
ui.importButton.addEventListener("click", () => void importCurrentVideo().catch((cause) => showToast(String(cause.message || cause))));
ui.captureButton.addEventListener("click", () => void captureCurrentFrame().catch((cause) => showToast(String(cause.message || cause))));

ui.loginForm.addEventListener("submit", (event) => {
  event.preventDefault();
  void (async () => {
    ui.connectButton.disabled = true;
    ui.settingsMessage.textContent = "正在连接…";
    try {
      const api = new OpenStudioClient({ baseUrl: ui.serverInput.value });
      const auth = await api.login(ui.usernameInput.value, ui.passwordInput.value);
      const workspaces = await api.listWorkspaces();
      const workspace = workspaces[0];
      if (!workspace) throw new Error("当前账户还没有工作区");
      await saveConnection({
        baseUrl: api.baseUrl,
        token: auth.token,
        workspaceId: workspace.id,
        workspaceName: workspace.name,
        projectId: "",
      });
      ui.passwordInput.value = "";
      await loadDestinations(workspaces);
      ui.settingsMessage.textContent = "连接成功";
    } catch (cause) {
      ui.settingsMessage.textContent = cause instanceof Error ? cause.message : String(cause);
    } finally {
      ui.connectButton.disabled = false;
    }
  })();
});

ui.workspaceSelect.addEventListener("change", () => {
  if (!connection) return;
  connection.workspaceId = ui.workspaceSelect.value;
  connection.workspaceName = ui.workspaceSelect.selectedOptions[0]?.textContent || "";
  connection.projectId = "";
  void loadDestinations().catch((cause) => { ui.settingsMessage.textContent = String(cause.message || cause); });
});

ui.projectSelect.addEventListener("change", () => {
  if (!connection) return;
  connection.projectId = ui.projectSelect.value;
  void saveConnection({ ...connection });
});

ui.disconnectButton.addEventListener("click", () => {
  void (async () => {
    const api = connection?.token ? client() : null;
    try {
      await api?.logout();
    } catch {
      // A missing/expired backend is not allowed to trap a user in the connected UI. The local
      // credential is removed regardless; a live backend session is revoked whenever reachable.
    }
    await saveConnection(null);
    ui.settingsMessage.textContent = "已断开连接";
  })();
});

chrome.runtime.onMessage.addListener((message) => {
  if (message?.type === "ACTIVE_TAB_CHANGED") void refreshActivePage();
});

window.setInterval(() => {
  if (!context?.supported || document.hidden) return;
  void sendToTab<VideoContext>({ type: "GET_CONTEXT" }).then((next) => {
    context = next;
    updateActiveCue(next.currentTime);
  }).catch(() => undefined);
}, 800);

void (async () => {
  connection = await storedConnection();
  renderConnection();
  if (connection) {
    try {
      await loadDestinations();
    } catch (cause) {
      ui.settingsMessage.textContent = cause instanceof Error ? cause.message : String(cause);
      showSettings(true);
    }
  }
  await refreshActivePage();
})();
