export type Workspace = { id: string; name: string };
export type Project = { id: string; name: string; workspace_id: string };
export type ImportJob = { id: string; status: string };
export type Job = {
  id: string;
  status: string;
  progress?: number | null;
  error?: string | null;
  result?: Record<string, unknown> | null;
};
export type GeneratedTranscript = {
  assetId: string;
  language: string;
  cues: Array<{ start: number; end: number; text: string }>;
};

type ClientOptions = {
  baseUrl: string;
  token?: string;
  fetcher?: typeof fetch;
};

type AuthResult = {
  token: string;
  user: { id: string; username: string; display_name?: string };
};

const TRANSLATE_BATCH = 500;

function cleanBaseUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

async function responseError(response: Response): Promise<Error> {
  let detail = "";
  try {
    const body = await response.json();
    detail = typeof body?.detail === "string" ? body.detail : JSON.stringify(body?.detail || body);
  } catch {
    detail = await response.text().catch(() => "");
  }
  return new Error(detail || `Open Studio 请求失败（${response.status}）`);
}

export class OpenStudioClient {
  readonly baseUrl: string;
  token: string;
  private readonly fetcher: typeof fetch;

  constructor({ baseUrl, token = "", fetcher = fetch }: ClientOptions) {
    this.baseUrl = cleanBaseUrl(baseUrl);
    this.token = token;
    // Window.fetch is a Web-IDL method in Chrome. Calling a stored reference as
    // `this.fetcher(...)` otherwise gives it the client instance as its receiver and Chrome
    // rejects the request with `Illegal invocation` before it ever reaches the backend.
    this.fetcher = (input, init) => fetcher.call(globalThis, input, init);
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const form = init.body instanceof FormData;
    const response = await this.fetcher(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        ...(form ? {} : { "Content-Type": "application/json" }),
        "Accept-Language": "zh-CN",
        "X-Open-Studio-Client": "browser-extension",
        ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
        ...(init.headers || {}),
      },
    });
    if (!response.ok) throw await responseError(response);
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  async login(username: string, password: string): Promise<AuthResult> {
    const result = await this.request<AuthResult>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    this.token = result.token;
    return result;
  }

  async logout(): Promise<void> {
    await this.request<{ ok: true }>("/api/auth/logout", { method: "POST" });
    this.token = "";
  }

  listWorkspaces(): Promise<Workspace[]> {
    return this.request<Workspace[]>("/api/workspaces");
  }

  listProjects(workspaceId: string): Promise<Project[]> {
    return this.request<Project[]>(`/api/projects?workspace_id=${encodeURIComponent(workspaceId)}`);
  }

  async translate(workspaceId: string, texts: string[], targetLanguage: string): Promise<string[]> {
    const translations: string[] = [];
    for (let offset = 0; offset < texts.length; offset += TRANSLATE_BATCH) {
      const result = await this.request<{ translations: string[] }>("/api/translate", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: workspaceId,
          texts: texts.slice(offset, offset + TRANSLATE_BATCH),
          target_lang: targetLanguage,
          engine: "google",
        }),
      });
      translations.push(...result.translations);
    }
    return translations;
  }

  importVideo(workspaceId: string, projectId: string | null, url: string, title: string): Promise<ImportJob> {
    return this.request<ImportJob>("/api/assets/import-url", {
      method: "POST",
      body: JSON.stringify({
        workspace_id: workspaceId,
        project_id: projectId,
        items: [{ url, title }],
        kind: "video",
        max_height: 0,
      }),
    });
  }

  private async waitForJob(jobId: string, onProgress?: (job: Job) => void): Promise<Job> {
    const deadline = Date.now() + 30 * 60_000;
    while (Date.now() < deadline) {
      const job = await this.request<Job>(`/api/jobs/${encodeURIComponent(jobId)}`);
      onProgress?.(job);
      if (job.status === "succeeded") return job;
      if (job.status === "failed" || job.status === "cancelled") {
        throw new Error(job.error || "Open Studio 任务未能完成");
      }
      await new Promise((resolve) => setTimeout(resolve, 1_200));
    }
    throw new Error("Open Studio 生成逐字稿超时，请在任务中心查看进度");
  }

  async generateTranscriptFromVideo({
    workspaceId,
    projectId,
    url,
    title,
    onProgress,
  }: {
    workspaceId: string;
    projectId: string | null;
    url: string;
    title: string;
    onProgress?: (stage: "import" | "transcribe", job: Job) => void;
  }): Promise<GeneratedTranscript> {
    const importJob = await this.importVideo(workspaceId, projectId, url, title);
    const imported = await this.waitForJob(importJob.id, (job) => onProgress?.("import", job));
    const assetIds = imported.result?.asset_ids;
    const assetId = Array.isArray(assetIds) && typeof assetIds[0] === "string" ? assetIds[0] : "";
    if (!assetId) throw new Error("视频已下载，但 Open Studio 没有返回素材编号");

    const transcription = await this.request<ImportJob>(`/api/assets/${encodeURIComponent(assetId)}/transcribe`, {
      method: "POST",
    });
    await this.waitForJob(transcription.id, (job) => onProgress?.("transcribe", job));
    const transcript = await this.request<{
      language?: string | null;
      segments?: Array<{ start_time?: number; end_time?: number; text?: string }>;
    }>(`/api/assets/${encodeURIComponent(assetId)}/transcript`);
    const cues = (transcript.segments || []).flatMap((segment) => {
      const start = Number(segment.start_time);
      const end = Number(segment.end_time);
      const text = String(segment.text || "").trim();
      return Number.isFinite(start) && Number.isFinite(end) && text
        ? [{ start: Math.max(0, start), end: Math.max(start, end), text }]
        : [];
    });
    if (cues.length === 0) throw new Error("Open Studio 已完成识别，但逐字稿内容为空");
    return { assetId, language: String(transcript.language || ""), cues };
  }

  uploadFrame(workspaceId: string, projectId: string | null, name: string, blob: Blob): Promise<{ id: string }> {
    const form = new FormData();
    form.set("workspace_id", workspaceId);
    if (projectId) form.set("project_id", projectId);
    form.set("name", name);
    form.set("file", blob, name);
    return this.request<{ id: string }>("/api/assets/import", { method: "POST", body: form });
  }
}
