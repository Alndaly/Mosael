/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 「扫码一键创建」那个弹窗里的**版式**:二维码在上、说明在下,整体水平居中。
 *
 * 此前是一横排(左 188px 二维码方块、右两行说明):弹窗默认就 512px 宽,横排把说明挤在右边一窄条,
 * 二维码和文字各贴一边,看着不像一件事。维护者要的是「上下竖直、居中」—— 扫码这个动作是**一件事**,
 * 上面给码、下面说现在到哪一步。
 *
 * 版式与状态无关:生成中(转圈占位)、出码、失败(占位 + 失败原因)都是**同一个容器**,
 * 只换里面的两块。所以这里按三种状态各断一次,不是只断成功态。
 *
 * 尺寸不动:二维码仍由 `qrcode` 以 180 生成、占位块仍 188(180 + 两侧 p-1),不许为了塞进竖直版式把码缩小。
 */

const api = vi.hoisted(() => vi.fn());
const toDataURL = vi.hoisted(() => vi.fn(async () => "data:image/png;base64,qr"));

vi.mock("@/api/transport", () => ({ api }));
vi.mock("@/app/preferences", async () => {
  const { messages } = await import("@/app/messages");
  const table = messages["zh-CN"] as Record<string, string>;
  return { useI18n: () => (key: string) => table[key] ?? key };
});
vi.mock("qrcode", () => ({ default: { toDataURL } }));

import { messages } from "@/app/messages";
import { FeishuSection } from "@/features/settings/FeishuSection";

const zh = messages["zh-CN"] as Record<string, string>;
const WORKSPACE = { id: "ws-1", name: "W" } as never;
const QR_URL = "https://open.feishu.cn/page/launcher?code=abc";

/** 二维码生成失败时后端写进 `phase: "error"` 的那句话 —— 弹窗里要能看见它。 */
const ONBOARDING_ERROR = "飞书创建应用失败:该账号没有创建应用的权限";

type OnboardingReply = { phase: string; qr_url?: string | null; user_code?: string | null; error?: string | null };

/**
 * `post` 是 POST /onboarding 的回执,`get` 是轮询 GET 的回执。
 * POST 失败会**关掉弹窗**(请求都没打通,没什么可看的)—— 那是既有的轮询/绑定逻辑,这里不覆盖;
 * 这里说的「失败」是后端跑起来了、但二维码这一步失败(`phase: "error"`),弹窗还开着。
 */
function mockOnboarding(post: OnboardingReply | Promise<OnboardingReply>, get: OnboardingReply | Promise<OnboardingReply>) {
  api.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path.startsWith("/api/feishu/bots?")) return [];
    if (path.startsWith("/api/feishu/onboarding/")) return init?.method === "POST" ? post : get;
    throw new Error(`unexpected request: ${path}`);
  });
}

async function openScanDialog() {
  const user = userEvent.setup();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <FeishuSection workspace={WORKSPACE} />
    </QueryClientProvider>,
  );
  await user.click(await screen.findByRole("button", { name: zh.feishuScanCreate }));
  const dialog = await screen.findByRole("dialog");
  return { user, dialog };
}

const classes = (element: Element) => element.className.split(/\s+/).filter(Boolean);

/** 说明的第一行(`feishuScanHint`)—— 三种状态都有它,从它往上两级就是这个弹窗的版式容器。 */
const hintOf = (dialog: HTMLElement) => within(dialog).getByText(zh.feishuScanHint);
const copyOf = (dialog: HTMLElement) => hintOf(dialog).parentElement as HTMLElement;
const layoutOf = (dialog: HTMLElement) => copyOf(dialog).parentElement as HTMLElement;
const qrBlockOf = (dialog: HTMLElement) => layoutOf(dialog).firstElementChild as HTMLElement;

/** 版式:二维码与说明是同一列的**上下两项**,整列水平居中。 */
function expectVerticalLayout(dialog: HTMLElement) {
  const layout = layoutOf(dialog);
  expect(classes(layout)).toContain("flex");
  expect(classes(layout)).toContain("flex-col");
  expect(classes(layout)).not.toContain("flex-row");
  //: 列方向上的 items-center 就是「整体居中」:两块共用中线。
  expect(classes(layout)).toContain("items-center");
  //: 说明文字居中(此前左对齐贴右边)。
  expect(classes(layout)).toContain("text-center");

  const children = [...layout.children];
  expect(children).toHaveLength(2);
  //: 二维码在上、说明在下 —— 不是左一块右一块。
  expect(children[0]).toBe(qrBlockOf(dialog));
  expect(children[1]).toBe(copyOf(dialog));
  expect(qrBlockOf(dialog).contains(copyOf(dialog))).toBe(false);
  expect(copyOf(dialog)).toContainElement(hintOf(dialog));
}

beforeEach(() => {
  api.mockReset();
  toDataURL.mockClear();
});

