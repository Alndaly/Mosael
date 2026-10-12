/**
 * 内嵌 ComfyUI 跟随 Mosael 的语言(见 comfyLocale 的文件头):两件事各测一头 ——
 * **载入之前**把服务器上那个值设成 Mosael 的语言(前端载入时读的就是它),以及**已经开着的那一页**当场换过来
 * (走前端自己的设置,不重新载入)。语言映射那一段(认不出的什么都不设)在这里钉住。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

/** 每个分区一个假会话(带 Cookie 的那个 fetch)、一个假驱动 —— 替身和 comfyViews.test.ts 同一套。 */
const fake = vi.hoisted(() => {
  const sessions = new Map<string, { fetch: ReturnType<typeof vi.fn> }>();
  const drivers = new Map<string, { waitForFunction: ReturnType<typeof vi.fn>; evaluate: ReturnType<typeof vi.fn> }>();
  return { sessions, drivers };
});

vi.mock("electron", () => ({
  session: {
    fromPartition: (partition: string) => {
      let one = fake.sessions.get(partition);
      if (!one) {
        one = { fetch: vi.fn(async () => ({ ok: true, status: 200 })) };
        fake.sessions.set(partition, one);
      }
      const entry = one;
      return { webRequest: { onBeforeRequest: vi.fn() }, fetch: entry.fetch };
    },
  },
}));
vi.mock("./accountViews", () => ({
  sharedViews: () => ({
    existingDriver: (id: string) => fake.drivers.get(id) ?? null,
    currentContents: () => null,
  }),
}));
vi.mock("./log", () => ({ plog: vi.fn() }));

const {
  comfyLocaleOf,
  comfyLocaleScript,
  comfySettingsUrl,
  matchComfyLocaleInPage,
  setComfyLocaleOnServer,
} = await import("./comfyLocale");
const { comfyViewOpening, resetComfyViews } = await import("./comfyViews");

const PARTITION = "persist:pool-comfyui-c1";
const URL_ = "http://192.168.3.15:8188";

beforeEach(() => {
  resetComfyViews();
  fake.sessions.clear();
  fake.drivers.clear();
});

describe("语言映射(只此一处)", () => {
  it("Mosael 的两种语言换成 ComfyUI 认的值;写法不同(地区 / 下划线 / 大小写)也认", () => {
    expect(comfyLocaleOf("zh-CN")).toBe("zh");
    expect(comfyLocaleOf("en-US")).toBe("en");
    expect(comfyLocaleOf("zh_CN")).toBe("zh");
    expect(comfyLocaleOf(" EN-us ")).toBe("en");
  });

  it("认不出的不猜:回 null(调用方什么都不设),不拿 en 顶替", () => {
    for (const one of ["ja-JP", "fr", "", "   ", null, undefined, "en US; rm -rf"])
      expect(comfyLocaleOf(one), String(one)).toBeNull();
  });
});

describe("设置那一条路", () => {
  it("按目录拼这个来源;查询串与锚点不算数;挂在子路径下也接得上", () => {
    expect(comfySettingsUrl("http://127.0.0.1:8120")).toBe("http://127.0.0.1:8120/api/settings/Comfy.Locale");
    expect(comfySettingsUrl("http://192.168.3.15:8188/#/somewhere?x=1")).toBe("http://192.168.3.15:8188/api/settings/Comfy.Locale");
    expect(comfySettingsUrl("https://box.example.ts.net/comfy/")).toBe("https://box.example.ts.net/comfy/api/settings/Comfy.Locale");
  });
});

describe("载入之前:把服务器上那个值设成 Mosael 的语言", () => {
  it("用这个视图分区的会话(带它的 Cookie / 代理)发 POST,body 是一个 JSON 串", async () => {
    await expect(setComfyLocaleOnServer({ partition: PARTITION, url: URL_, locale: "zh-CN" })).resolves.toBe("applied");
    expect(fake.sessions.get(PARTITION)?.fetch).toHaveBeenCalledExactlyOnceWith(
      "http://192.168.3.15:8188/api/settings/Comfy.Locale",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: '"zh"',
      }),
    );
  });

  it("认不出的语言:一个请求都不发(连这个分区的会话都不碰)", async () => {
    await expect(setComfyLocaleOnServer({ partition: PARTITION, url: URL_, locale: "ja-JP" })).resolves.toBe("unsupported");
    expect(fake.sessions.has(PARTITION)).toBe(false);
  });

  it("服务器不收(4xx/5xx)、发不出去:说没成、不抛 —— 语言跟不跟得上不挡着工作台开", async () => {
    fake.sessions.set(PARTITION, { fetch: vi.fn(async () => ({ ok: false, status: 403 })) });
    await expect(setComfyLocaleOnServer({ partition: PARTITION, url: URL_, locale: "zh" })).resolves.toBe("failed");
    fake.sessions.set(PARTITION, { fetch: vi.fn(async () => { throw new Error("ECONNREFUSED"); }) });
    await expect(setComfyLocaleOnServer({ partition: PARTITION, url: URL_, locale: "en" })).resolves.toBe("failed");
  });
});

describe("已经开着的那一页:当场换过来,不重新载入", () => {
  function page() {
    const driver = { waitForFunction: vi.fn(async () => true), evaluate: vi.fn(async () => "applied") };
    fake.drivers.set(PARTITION, driver);
    comfyViewOpening(PARTITION, URL_);
    return driver;
  }

  it("跑的是前端自己那条路(setting.set),脚本按打开时记下的来源现拼", async () => {
    const driver = page();
    await expect(matchComfyLocaleInPage({ partition: PARTITION, locale: "zh-CN" })).resolves.toBe("applied");
    expect(driver.evaluate).toHaveBeenCalledExactlyOnceWith(
      comfyLocaleScript("http://192.168.3.15:8188", "zh"),
      expect.any(Number),
    );
  });

  it("视图没打开过(不知道来源)、前端一直没就绪:说没就绪,不跑脚本", async () => {
    const driver = { waitForFunction: vi.fn(async () => true), evaluate: vi.fn(async () => "applied") };
    fake.drivers.set(PARTITION, driver);
    await expect(matchComfyLocaleInPage({ partition: PARTITION, locale: "zh" })).resolves.toBe("notReady");
    comfyViewOpening(PARTITION, URL_);
    driver.waitForFunction.mockResolvedValueOnce(false);
    await expect(matchComfyLocaleInPage({ partition: PARTITION, locale: "zh" })).resolves.toBe("notReady");
    expect(driver.evaluate).not.toHaveBeenCalled();
  });

  it("认不出的语言:不跑脚本", async () => {
    const driver = page();
    await expect(matchComfyLocaleInPage({ partition: PARTITION, locale: "ja-JP" })).resolves.toBe("unsupported");
    expect(driver.evaluate).not.toHaveBeenCalled();
  });
});

describe("页面里那段脚本", () => {
  it("先认来源,再认这个设置登不登记、可选值里有没有要的那个,才设", () => {
    const script = comfyLocaleScript("http://192.168.3.15:8188", "zh");
    expect(script).toContain('location.origin !== "http://192.168.3.15:8188"');
    expect(script).toContain('"Comfy.Locale"');
    expect(script).toContain("setting.set");
    expect(script).toContain('"zh"');
  });
});
