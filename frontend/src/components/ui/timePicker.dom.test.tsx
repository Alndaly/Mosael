/** @vitest-environment jsdom */
/**
 * 定时任务「每天几点」的选择器。钉住三件事:值的格式(HH:MM,补零)、选小时不收起而选分钟收起、
 * 方向键在当前列里挪格(会绕回)。
 */
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => ({ timePickerHour: "时", timePickerMinute: "分" })[key] ?? key }));

const { TimePicker } = await import("./time-picker");

afterEach(cleanup);

function Harness({ initial, onChange }: { initial: string; onChange: (v: string) => void }) {
  const [value, setValue] = React.useState(initial);
  return <TimePicker ariaLabel="执行时间" value={value} onChange={(v) => { setValue(v); onChange(v); }} />;
}

it("选小时不收起、选分钟收起,值补零成 HH:MM", () => {
  const onChange = vi.fn();
  render(<Harness initial="09:00" onChange={onChange} />);
  const trigger = screen.getByRole("button", { name: "执行时间" });
  expect(trigger.textContent).toContain("09:00");
  fireEvent.click(trigger);

  const hours = screen.getByRole("listbox", { name: "时" });
  expect(hours.querySelector("[aria-selected=true]")?.textContent).toBe("09");
  fireEvent.click(screen.getAllByRole("option", { name: "14" })[0]);
  expect(onChange).toHaveBeenLastCalledWith("14:00");
  expect(screen.getByRole("listbox", { name: "分" })).toBeTruthy(); // 还开着,接着选分钟

  fireEvent.click(screen.getAllByRole("option", { name: "05" }).at(-1)!);
  expect(onChange).toHaveBeenLastCalledWith("14:05");
  expect(screen.queryByRole("listbox", { name: "分" })).toBeNull();
  expect(trigger.textContent).toContain("14:05");
});

it("方向键在当前列挪一格,到头绕回", () => {
  const onChange = vi.fn();
  render(<Harness initial="23:59" onChange={onChange} />);
  fireEvent.click(screen.getByRole("button", { name: "执行时间" }));
  fireEvent.keyDown(screen.getByRole("listbox", { name: "时" }), { key: "ArrowDown" });
  expect(onChange).toHaveBeenLastCalledWith("00:59");
  fireEvent.keyDown(screen.getByRole("listbox", { name: "分" }), { key: "ArrowDown" });
  expect(onChange).toHaveBeenLastCalledWith("00:00");
  expect(screen.getByRole("listbox", { name: "分" })).toBeTruthy(); // 挪格不收起
});