describe("扫码一键创建弹窗的版式", () => {
  it("① 二维码块与说明是同一列里的上下两项,整列居中", async () => {
    mockOnboarding({ phase: "waiting_scan", qr_url: QR_URL }, { phase: "waiting_scan", qr_url: QR_URL });
    const { dialog } = await openScanDialog();
    await waitFor(() => expect(dialog.querySelector('img[alt="Feishu QR"]')).toBeTruthy());

    expectVerticalLayout(dialog);
  });

  it("② 说明文字居中,且在二维码下面 —— 两行说明不跑到码右边", async () => {
    mockOnboarding({ phase: "waiting_scan", qr_url: QR_URL }, { phase: "waiting_scan", qr_url: QR_URL });
    const { dialog } = await openScanDialog();
    await waitFor(() => expect(dialog.querySelector('img[alt="Feishu QR"]')).toBeTruthy());

    const layout = layoutOf(dialog);
    const copy = copyOf(dialog);
    const paragraphs = [...copy.querySelectorAll("p")];
    expect(paragraphs).toHaveLength(2);
    expect(paragraphs[0]).toBe(hintOf(dialog));
    //: 第二行是当前状态(已出码 → 等待扫码确认)。
    expect(paragraphs[1].textContent).toContain(zh.feishuWaitingScan);
    //: 说明容器继承居中,自己不再压左对齐。
    expect(classes(layout)).toContain("text-center");
    expect(classes(copy)).not.toContain("text-left");
    //: 二维码的 DOM 位置在说明之前(视觉上的「上面」)。
    expect(qrBlockOf(dialog).compareDocumentPosition(copy) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("③ 生成中:占位转圈在「上」,说明在「下」,同一个竖直结构", async () => {
    //: POST 迟迟不回 —— 正是「正在生成二维码…」那一屏。
    mockOnboarding(new Promise<never>(() => {}), { phase: "idle", qr_url: null });
    const { dialog } = await openScanDialog();
    await within(dialog).findByText(zh.feishuQrLoading);

    expectVerticalLayout(dialog);
    //: 占位块是尺寸的准星:188(= 180 的码 + 两侧 p-1),没有为了竖直版式把它改小。
    const placeholder = qrBlockOf(dialog);
    expect(classes(placeholder)).toEqual(expect.arrayContaining(["h-[188px]", "w-[188px]"]));
    expect(placeholder.querySelector("svg")).toBeTruthy();
    expect(within(dialog).getByText(zh.feishuQrLoading)).toBeTruthy();
  });

  it("③ 出码:二维码图片在「上」,说明在「下」,同一个竖直结构", async () => {
    mockOnboarding({ phase: "waiting_scan", qr_url: QR_URL }, { phase: "waiting_scan", qr_url: QR_URL });
    const { dialog } = await openScanDialog();
    await waitFor(() => expect(dialog.querySelector('img[alt="Feishu QR"]')).toBeTruthy());

    expectVerticalLayout(dialog);
    expect(qrBlockOf(dialog).tagName).toBe("IMG");
    expect(within(dialog).getByText(zh.feishuWaitingScan)).toBeTruthy();
  });

  it("③ 二维码出不来(失败):仍然是竖直结构,失败原因在说明那一行", async () => {
    mockOnboarding({ phase: "waiting_scan", qr_url: null }, { phase: "error", qr_url: null, error: ONBOARDING_ERROR });
    const { dialog } = await openScanDialog();
    await within(dialog).findByText((_, node) => node?.textContent === ONBOARDING_ERROR);

    expectVerticalLayout(dialog);
    expect(within(dialog).getByText(ONBOARDING_ERROR)).toBeTruthy();
  });

  it("③ 已扫成功:弹窗自己关掉(成功态不是另一套横排)", async () => {
    //: `phase: "done"` 会把 scanning 置回 false —— 弹窗关掉、刷新机器人列表。这是既有逻辑,
    //: 这里只确认成功不是「再画一横排」。GET 先挂住,让弹窗真的画出来,再把 done 交回去。
    let releaseDone = () => {};
    const pendingGet = new Promise<OnboardingReply>((resolve) => {
      releaseDone = () => resolve({ phase: "done", qr_url: null });
    });
    mockOnboarding({ phase: "waiting_scan", qr_url: QR_URL }, pendingGet);
    const { dialog } = await openScanDialog();
    expect(dialog).toBeTruthy();

    releaseDone();
    await waitFor(() => expect(dialog.isConnected).toBe(false));
  });

  it("④ 窄宽度不横滚:说明有宽度上限、能缩、自然折行,二维码尺寸不被压小", async () => {
    mockOnboarding({ phase: "waiting_scan", qr_url: QR_URL }, { phase: "waiting_scan", qr_url: QR_URL });
    const { dialog } = await openScanDialog();
    await waitFor(() => expect(dialog.querySelector('img[alt="Feishu QR"]')).toBeTruthy());

    const layout = layoutOf(dialog);
    const copy = copyOf(dialog);
    //: 说明容器不设死宽:给一个上限(行长)并允许缩到容器里。
    expect(classes(copy)).toContain("min-w-0");
    expect(classes(copy).some((one) => one.startsWith("max-w-"))).toBe(true);
    expect(classes(layout)).not.toContain("whitespace-nowrap");
    //: 弹窗里没有任何横向滚动/不换行的写法 —— 窄了就折行,不是把内容推出屏幕。
    expect(dialog.innerHTML).not.toMatch(/overflow-x-(?:auto|scroll)|whitespace-nowrap/);
    //: 码的生成尺寸不变(180),占位块仍是 188;竖直排布不靠缩小二维码换空间。
    expect(toDataURL).toHaveBeenCalledWith(QR_URL, { width: 180, margin: 1 });
    expect(qrBlockOf(dialog).className).not.toMatch(/(?:^|\s)w-(?!full)[^\s]+/);
  });
});
