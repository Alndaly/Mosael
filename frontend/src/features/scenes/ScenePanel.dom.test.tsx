/** @vitest-environment jsdom */
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { ScenePanel } from "./ScenePanel";
afterEach(cleanup);
it("collapses the whole section and preserves its field state when reopened", () => {
  render(<ScenePanel id="test" title="调整物体"><input aria-label="物体名称" defaultValue="方块" /></ScenePanel>);
  const toggle = screen.getByRole("button", { name: "调整物体" });
  const input = screen.getByRole("textbox");
  fireEvent.change(input, { target: { value: "展台" } });
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(input).not.toBeVisible();
  fireEvent.click(toggle);
  expect(input).toBeVisible();
  expect(input).toHaveValue("展台");
});
