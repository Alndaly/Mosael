/** @vitest-environment jsdom */
/**
 * `<OverNativeView>`(ADR 0051「让开」那一类):原生视图在前台时,里面打开的弹窗抬过外壳、开着时请视图让开;视图不在前台时什么都不变。
 * 挂在里面的有命令面板、配音库嗓子交给远端引擎那一问(后台的请求撞上 409 才弹)、任务中心的详情框。
 */
import React from "react";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { OverNativeView } from "@/components/app/overNativeView";
import { AlertDialog, AlertDialogContent, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { resetNativeViewAside, settleNativeViewAside } from "@/components/ui/nativeViewAside";
import { resetNativeViewForTests } from "@/lib/nativeView";

let push: ((state: { visible: boolean }) => void) | null = null;
const setOverlay = vi.fn(async (_up: boolean) => undefined);

function desktop(visible: boolean) {
  vi.stubGlobal("mosaelPublish", {
    onViewState: (callback: (state: { visible: boolean }) => void) => {
      push = callback;
      callback({ visible });
      return () => (push = null);
    },
    setOverlay,
  });
  resetNativeViewForTests();
}

function Ask({ open }: { open: boolean }) {
  return (
    <OverNativeView>
      <AlertDialog open={open}>
        <AlertDialogContent>
          <AlertDialogTitle>交给远端引擎念?</AlertDialogTitle>
        </AlertDialogContent>
      </AlertDialog>
    </OverNativeView>
  );
}

afterEach(async () => {
  cleanup();
  await settleNativeViewAside();
  resetNativeViewAside();
  vi.unstubAllGlobals();
  resetNativeViewForTests();
  setOverlay.mockClear();
});

it("视图在前台:弹窗抬过外壳(z 205),开着时视图让开,关了视图回来", async () => {
  desktop(true);
  const view = render(<Ask open />);
  expect(screen.getByRole("alertdialog").className).toMatch(/z-\[205\]/);
  await waitFor(() => expect(setOverlay.mock.calls).toEqual([[true]]));
  view.rerender(<Ask open={false} />);
  await waitFor(() => expect(setOverlay.mock.calls).toEqual([[true], [false]]));
});

it("视图不在前台:和平时一样", async () => {
  desktop(false);
  render(<Ask open />);
  expect(screen.getByRole("alertdialog").className).not.toMatch(/z-\[205\]/);
  //: 没有拍画面这一步时,请视图让开是在弹窗挂上的那一刻同步发出去的:此刻没发就是没发
  expect(setOverlay).not.toHaveBeenCalled();
});

it("开着的时候视图亮起来(人点开了内嵌浏览器):跟着抬过去、请它让开", async () => {
  desktop(false);
  render(<Ask open />);
  act(() => push?.({ visible: true }));
  expect(screen.getByRole("alertdialog").className).toMatch(/z-\[205\]/);
  await waitFor(() => expect(setOverlay.mock.calls).toEqual([[true]]));
});
