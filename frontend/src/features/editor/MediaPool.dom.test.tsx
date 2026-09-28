/** @vitest-environment jsdom */
/**
 * 剪辑页左侧的素材面板:
 * - 头上的数说清楚是什么(「N 个素材」,筛了就是「剩几个 / 一共几个」),不是一个光秃秃的数字;
 * - 标签筛选和素材库是同一个组件:能同时勾几个、「同时 / 任一」、一排可去掉的标签、记住;
 * - 每一行带着素材的标签,挤不下的收成「+N」;
 * - 人声分离 / 降噪处理整份素材、产出进素材库,所以在素材的右键菜单里(有声音才给),和素材库同一个实现。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { renameAsset, separateAssetAudio, type Asset } from "@/api/client";
import { MediaPool } from "./MediaPool";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) =>
    ({ mediaPoolCount: "{count} assets", mediaPoolCountFiltered: "{shown}/{total} assets", mediaRemoveTag: "remove {tag}" })[key] ?? key,
}));
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: vi.fn() }) }));
vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  renameAsset: vi.fn(async () => Promise.reject(new Error("name taken"))),
  separateAssetAudio: vi.fn(async () => ({ id: "job-1" })),
  listDenoiseEngines: vi.fn(async () => []),
}));

const asset = (id: string, kind: Asset["kind"], tags: string[]) =>
  ({ id, name: id, workspace_id: "ws", project_id: "p", original_filename: id, file_key: id, kind, source: "imported", tags, media_info: {}, proxy_expected: false }) as Asset;

const ASSETS = [
  asset("beach", "video", ["sea", "dusk", "b-roll"]),
  asset("talk", "video", ["interview"]),
  asset("pier", "image", ["sea"]),
  asset("plain", "audio", []),
];

function renderPool(assets: Asset[] = ASSETS) {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <MediaPool assets={assets} uploading={false} onImportFiles={vi.fn()} onRecord={vi.fn()} onAddToTimeline={vi.fn()} />
    </QueryClientProvider>,
  );
}

const rowNames = () => [...document.querySelectorAll("[data-pool-item] strong")].map((one) => one.textContent);
const count = () => document.querySelector("[data-pool-count]")?.textContent;
const tagOption = (dialog: HTMLElement, tag: string) => within(dialog).getByRole("button", { name: new RegExp(`^${tag}`) });

beforeEach(() => localStorage.clear());

it("头上写「N 个素材」;筛了之后写剩几个 / 一共几个", () => {
  renderPool();
  expect(count()).toBe("4 assets");
  fireEvent.click(screen.getByRole("button", { name: "kindVideo" }));
  expect(count()).toBe("2/4 assets");
  expect(rowNames()).toEqual(["beach", "talk"]);
});

it("每一行带着素材的标签:露前两个,其余收成 +N;没标签的行不画", () => {
  renderPool();
  const beach = document.querySelector("[data-pool-item='beach']")!;
  const chips = beach.querySelector("[data-asset-tags]")!;
  expect([...chips.children].map((one) => one.textContent)).toEqual(["sea", "dusk", "+1"]);
  expect(chips.lastElementChild).toHaveAttribute("title", "b-roll");
  expect(document.querySelector("[data-pool-item='plain'] [data-asset-tags]")).toBeNull();
});

it("标签可以同时勾几个,「同时 / 任一」切换结果;下面一排能一个个去掉、一键清空", async () => {
  renderPool();
  fireEvent.click(screen.getByRole("button", { name: "filterByTag" }));
  const dialog = await screen.findByRole("dialog");
  // 标签后面标着挂了几条素材。
  expect(tagOption(dialog, "sea")).toHaveTextContent("sea2");

  fireEvent.click(tagOption(dialog, "sea"));
  expect(rowNames()).toEqual(["beach", "pier"]);
  fireEvent.click(tagOption(dialog, "interview"));
  // 默认「同时带有」:没有哪条既是 sea 又是 interview。
  expect(rowNames()).toEqual([]);
  fireEvent.click(within(dialog).getByRole("radio", { name: "mediaTagMatchAny" }));
  expect(rowNames()).toEqual(["beach", "talk", "pier"]);
  expect(screen.getByRole("button", { name: "filterByTag" }).querySelector("[data-tag-filter-count]")).toHaveTextContent("2");

  const chips = screen.getByRole("group", { name: "mediaActiveTags" });
  expect(chips).toHaveTextContent("mediaTagMatchAny");
  fireEvent.click(within(chips).getByRole("button", { name: "remove sea" }));
  expect(rowNames()).toEqual(["talk"]);

  fireEvent.click(within(screen.getByRole("group", { name: "mediaActiveTags" })).getByRole("button", { name: "mediaClearTag" }));
  expect(rowNames()).toEqual(["beach", "talk", "pier", "plain"]);
  expect(screen.queryByRole("group", { name: "mediaActiveTags" })).not.toBeInTheDocument();
});

it("类型、标签和「同时 / 任一」都记住:面板卸掉再装上还是那样", async () => {
  const first = renderPool();
  fireEvent.click(screen.getByRole("button", { name: "kindVideo" }));
  fireEvent.click(screen.getByRole("button", { name: "filterByTag" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(tagOption(dialog, "sea"));
  fireEvent.click(tagOption(dialog, "interview"));
  fireEvent.click(within(dialog).getByRole("radio", { name: "mediaTagMatchAny" }));
  first.unmount();

  renderPool();
  expect(screen.getByRole("button", { name: "kindVideo" })).toHaveAttribute("aria-pressed", "true");
  expect(rowNames()).toEqual(["beach", "talk"]);
  expect(within(screen.getByRole("group", { name: "mediaActiveTags" })).getAllByRole("button").map((one) => one.getAttribute("aria-label"))).toEqual(["remove sea", "remove interview", "mediaClearTag"]);
});

it("记着的标签已经没有素材带着了,就当没勾 —— 面板不会空得莫名其妙", () => {
  localStorage.setItem("mosael:selected-set:editor-pool-tags", JSON.stringify(["gone"]));
  renderPool();
  expect(rowNames()).toEqual(["beach", "talk", "pier", "plain"]);
  expect(count()).toBe("4 assets");
  expect(screen.queryByRole("group", { name: "mediaActiveTags" })).not.toBeInTheDocument();
});

// 重命名失败时对话框要收起(失败原因由全局兜底报):此前停在那儿、确认键又能点,连点就是连发请求。
it("重命名失败:对话框收起,不留一个能反复点的确认键", async () => {
  const user = userEvent.setup();
  renderPool();
  fireEvent.contextMenu(document.querySelector("[data-pool-item='beach']")!, { button: 2, clientX: 10, clientY: 10 });
  await user.click(await screen.findByRole("menuitem", { name: "rename" }));
  const dialog = await screen.findByRole("dialog", { name: "renameAsset" });
  const input = within(dialog).getByRole("textbox");
  await user.clear(input);
  await user.type(input, "sunset");
  await user.click(within(dialog).getByRole("button", { name: "confirm" }));
  await waitFor(() => expect(renameAsset).toHaveBeenCalledWith("beach", "sunset"));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "renameAsset" })).toBeNull());
  expect(renameAsset).toHaveBeenCalledTimes(1);
});

const openRowMenu = (id: string) =>
  fireEvent.contextMenu(document.querySelector(`[data-pool-item='${id}']`)!, { button: 2, clientX: 10, clientY: 10 });
const menuItems = () => screen.getAllByRole("menuitem").map((item) => item.textContent?.trim());

it("有声音的素材:右键能分离人声与背景音(排任务)、能降噪(开对话框);图片没有这两项", async () => {
  const user = userEvent.setup();
  renderPool();

  openRowMenu("pier");
  await screen.findByRole("menuitem", { name: "rename" });
  expect(menuItems()).not.toContain("separateAudio");
  expect(menuItems()).not.toContain("denoiseAction");
  await user.keyboard("{Escape}");

  openRowMenu("beach");
  await user.click(await screen.findByRole("menuitem", { name: "separateAudio" }));
  await waitFor(() => expect(separateAssetAudio).toHaveBeenCalledWith("beach"));

  openRowMenu("plain");
  await user.click(await screen.findByRole("menuitem", { name: "denoiseAction" }));
  expect(await screen.findByRole("dialog", { name: "denoiseTitle" })).toBeInTheDocument();
});
