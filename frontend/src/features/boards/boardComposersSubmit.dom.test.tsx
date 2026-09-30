/** @vitest-environment jsdom */
/**
 * 面板的提交键要转到**请求落地**为止:画布把 run 的 Promise 交给面板(useSubmitting 等它)。
 *
 * 此前 boardComposers 里是 `void run(...)`:面板拿到的是 undefined,按钮一点就恢复,连点两下发两次 ——
 * 两份钱,第二份的回执还和第一份抢同一格。
 */
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import type { BoardItem } from "@/api/client";
import { renderComposer, type ComposerHost } from "./boardComposers";
import { NO_UPSTREAM } from "./boardUpstream";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@xyflow/react", () => ({
  NodeToolbar: ({ children }: { children: React.ReactNode }) => children,
  Position: { Bottom: "bottom" },
}));
vi.mock("@tanstack/react-query", () => ({ useQuery: () => ({ data: [] }) }));

it("截挂了就地重截:请求在路上时按钮不恢复,连点只发一次;落地之后才能再点", async () => {
  let land!: () => void;
  const run = vi.fn(() => new Promise<void>((resolve) => (land = resolve)));
  const item = {
    id: "cut", kind: "video", x: 0, y: 0,
    form: { producer: "trim", trim: { asset_id: "src", start: 0, end: 3, mute: false } },
    run: { status: "failed" },
  } as BoardItem;
  const host = {
    item, position: { x: 0, y: 0 }, workspaceId: "w", feeding: NO_UPSTREAM, documents: new Map(), models: [],
    onFormChange: vi.fn(), onPickAsset: vi.fn(), run,
  } as unknown as ComposerHost;
  render(<>{renderComposer("trim", host)}</>);

  const submit = () => fireEvent.click(screen.getByRole("button", { name: /boardTrimSubmit/ }));
  submit();
  //: 让已经就绪的微任务都跑完 —— 交回的不是那次请求的话,按钮在这里就恢复了。
  await act(async () => {});
  submit();
  expect(run).toHaveBeenCalledTimes(1);

  await act(async () => {
    land();
  });
  submit();
  expect(run).toHaveBeenCalledTimes(2);
});
