import { describe, expect, it, vi } from "vitest";

import { OpenStudioClient } from "../src/openstudio/client";


function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("OpenStudioClient", () => {
  it("keeps the native fetch receiver when no custom fetcher is supplied", async () => {
    const nativeLikeFetch = vi.fn(function (this: unknown) {
      if (this !== globalThis) throw new TypeError("Illegal invocation");
      return Promise.resolve(json({ token: "session", user: { id: "u1", username: "demo" } }));
    });
    vi.stubGlobal("fetch", nativeLikeFetch);

    const client = new OpenStudioClient({ baseUrl: "http://127.0.0.1:8800" });
    await client.login("demo", "secret");

    expect(nativeLikeFetch).toHaveBeenCalledOnce();
    vi.unstubAllGlobals();
  });

  it("revokes the stored backend session when disconnecting", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json({ ok: true }));
    const client = new OpenStudioClient({ baseUrl: "http://127.0.0.1:8800", token: "session", fetcher });

    await client.logout();

    expect(fetcher).toHaveBeenCalledOnce();
    expect(fetcher.mock.calls[0]?.[0]).toBe("http://127.0.0.1:8800/api/auth/logout");
    expect(fetcher.mock.calls[0]?.[1]?.method).toBe("POST");
    expect(new Headers(fetcher.mock.calls[0]?.[1]?.headers).get("Authorization")).toBe("Bearer session");
    expect(client.token).toBe("");
  });

  it("translates long transcripts in bounded batches without changing cue order", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const request = JSON.parse(String(init?.body));
      return json({ translations: request.texts.map((value: string) => `T:${value}`) });
    });
    const client = new OpenStudioClient({ baseUrl: "http://127.0.0.1:8800", token: "session", fetcher });
    const texts = Array.from({ length: 620 }, (_, index) => `cue-${index}`);

    const translations = await client.translate("workspace", texts, "en");

    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body)).texts).toHaveLength(500);
    expect(JSON.parse(String(fetcher.mock.calls[1]?.[1]?.body)).texts).toHaveLength(120);
    expect(translations).toHaveLength(620);
    expect(translations[0]).toBe("T:cue-0");
    expect(translations[619]).toBe("T:cue-619");
  });

  it("imports exactly the current page as one video job", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json({ id: "job-1", status: "queued" }));
    const client = new OpenStudioClient({ baseUrl: "http://127.0.0.1:8800/", token: "session", fetcher });

    await client.importVideo("workspace", "project", "https://www.youtube.com/watch?v=abc", "A video");

    expect(fetcher).toHaveBeenCalledOnce();
    expect(fetcher.mock.calls[0]?.[0]).toBe("http://127.0.0.1:8800/api/assets/import-url");
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toEqual({
      workspace_id: "workspace",
      project_id: "project",
      items: [{ url: "https://www.youtube.com/watch?v=abc", title: "A video" }],
      kind: "video",
      max_height: 0,
    });
  });

  it("imports, transcribes, and returns a timed transcript when a site has no captions", async () => {
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/api/assets/import-url")) return json({ id: "import-1", status: "queued" });
      if (path.endsWith("/api/jobs/import-1")) {
        return json({ id: "import-1", status: "succeeded", result: { asset_ids: ["asset-1"] } });
      }
      if (path.endsWith("/api/assets/asset-1/transcribe")) return json({ id: "transcribe-1", status: "queued" });
      if (path.endsWith("/api/jobs/transcribe-1")) {
        return json({ id: "transcribe-1", status: "succeeded", result: {} });
      }
      if (path.endsWith("/api/assets/asset-1/transcript")) {
        return json({
          language: "en",
          segments: [
            { start_time: 1.2, end_time: 3.5, text: "Hello" },
            { start_time: 3.5, end_time: 5, text: "world" },
          ],
        });
      }
      return json({ detail: "unexpected request" }, 404);
    });
    const client = new OpenStudioClient({ baseUrl: "http://127.0.0.1:8800", token: "session", fetcher });

    const generated = await client.generateTranscriptFromVideo({
      workspaceId: "workspace",
      projectId: null,
      url: "https://www.youtube.com/watch?v=abc",
      title: "A video",
    });

    expect(generated).toEqual({
      assetId: "asset-1",
      language: "en",
      cues: [
        { start: 1.2, end: 3.5, text: "Hello" },
        { start: 3.5, end: 5, text: "world" },
      ],
    });
    expect(fetcher.mock.calls.map(([input]) => String(input))).toEqual([
      "http://127.0.0.1:8800/api/assets/import-url",
      "http://127.0.0.1:8800/api/jobs/import-1",
      "http://127.0.0.1:8800/api/assets/asset-1/transcribe",
      "http://127.0.0.1:8800/api/jobs/transcribe-1",
      "http://127.0.0.1:8800/api/assets/asset-1/transcript",
    ]);
  });

  it("uploads a captured frame through the normal asset import seam", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json({ id: "asset-1" }));
    const client = new OpenStudioClient({ baseUrl: "http://127.0.0.1:8800", token: "session", fetcher });

    await client.uploadFrame("workspace", null, "frame-12.3.png", new Blob(["png"], { type: "image/png" }));

    const init = fetcher.mock.calls[0]?.[1];
    expect(fetcher.mock.calls[0]?.[0]).toBe("http://127.0.0.1:8800/api/assets/import");
    expect(init?.body).toBeInstanceOf(FormData);
    const form = init?.body as FormData;
    expect(form.get("workspace_id")).toBe("workspace");
    expect(form.get("project_id")).toBeNull();
    expect((form.get("file") as File).name).toBe("frame-12.3.png");
    expect(new Headers(init?.headers).has("Content-Type")).toBe(false);
  });
});
