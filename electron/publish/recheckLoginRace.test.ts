/**
 * 后台复检跑到一半,用户点了「去登录」—— 复检的结论不许回写。
 *
 * 线上现场(视频号):复检刚 goto 创作页,登录流程就把同一个视图导航去了登录页;复检随后在
 * 「微信快捷登录」那一页上判了一次,回写 bound —— 人还没点确认,账号卡片就成了已登录。
 * 这台视图已经交给登录流程,账号状态归登录轮询管。
 */
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => {
  const driver = { goto: vi.fn(async () => {}), url: () => "https://channels.weixin.qq.com/login.html" };
  const views: Record<string, unknown> & { visibleAccountId: string | null } = {
    visibleAccountId: null,
    attachWindow: vi.fn(),
    getDriver: () => driver,
    configureAccount: vi.fn(async () => {}),
    show: vi.fn((id: string) => { views.visibleAccountId = id; }),
    hide: vi.fn(() => { views.visibleAccountId = null; }),
  };
  const adapter = { openCreatorPage: vi.fn(async () => {}), checkLogin: vi.fn(async () => false) };
  const backend = {
    heartbeat: vi.fn(async () => {}),
    markDue: vi.fn(async () => {}),
    claimTask: vi.fn(async () => ({ task: null })),
    claimCheck: vi.fn(async () => ({ account: null as unknown })),
    patchAccount: vi.fn(async () => {}),
    accountProxy: vi.fn(async () => null),
  };
  return { driver, views, adapter, backend };
});
vi.mock("electron", () => ({ app: { getPath: () => "/tmp" } }));
vi.mock("./accountViews", () => ({ createSharedViews: () => mocks.views, destroySharedViews: vi.fn() }));
vi.mock("./adapters", () => ({ createAdapter: () => mocks.adapter }));
vi.mock("./log", () => ({ plog: vi.fn() }));
vi.mock("./publishBackend", () => mocks.backend);
import { openLogin, startPublishWorker, stopPublishWorker } from "./publishWorker";

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  mocks.views.visibleAccountId = null;
});
afterEach(() => { stopPublishWorker(); vi.clearAllTimers(); vi.useRealTimers(); });

it("复检途中被登录接管:不回写复检结论", async () => {
  mocks.backend.claimCheck.mockResolvedValueOnce({
    account: { account_id: "wx", platform: "weixin-channels", binding_status: "login_required", proxy: null },
  });
  // 复检的那次 checkLogin 期间,用户点了登录;复检看到的是登录页上的半截现场,却答了「已登录」。
  mocks.adapter.checkLogin.mockImplementationOnce(async () => {
    await openLogin("wx", "weixin-channels");
    return true;
  });
  startPublishWorker({ window: {} as never });
  await vi.advanceTimersByTimeAsync(12_000);
  expect(mocks.adapter.checkLogin.mock.calls.length).toBeGreaterThan(1); // 登录轮询接着在问
  expect(mocks.backend.patchAccount).not.toHaveBeenCalledWith("wx", expect.objectContaining({ binding_status: "bound" }));
  expect(mocks.views.hide).not.toHaveBeenCalled(); // 人还在登录页上,内嵌浏览器不能自己收起
});
