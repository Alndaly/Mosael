/**
 * 字幕翻译的两道闸:**单批超时**与**取消**,以及进度必须按批往前走。
 *
 * 真机反馈:1039 条字幕点「翻译」,按钮停在「翻译中 0/1039…」不动,也没有取消的入口。
 * 原因是这条链在客户端**没有任何超时**(`api()` 里的 fetch 只把 signal 传下去,没人建),
 * 而后端 Google 免费端点是**一句一句串行**的(见 backend/app/domain/translate.py 的
 * `_GOOGLE_MIN_INTERVAL_SECONDS`),一整批 400 句光起点间隔就要 140 秒 —— 进度只在整批回来时
 * 才动一次。加上默认引擎(Google)在部分网络下根本连不上,前端就永远停在 0。
 *
 * 这里钉住的是**出口**(`translateTexts`)的行为:每批有上限、整次有总预算、说得停、进度按批回调。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { translateTexts } from "@/api/client";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

/** fetch 的「永不返回」替身:真的和浏览器一样认 AbortSignal —— 掐了就 reject AbortError。 */
function never(init?: RequestInit): Promise<Response> {
  return new Promise<Response>((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), {
      once: true,
    });
  });
}

function reply(translations: string[]) {
  return new Response(JSON.stringify({ translations }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

describe("一批请求一直不返回", () => {
  it("到点明确失败(超时),而不是永远挂着", async () => {
    fetchMock.mockImplementation((_url: string, init: RequestInit) => never(init));
    const started = Date.now();
    await expect(
      translateTexts("w1", ["a", "b", "c"], "en", "", undefined, { batchTimeoutMs: 50 } as never),
    ).rejects.toMatchObject({ name: "TranslationTimeout" });
    expect(Date.now() - started).toBeLessThan(2_000);
    //: 掐的是**这一批**的 fetch,不是把后面所有请求一起放行。
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect((fetchMock.mock.calls[0][1] as RequestInit).signal?.aborted).toBe(true);
  });

  it("总预算用完也明确失败(不是一批一批拖到天荒地老)", async () => {
    fetchMock.mockImplementation((_url: string, init: RequestInit) => never(init));
    await expect(
      translateTexts("w1", ["a", "b", "c"], "en", "", undefined, { deadlineMs: 40 } as never),
    ).rejects.toMatchObject({ name: "TranslationDeadlineExceeded" });
  });
});

describe("取消", () => {
  it("signal 一掐:正在等的那批当场停,抛可辨认的取消,不再发下一批", async () => {
    fetchMock.mockImplementation((_url: string, init: RequestInit) => never(init));
    const controller = new AbortController();
    const pending = translateTexts("w1", ["a", "b", "c"], "en", "", undefined, {
      signal: controller.signal,
    } as never);
    setTimeout(() => controller.abort(), 20);
    await expect(pending).rejects.toMatchObject({ name: "TranslationCancelled" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect((fetchMock.mock.calls[0][1] as RequestInit).signal?.aborted).toBe(true);
  });

  it("已经取消的 signal 不再发请求", async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(
      translateTexts("w1", ["a"], "en", "", undefined, { signal: controller.signal } as never),
    ).rejects.toMatchObject({ name: "TranslationCancelled" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("进度按批前进", () => {
  it("375 条按 125 一批:每批回来就回调一次,偏移 0 / 125 / 250", async () => {
    fetchMock.mockImplementation(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(String(init.body));
      return reply((body.texts as string[]).map((text) => `T:${text}`));
    });
    const handed: Array<{ offset: number; count: number }> = [];
    const texts = Array.from({ length: 375 }, (_, i) => `c${i}`);
    const { translations } = await translateTexts("w1", texts, "en", "", async (batch, offset) => {
      handed.push({ offset, count: batch.length });
    });
    expect(handed).toEqual([
      { offset: 0, count: 125 },
      { offset: 125, count: 125 },
      { offset: 250, count: 125 },
    ]);
    expect(translations).toHaveLength(375);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
