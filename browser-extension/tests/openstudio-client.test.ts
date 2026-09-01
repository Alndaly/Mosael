import { describe, expect, it, vi } from "vitest";

import { OpenStudioClient } from "../src/openstudio/client";


function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("OpenStudioClient", () => {
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
