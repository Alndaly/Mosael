/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";
//: 这里不测看大图(那是 image-preview 自己和各处接线测试的事),只给一个桩让组件挂得上。
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: vi.fn(), isImagePreviewOpen: false }) }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => ({ wfOutputImageCount: "{n} 张", wfOutputFileCount: "{n} 份" })[key] ?? key,
}));

/**
 * 产出素材怎么摆。
 *
 * 用户看到的那一版:「分离人声与背景音」跑完,节点上两个一模一样的音频条并排挤在两百像素里,
 * 哪条是人声只能点开听 —— 而右边接点上明明写着「人声」「背景音」。检查器里更糟:那份预览的
 * 尺寸表是照着视频写的,音频落进 `h-[78px] bg-black`,成了黑方块里嵌一条播放器。
 *
 * 两件事在这里钉住:**名字跟着素材走**,**尺寸按素材种类给**。
 */

vi.mock("@/api/transport", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/transport")>()),
  api: vi.fn(async (path: string) => {
    const id = path.split("/").pop() as string;
    return { id, name: `素材 ${id}`, kind: id.startsWith("img") ? "image" : "audio" };
  }),
}));
vi.mock("@/components/app/asset-preview", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/app/asset-preview")>()),
  AssetInlinePreview: ({ assetId, kind, className }: { assetId: string; kind: string; className?: string }) => (
    <div data-testid="preview" data-asset={assetId} data-kind={kind} data-cls={className ?? ""} />
  ),
}));

import { OutputAssets } from "@/features/workflows/OutputAssets";

const VOICE = { key: "vocals_asset_id", label: "人声", assetId: "a1" };
const MUSIC = { key: "background_asset_id", label: "背景音", assetId: "a2" };

async function mount(items: typeof VOICE[], density: "node" | "panel") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={qc}>
      <OutputAssets items={items} density={density} />
    </QueryClientProvider>,
  );
  await screen.findAllByTestId("preview");
  return view;
}

describe("产出素材", () => {
  it("两份摆在一起时各自带名字 —— 这正是此前分不清的那一刻", async () => {
    await mount([VOICE, MUSIC], "node");
    expect(screen.getByText("人声")).toBeTruthy();
    expect(screen.getByText("背景音")).toBeTruthy();
  });

  it("只有一份时不占那一行 —— 节点标题已经说了它是什么", async () => {
    await mount([VOICE], "node");
    expect(screen.queryByText("人声")).toBeNull();
  });

  it("检查器里一律报名字 —— 那儿每一行本来就是「名字 + 值」", async () => {
    await mount([VOICE], "panel");
    expect(screen.getByText("人声")).toBeTruthy();
  });

  it("音频不并排:并排之后每条只剩一半宽,进度条几乎点不中", async () => {
    const { container } = await mount([VOICE, MUSIC], "node");
    expect(container.firstElementChild?.className).not.toContain("grid-flow-col");
  });

  it("画面并排 —— 缩略图并排看得清", async () => {
    const { container } = await mount(
      [{ ...VOICE, assetId: "img1" }, { ...MUSIC, assetId: "img2" }],
      "node",
    );
    expect(container.firstElementChild?.className).toContain("grid-flow-col");
  });

  it("检查器里几个口各一张:两列往下排,不挤成一排细条", async () => {
    const { container } = await mount(
      [{ ...VOICE, assetId: "img1" }, { ...MUSIC, assetId: "img2" }, { key: "image_12", label: "图 · 另一张", assetId: "img3" }],
      "panel",
    );
    expect(screen.getAllByTestId("preview")).toHaveLength(3);
    expect(container.firstElementChild?.className).toContain("grid-cols-2");
  });

  it("音频不套进按画面写的方框里", async () => {
    await mount([VOICE], "panel");
    const cls = screen.getByTestId("preview").getAttribute("data-cls") ?? "";
    expect(cls, "音频条自带高度,固定高度 + 黑底是给画面用的").not.toMatch(/h-\[\d+px\]|bg-black|object-cover/);
  });

  it("一个口交了好几份(一次出两张的工作流):全摆出来,名字后面报几张 —— 此前只看得到一张", async () => {
    const batch = [
      { key: "image_9", label: "图 · 预览图像", assetId: "img1" },
      { key: "image_9", label: "图 · 预览图像", assetId: "img2" },
    ];
    const { container } = await mount(batch, "node");
    expect(screen.getAllByTestId("preview").map((one) => one.getAttribute("data-asset"))).toEqual(["img1", "img2"]);
    expect(screen.getByText("图 · 预览图像")).toBeTruthy();
    expect(container.querySelector("[data-output-count]")?.textContent).toBe("· 2 张");
    expect(container.querySelector("[data-output-group] .grid-cols-2"), "两张排成网格").toBeTruthy();
  });

  it("卡片上同一份素材只摆一次:「第一份产出」就是那个口的第一张", async () => {
    const items = [
      { key: "image_9", label: "图 · 预览图像", assetId: "img1" },
      { key: "image_9", label: "图 · 预览图像", assetId: "img2" },
      { key: "asset_id", label: "第一份产出", assetId: "img1" },
    ];
    await mount(items, "node");
    expect(screen.getAllByTestId("preview").map((one) => one.getAttribute("data-asset"))).toEqual(["img1", "img2"]);
    expect(screen.queryByText("第一份产出")).toBeNull();
  });

  it("检查器里一个口一行:那个口的两张和「第一份产出」各报各的", async () => {
    const items = [
      { key: "image_9", label: "图 · 预览图像", assetId: "img1" },
      { key: "image_9", label: "图 · 预览图像", assetId: "img2" },
      { key: "asset_id", label: "第一份产出", assetId: "img1" },
    ];
    const { container } = await mount(items, "panel");
    expect(screen.getAllByTestId("preview").map((one) => one.getAttribute("data-asset"))).toEqual(["img1", "img2", "img1"]);
    expect(screen.getByText("第一份产出")).toBeTruthy();
    expect([...container.querySelectorAll("[data-output-count]")].map((one) => one.textContent)).toEqual(["· 2 张"]);
  });

  it("一个口好多份:卡片上摆四格,最后一格写还有几张", async () => {
    const many = Array.from({ length: 7 }, (_, index) => ({ key: "image_9", label: "图", assetId: `img${index}` }));
    const { container } = await mount(many, "node");
    expect(screen.getAllByTestId("preview")).toHaveLength(4);
    expect(container.querySelector("[data-output-more]")?.textContent).toBe("+3");
    expect(container.querySelector("[data-output-count]")?.textContent).toBe("· 7 张");
  });

  it("素材被删掉就什么都不画 —— 那是正常路径,不是错误", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={qc}>
        <OutputAssets items={[]} density="node" />
      </QueryClientProvider>,
    );
    expect(container.firstChild).toBeNull();
  });
});
