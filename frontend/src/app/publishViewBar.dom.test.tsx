/** @vitest-environment jsdom */

/**
 * 内嵌浏览器的顶栏(PublishViewBar):拖它挪窗口。底下开着模态弹窗时也拖得动 —— 拖拽区按文档顺序合、后面的盖前面的
 * (见 test/dragRegions),弹窗的遮罩和内容都声明 no-drag、挂在 body 末尾;顶栏要排在它们后面。
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/app/preferences")>()),
  useI18n: () => (key: string) => key,
}));

import { PublishViewBar } from "@/app/App";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { declaresDrag, noDragAfter } from "@/test/dragRegions";

type ViewListener = (state: PublishViewState) => void;

function desktop(extra: Record<string, unknown> = {}) {
  let listener: ViewListener | null = null;
  vi.stubGlobal("mosaelPublish", {
    ...extra,
    onViewState: (callback: ViewListener) => {
      listener = callback;
      return () => (listener = null);
    },
    setPagesInset: vi.fn(async () => undefined),
    hideView: vi.fn(async () => undefined),
  });
  return (state: PublishViewState) => act(() => listener?.(state));
}

afterEach(() => vi.unstubAllGlobals());

describe("内嵌浏览器的顶栏拖得动窗口", () => {
  it("底下开着模态弹窗:顶栏排在弹窗的遮罩和内容(都声明 no-drag)后面", async () => {
    const show = desktop();
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <Dialog open>
          <DialogContent>
            <DialogTitle>打开其他网址</DialogTitle>
          </DialogContent>
        </Dialog>
        <PublishViewBar />
      </QueryClientProvider>,
    );
    //: 弹窗先开着(它的 portal 先挂上),内嵌浏览器后亮出来
    await waitFor(() => expect(document.querySelector(".modal-overlay")).not.toBeNull());
    show({ visible: true, accountId: "persist:pool-1", accountName: "档案", url: "https://example.com/", partition: "persist:pool-1", pages: [] });
    const bar = document.querySelector("[data-publish-back]")!.closest("[data-app-chrome]")!;
    expect(declaresDrag(bar), "顶栏是拖拽区").toBe(true);
    expect(noDragAfter(bar), "没有排在顶栏后面的 no-drag").toEqual([]);
  });
});

//: 地址栏是只有一个输入框的表单(没有按钮):按回车靠浏览器的隐式提交,和按钮的 type 无关 —— 这里钉住它照样去那个网址。
describe("内嵌浏览器的地址栏", () => {
  it("改了地址敲回车就去那个网址", async () => {
    const navigate = vi.fn(async () => undefined);
    const show = desktop({ navigate, focusPage: vi.fn(async () => undefined) });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <PublishViewBar />
      </QueryClientProvider>,
    );
    show({ visible: true, accountId: "persist:pool-1", accountName: "档案", url: "https://example.com/", partition: "persist:pool-1", pages: [] });
    const user = userEvent.setup();
    const address = await screen.findByPlaceholderText("addressPlaceholder");
    await user.clear(address);
    await user.type(address, "https://mosael.app/{Enter}");
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("https://mosael.app/"));
  });
});
