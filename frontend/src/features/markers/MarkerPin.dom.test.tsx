/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { MarkerPin } from "./MarkerPin";
import { MarkerEditorProvider } from "./MarkerEditorProvider";
import type { CanvasMarker } from "./markers";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

const marker: CanvasMarker = { id: "m1", name: "分镜起点", x: 0, y: 0, shortcut: "Alt+1" };

function pin(overrides: Partial<CanvasMarker> = {}, handlers: { onChange?: () => void; onDelete?: () => void } = {}) {
  const data = {
    editable: true,
    marker: { ...marker, ...overrides },
    markers: [{ ...marker, ...overrides }],
    onChange: handlers.onChange ?? vi.fn(),
    onDelete: handlers.onDelete ?? vi.fn(),
  };
  // NodeProps 有二十来个 React Flow 内部字段,这里只喂组件真正读的那两个。
  return render(<MarkerPin {...({ data, selected: false } as unknown as React.ComponentProps<typeof MarkerPin>)} />, { wrapper: MarkerEditors });
}

function MarkerEditors({ children }: { children: React.ReactNode }) {
  return <MarkerEditorProvider enabled>{children}</MarkerEditorProvider>;
}

it("旗子上就印着名字和绑定的键 —— 不然「绑过了没有」只能靠回忆", () => {
  pin();
  expect(screen.getByText("分镜起点")).toBeInTheDocument();
  expect(screen.getByText(/1/)).toBeInTheDocument();
});

it("没绑键的标记照样显示,只是没有那块键位", () => {
  pin({ shortcut: undefined });
  expect(screen.getByText("分镜起点")).toBeInTheDocument();
  expect(screen.queryByText("markerShortcutNone")).not.toBeInTheDocument();
});

it("点开旗子就能改名、改键、删掉 —— 配置留在这一处位置上", async () => {
  const onChange = vi.fn();
  const onDelete = vi.fn();
  pin({}, { onChange, onDelete });
  fireEvent.click(screen.getByTitle("markerConfigure"));
  fireEvent.change(await screen.findByLabelText("markerName"), { target: { value: "改过的名字" } });
  expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ name: "改过的名字" }));
  fireEvent.click(screen.getByRole("button", { name: /markerDelete/ }));
  expect(onDelete).toHaveBeenCalledWith("m1");
});

it("outside marker mode the pin cannot open or keep its editor focused", () => {
  const data = { marker, markers: [marker], onChange: vi.fn(), onDelete: vi.fn(), editable: true };
  const props = { data, selected: false } as unknown as React.ComponentProps<typeof MarkerPin>;
  const { rerender } = render(<MarkerPin {...props} />, { wrapper: MarkerEditors });
  fireEvent.click(screen.getByTitle("markerConfigure"));
  expect(screen.getByLabelText("markerName")).toBeInTheDocument();
  rerender(<MarkerPin {...props} data={{ ...data, editable: false }} />);
  expect(screen.queryByLabelText("markerName")).not.toBeInTheDocument();
  expect(screen.getByTitle("markerConfigure")).toHaveAttribute("tabindex", "-1");
  fireEvent.click(screen.getByTitle("markerConfigure"));
  expect(screen.queryByLabelText("markerName")).not.toBeInTheDocument();
});

function Pins({ enabled = true, second = true }: { enabled?: boolean; second?: boolean }) {
  const markers = [marker, { ...marker, id: "m2", name: "分镜终点" }];
  return <MarkerEditorProvider enabled={enabled}>
    {markers.slice(0, second ? 2 : 1).map(one => <MarkerPin key={one.id} {...({
      data: { editable: true, marker: one, markers, onChange: vi.fn(), onDelete: vi.fn() },
      selected: true,
    } as unknown as React.ComponentProps<typeof MarkerPin>)} />)}
  </MarkerEditorProvider>;
}

it("opening another selected marker replaces the editor and keeps the new editor interactive", async () => {
  const user = userEvent.setup();
  render(<Pins />);
  await user.click(screen.getByRole("button", { name: /分镜起点/ }));
  expect(screen.getByLabelText("markerName")).toHaveValue("分镜起点");
  await user.click(screen.getByRole("button", { name: /分镜终点/ }));
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
  expect(screen.getByLabelText("markerName")).toHaveValue("分镜终点");
  await waitFor(() => expect(screen.getByRole("dialog").contains(document.activeElement)).toBe(true));
  await user.click(screen.getByRole("button", { name: "close" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /分镜起点/ }));
  expect(screen.getByLabelText("markerName")).toHaveValue("分镜起点");
});

it("hiding markers or removing the active marker clears its editor without reopening it later", () => {
  const { rerender } = render(<Pins />);
  fireEvent.click(screen.getByRole("button", { name: /分镜终点/ }));
  rerender(<Pins enabled={false} />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  rerender(<Pins />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /分镜终点/ }));
  rerender(<Pins second={false} />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  rerender(<Pins />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
