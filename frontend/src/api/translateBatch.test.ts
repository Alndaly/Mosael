/**
 * 字幕多到超过一次请求的上限时,分批,而不是报错。
 *
 * 真机反馈:「翻译最多只能翻译 500 条 超出就会报错」。那个 500 是后端防止一次请求打垮自己的
 * 安全阀(api/schemas.TranslateRequest),不是"能翻多少字幕"的答案 —— 一条一小时视频的字幕轨
 * 轻松上千条,而用户看到的是「翻译失败」。
 *
 * 分批放在 `translateTexts` 里,因为它是唯一出口:让两个调用方各自切一遍是同一件事写两遍,
 * 漏掉一处就又是一条"超过 N 条就报错"。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

//: `api` 就定义在 client.ts 自己里面,所以打桩打在 fetch 这一层 —— 也更真实:
//: 分批要真的变成几次 HTTP 请求才算数。
const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

/** 把 fetch 的入参还原成后端会看到的那个请求体。 */
function bodiesSentTo(mock: typeof fetchMock): Array<{ texts: string[]; target_lang: string; engine: string; workspace_id: string }> {
  return mock.mock.calls.map(([, init]) => JSON.parse(String((init as RequestInit).body)));
}

function reply(payload: unknown) {
  return { ok: true, status: 200, json: async () => payload } as unknown as Response;
}

describe("翻译分批", () => {
  it("1000 条分几次送出去,顺序和条数都对得上", async () => {
    const { translateTexts } = await import("@/api/client");
    fetchMock.mockImplementation(async (_url: string, init: RequestInit) => {
      // 回一份能验证顺序的:每条前面加 "T:"
      const body = JSON.parse(String(init.body));
      return reply({ translations: (body.texts as string[]).map((x: string) => `T:${x}`) });
    });

    const texts = Array.from({ length: 1000 }, (_, i) => `cue-${i}`);
    const { translations } = await translateTexts("w1", texts, "en");

    expect(translations).toHaveLength(1000);
    expect(translations[0]).toBe("T:cue-0");
    expect(translations[999]).toBe("T:cue-999");
    expect(fetchMock.mock.calls.length).toBeGreaterThan(1);
    // 每一批都不能超过后端的上限,否则分批等于没分。
    for (const body of bodiesSentTo(fetchMock)) {
      expect(body.texts.length).toBeLessThanOrEqual(500);
    }
  });

  it("少量字幕仍然只发一次 —— 别为了分批把常见情形也拆开", async () => {
    const { translateTexts } = await import("@/api/client");
    fetchMock.mockResolvedValue(reply({ translations: ["a", "b"] }));
    await translateTexts("w1", ["x", "y"], "en");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("引擎和目标语言每一批都带上", async () => {
    const { translateTexts } = await import("@/api/client");
    fetchMock.mockImplementation(async (_url: string, init: RequestInit) =>
      reply({ translations: (JSON.parse(String(init.body)).texts as string[]).map(() => "") }),
    );
    await translateTexts("w1", Array.from({ length: 900 }, (_, i) => `c${i}`), "ja", "ai");
    expect(fetchMock.mock.calls.length).toBeGreaterThan(1);
    for (const body of bodiesSentTo(fetchMock)) {
      expect(body.target_lang).toBe("ja");
      expect(body.engine).toBe("ai");
      expect(body.workspace_id).toBe("w1");
    }
  });
});
