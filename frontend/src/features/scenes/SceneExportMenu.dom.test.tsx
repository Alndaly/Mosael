/** @vitest-environment jsdom */
/**
 * 「导出文件」只导文件。此前它把「生成素材」弹层里的五项又抄了一遍(三条 → 生成、两条 → 素材库),
 * 同一件事两个入口,而「导出文件」这个名字装不下它们。
 */
import React from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { SceneExportMenu } from "./SceneExportMenu";

afterEach(cleanup);

it("只有 GLB 和 JSON 两项,各自交给调用方", () => {
  const onExportGlb = vi.fn();
  const onExportJson = vi.fn();
  render(<SceneExportMenu disabled={false} onExportGlb={onExportGlb} onExportJson={onExportJson} />);
  fireEvent.click(screen.getByRole("button", { name: "sceneExportFiles" }));
  const menu = screen.getByRole("menu", { name: "sceneExportFiles" });
  expect(within(menu).getAllByRole("menuitem").map((item) => item.textContent)).toEqual(["sceneExportGlb", "sceneExportJson"]);
  // 点完一项菜单就收起;再点开选另一项。
  fireEvent.click(within(menu).getByRole("menuitem", { name: "sceneExportGlb" }));
  expect(screen.queryByRole("menu")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "sceneExportFiles" }));
  fireEvent.click(within(screen.getByRole("menu")).getByRole("menuitem", { name: "sceneExportJson" }));
  expect(onExportGlb).toHaveBeenCalledTimes(1);
  expect(onExportJson).toHaveBeenCalledTimes(1);
});

it("在忙的时候点不开", () => {
  render(<SceneExportMenu disabled onExportGlb={vi.fn()} onExportJson={vi.fn()} />);
  expect((screen.getByRole("button", { name: "sceneExportFiles" }) as HTMLButtonElement).disabled).toBe(true);
});
