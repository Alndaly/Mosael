/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

/**
 * 产出素材怎么摆。
 *
 * 用户看到的那一版:「分离人声与背景音」跑完,节点上两个一模一样的音频条并排挤在两百像素里,
 * 哪条是人声只能点开听 —— 而右边接点上明明写着「人声」「背景音」。检查器里更糟:那份预览的
 * 尺寸表是照着视频写的,音频落进 `h-[78px] bg-black`,成了黑方块里嵌一条播放器。
 *
 * 两件事在这里钉住:**名字跟着素材走**,**尺寸按素材种类给**。
 */

vi.mock("@/api/client", () => ({
  api: vi.fn(async (path: string) => {
    const id = path.split("/").pop() as string;
    return { id, name: `素材 ${id}`, kind: id.startsWith("img") ? "image" : "audio" };
  }),
}));
vi.mock("@/components/app/asset-preview", () => ({
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

  it("音频不套进按画面写的方框里", async () => {
    await mount([VOICE], "panel");
    const cls = screen.getByTestId("preview").getAttribute("data-cls") ?? "";
    expect(cls, "音频条自带高度,固定高度 + 黑底是给画面用的").not.toMatch(/h-\[\d+px\]|bg-black|object-cover/);
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
