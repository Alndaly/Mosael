import { EventEmitter } from "node:events";

import { beforeEach, describe, expect, it, vi } from "vitest";

type Listener = (details: { method: string; url: string; uploadData?: { bytes?: Buffer }[] },
                 callback: (response: { cancel?: boolean }) => void) => void;

/** 每个分区一个假会话:记下挂在 onBeforeRequest 上的那个监听、补发的请求。 */
const fake = vi.hoisted(() => {
  const sessions = new Map<string, { filter: unknown; listener: Listener | null; fetch: ReturnType<typeof vi.fn>; registered: number }>();
  const contents = new Map<string, unknown>();
  const drivers = new Map<string, { waitForFunction: ReturnType<typeof vi.fn>; evaluate: ReturnType<typeof vi.fn> }>();
  return { sessions, contents, drivers };
});

vi.mock("electron", () => ({
  session: {
    fromPartition: (partition: string) => {
      let one = fake.sessions.get(partition);
      if (!one) {
        one = { filter: null, listener: null, fetch: vi.fn(async () => ({ ok: true })), registered: 0 };
        fake.sessions.set(partition, one);
      }
      const entry = one;
      return {
        webRequest: {
          onBeforeRequest: (filter: unknown, listener: Listener) => {
            entry.filter = filter;
            entry.listener = listener;
            entry.registered += 1;
          },
        },
        fetch: entry.fetch,
      };
    },
  },
}));
vi.mock("./accountViews", () => ({
  sharedViews: () => ({
    currentContents: (id: string) => fake.contents.get(id) ?? null,
    existingDriver: (id: string) => fake.drivers.get(id) ?? null,
  }),
}));

const { comfyViewOpening, comfyViewShown, onComfyLoaded, resetComfyViews, setComfyNavigation } = await import("./comfyViews");
const { navigationScript } = await import("./comfyNavigation");

const PARTITION = "persist:pool-comfyui-c1";
const URL_ = "http://192.168.3.15:8188/";

function request(partition: string, method: string, url: string, body?: unknown) {
  const listener = fake.sessions.get(partition)?.listener;
  if (!listener) throw new Error("no guard on this partition");
  const callback = vi.fn();
  listener({ method, url, uploadData: body === undefined ? undefined : [{ bytes: Buffer.from(JSON.stringify(body)) }] }, callback);
  return callback.mock.calls[0]?.[0];
}

beforeEach(() => {
  resetComfyViews();
  fake.sessions.clear();
  fake.contents.clear();
  fake.drivers.clear();
});

describe("设置写回的闸只装在这个连接的分区上", () => {
  it("打开时装上,同一个分区只装一次;别的分区不碰", () => {
    comfyViewOpening(PARTITION, URL_);
    comfyViewOpening(PARTITION, URL_);
    expect(fake.sessions.get(PARTITION)?.registered).toBe(1);
    expect([...fake.sessions.keys()]).toEqual([PARTITION]);
    expect(fake.sessions.get(PARTITION)?.filter).toEqual({ urls: ["*://*/*api/settings*"] });
  });

  it("操控方式的写回拦下;混着别的键的批量拦下、补发剩下的;别的设置照常写", () => {
    comfyViewOpening(PARTITION, URL_);
    expect(request(PARTITION, "POST", "http://192.168.3.15:8188/api/settings/Comfy.Canvas.NavigationMode", "standard"))
      .toEqual({ cancel: true });
    expect(request(PARTITION, "POST", "http://192.168.3.15:8188/api/settings", {
      "Comfy.Canvas.MouseWheelScroll": "panning", "Comfy.Queue.QPOV2": false,
    })).toEqual({ cancel: true });
    expect(fake.sessions.get(PARTITION)?.fetch).toHaveBeenCalledExactlyOnceWith("http://192.168.3.15:8188/api/settings", {
      method: "POST", body: JSON.stringify({ "Comfy.Queue.QPOV2": false }), headers: { "Content-Type": "application/json" },
    });
    expect(request(PARTITION, "POST", "http://192.168.3.15:8188/api/settings/Comfy.ColorPalette", "dark")).toEqual({});
    expect(request(PARTITION, "GET", "http://192.168.3.15:8188/api/settings")).toEqual({});
  });
});

describe("操控方式", () => {
  function page() {
    const contents = new EventEmitter();
    const driver = { waitForFunction: vi.fn(async () => true), evaluate: vi.fn(async () => "applied") };
    fake.contents.set(PARTITION, contents);
    fake.drivers.set(PARTITION, driver);
    return { contents, driver };
  }

  it("页面就绪后按打开时的来源设好", async () => {
    const { driver } = page();
    comfyViewOpening(PARTITION, URL_);
    await expect(setComfyNavigation(PARTITION, "trackpad")).resolves.toBe("applied");
    expect(driver.evaluate).toHaveBeenCalledWith(navigationScript("http://192.168.3.15:8188", "trackpad"), expect.any(Number));
  });

  it("没经工作流库打开过(不知道来源)或前端一直没就绪:说没就绪,不跑脚本", async () => {
    const { driver } = page();
    await expect(setComfyNavigation(PARTITION, "mouse")).resolves.toBe("notReady");
    comfyViewOpening(PARTITION, URL_);
    driver.waitForFunction.mockResolvedValueOnce(false);
    await expect(setComfyNavigation(PARTITION, "mouse")).resolves.toBe("notReady");
    expect(driver.evaluate).not.toHaveBeenCalled();
  });

  it("每次载入 / 刷新之后再设一次;载入之后的回调(工作台的桥)也跑", async () => {
    const { contents, driver } = page();
    comfyViewOpening(PARTITION, URL_);
    comfyViewShown(PARTITION);
    comfyViewShown(PARTITION);
    const loaded = vi.fn();
    onComfyLoaded(PARTITION, loaded);
    contents.emit("did-finish-load");
    expect(driver.evaluate, "还没选过操控方式就不设").not.toHaveBeenCalled();
    expect(loaded).toHaveBeenCalledExactlyOnceWith(PARTITION);
    await setComfyNavigation(PARTITION, "trackpad");
    driver.evaluate.mockClear();
    contents.emit("did-finish-load");
    await vi.waitFor(() => expect(driver.evaluate).toHaveBeenCalledExactlyOnceWith(
      navigationScript("http://192.168.3.15:8188", "trackpad"), expect.any(Number)));
    expect(contents.listenerCount("did-finish-load"), "同一页只挂一次").toBe(1);
  });
});
