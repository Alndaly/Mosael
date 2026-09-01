export type Workspace = { id: string; name: string };
export type Project = { id: string; name: string; workspace_id: string };
export type ImportJob = { id: string; status: string };

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
    this.fetcher = fetcher;
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

  uploadFrame(workspaceId: string, projectId: string | null, name: string, blob: Blob): Promise<{ id: string }> {
    const form = new FormData();
    form.set("workspace_id", workspaceId);
    if (projectId) form.set("project_id", projectId);
    form.set("name", name);
    form.set("file", blob, name);
    return this.request<{ id: string }>("/api/assets/import", { method: "POST", body: form });
  }
}
