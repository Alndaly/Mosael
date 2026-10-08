/** @vitest-environment jsdom */
/**
 * 3D 场景页的「打开三间展厅示例」。
 *
 * 此前空状态里一颗「体验示例场景」、页头一颗「打开三间展厅示例」,同屏两颗做同一件事;而说「打开」的那一颗
 * 每点一次复制一份,点四次就有四份同名的场景。现在一种叫法、同一时刻只有一颗;这个工作区已经有一份示例
 * (content.template 认得出,改过名也算)就打开那份。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { SceneSummary } from "@/api/domains/scenes";

vi.mock("@/app/preferences", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  usePreferences: () => ({ locale: "zh-CN", t: (key: string) => key }),
  useI18n: () => (key: string) => key,
}));
vi.mock("./SceneBlenderPull", () => ({ SceneBlenderPull: () => null }));
let scenes: SceneSummary[] = [];
const api = vi.hoisted(() => ({
  createScene: vi.fn(async (_ws: string, name: string, content: unknown) => ({ id: "fresh", workspace_id: "w1", name, content, revision: 1 })),
}));
vi.mock("@/api/domains/scenes", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  listScenes: vi.fn(async () => scenes),
  createScene: api.createScene,
}));

import { SceneStudio } from "./SceneStudio";
import { readHint } from "@/test/hint";

const summary = (id: string, name: string, template: SceneSummary["template"] = null): SceneSummary =>
  ({ id, name, revision: 1, updated_at: "2026-10-08T00:00:00", object_count: 2, shot_count: 1, template }) as SceneSummary;

beforeEach(() => {
  location.hash = "#/scenes";
  api.createScene.mockClear();
});
afterEach(() => {
  cleanup();
  location.hash = "";
});

function open(role = "editor") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SceneStudio workspace={{ id: "w1", role } as never} />
    </QueryClientProvider>,
  );
}

it("空着的时候只有一颗示例按钮(在空状态里),点了建一份带示例标记的场景", async () => {
  scenes = [];
  open();
  await screen.findByText("sceneEmptyTitle");
  const buttons = screen.getAllByRole("button", { name: "scenesOpenSample" });
  expect(buttons).toHaveLength(1);
  //: 一屏只有一个实心主动作:「新建场景」也只有一颗,在空状态里、次一级(描边),页头那颗收起来。
  const fresh = screen.getAllByRole("button", { name: "scenesNew" });
  expect(fresh).toHaveLength(1);
  expect(fresh[0].closest(".empty-state")).not.toBeNull();
  expect(fresh[0].className).not.toMatch(/\bbg-action\b/);
  expect(buttons[0].className).toMatch(/\bbg-action\b/);
  fireEvent.click(buttons[0]);
  await waitFor(() => expect(api.createScene).toHaveBeenCalledTimes(1));
  expect(api.createScene.mock.calls[0][2]).toMatchObject({ template: "three_halls" });
  await waitFor(() => expect(location.hash).toBe("#/scenes?scene=fresh"));
});

it("已经有一份示例(改过名也算):打开那一份,不再复制", async () => {
  scenes = [summary("mine", "空场景"), summary("hall", "我的展厅", "three_halls")];
  open();
  fireEvent.click(await screen.findByRole("button", { name: "scenesOpenSample" }));
  await waitFor(() => expect(location.hash).toBe("#/scenes?scene=hall"));
  expect(api.createScene).not.toHaveBeenCalled();
});

it("有场景但没有示例:页头那颗建一份", async () => {
  scenes = [summary("mine", "空场景")];
  open();
  fireEvent.click(await screen.findByRole("button", { name: "scenesOpenSample" }));
  await waitFor(() => expect(api.createScene).toHaveBeenCalledTimes(1));
});

//: 只读成员(体检 UM-20 / D62):会建一份场景的按钮是灰的、说为什么;已经有示例时那颗只是打开它,照常能点。
it("只读成员:建场景的按钮是灰的并说为什么;已有示例时「打开示例」照常打开那一份", async () => {
  scenes = [];
  open("viewer");
  await screen.findByText("sceneEmptyTitle");
  const sample = screen.getByRole("button", { name: "scenesOpenSample" });
  expect(sample).toBeDisabled();
  expect(await readHint(sample)).toBe("roleReadOnlyHint");
  expect(screen.getByRole("button", { name: "scenesNew" })).toBeDisabled();
  cleanup();

  scenes = [summary("hall", "我的展厅", "three_halls")];
  open("viewer");
  const openHall = await screen.findByRole("button", { name: "scenesOpenSample" });
  expect(openHall).toBeEnabled();
  expect(screen.getByRole("button", { name: "scenesNew" })).toBeDisabled();
  fireEvent.click(openHall);
  await waitFor(() => expect(location.hash).toBe("#/scenes?scene=hall"));
  expect(api.createScene).not.toHaveBeenCalled();
});
