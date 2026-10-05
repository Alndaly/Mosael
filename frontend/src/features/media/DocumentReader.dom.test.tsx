/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

/**
 * 素材详情里的文档阅读器(ADR 0031):读最新成功的那份解析,写明是谁解析的、有什么提醒;一段一段排,
 * 页面图挂在段首;Markdown 里的插图换成带令牌的文件地址。失败的说原因。
 */

const docs = vi.hoisted(() => ({
  listExtractions: vi.fn(),
  extractionSections: vi.fn(),
  parseDocument: vi.fn(),
  extractionFileUrl: (asset: string, extraction: string, path: string) => `/f/${asset}/${extraction}/${path}?token=t`,
}));
vi.mock("@/api/domains/documents", () => docs);
const cancelJob = vi.hoisted(() => vi.fn(async () => ({})));
vi.mock("@/api/domains/jobs", () => ({ cancelJob }));
vi.mock("@/api/domains/capabilities", () => ({ listCapabilityChoices: vi.fn(async () => [{ capability: "document_parse", options: [
  { id: "builtin:local", name: "本地解析", builtin: true, missing: [] }] }]) }));
vi.mock("@/features/media/useSaveDocumentAsNote", () => ({ useSaveDocumentAsNote: () => ({ mutate: vi.fn(), isPending: false }) }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => ({ docSectionLabel: "第 {index} {unit}", docUnitPage: "页" } as Record<string, string>)[key] ?? key,
}));
const openImagePreview = vi.hoisted(() => vi.fn());
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview }) }));

import { DocumentReader, withFileUrls } from "./DocumentReader";

const done = { id: "x1", asset_id: "a", parser: "builtin:local", parser_name: "本地解析", status: "succeeded", error: "",
               unit: "slide", sections: 1, chars: 10, outline: [], page_images: ["pages/001.png"], notes: ["docNote_noPageImages", "unknownNote"],
               created_at: "2026-09-28T00:00:00" };

function mount() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <DocumentReader assetId="a" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  docs.listExtractions.mockReset();
  docs.extractionSections.mockReset();
  openImagePreview.mockReset();
});

it("左边按段排全文,右边原版每一页;插图地址换成带令牌的;提醒只显示认得的", async () => {
  docs.listExtractions.mockResolvedValue([done]);
  docs.extractionSections.mockResolvedValue({ total: 1, unit: "slide", sections: [
    { index: 1, title: "季度汇报", image: "pages/001.png", markdown: "# 季度汇报\n\n![](images/001-001.png)" }] });
  mount();
  await waitFor(() => expect(document.querySelector("[data-document-section='1']")).not.toBeNull());
  expect(document.querySelector("[data-document-parsed-by]")?.textContent).toContain("docParsedBy");
  expect(document.querySelector("[data-document-pages] [data-document-page='pages/001.png']")).not.toBeNull();
  const images = [...document.querySelectorAll("img")].map((one) => one.getAttribute("src"));
  expect(images).toContain("/f/a/x1/pages/001.png?token=t");
  expect(images).toContain("/f/a/x1/images/001-001.png?token=t");
  const notes = document.querySelector("[data-document-notes]")?.textContent ?? "";
  expect(notes).toContain("docNote_noPageImages");
  expect(notes).not.toContain("unknownNote");
});

it("原版那一栏点开一页,灯箱里左右翻的是这份文档的每一页,标题是「第 n 页」", async () => {
  docs.listExtractions.mockResolvedValue([{ ...done, page_images: ["pages/001.png", "pages/002.png"] }]);
  docs.extractionSections.mockResolvedValue({ total: 0, unit: "slide", sections: [] });
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "第 2 页" }));
  expect(openImagePreview).toHaveBeenCalledWith({
    src: "/f/a/x1/pages/002.png?token=t",
    title: "第 2 页",
    gallery: [
      { src: "/f/a/x1/pages/001.png?token=t", title: "第 1 页" },
      { src: "/f/a/x1/pages/002.png?token=t", title: "第 2 页" },
    ],
  });
});

it("解析失败说原因", async () => {
  docs.listExtractions.mockResolvedValue([{ ...done, id: "x2", status: "failed", error: "文件坏了" }]);
  mount();
  await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("文件坏了"));
});

it("只改 Markdown 里相对解析目录的地址,外链不动", () => {
  expect(withFileUrls("![](images/a.png) ![](https://x.com/b.png)", "a", "x")).toBe("![](/f/a/x/images/a.png?token=t) ![](https://x.com/b.png)");
});

it("解析中能停:停的是那一次解析任务;停下之后说已停止,可以重新解析", async () => {
  //: 一份上百 MB 的 PDF 开始解析就只能等它跑完(用户截图)。
  docs.listExtractions.mockResolvedValue([{ ...done, id: "x2", status: "running", job_id: "job-9", sections: 0 }]);
  const { unmount } = mount();
  await waitFor(() => expect(document.querySelector("[data-document-stop]")).not.toBeNull());
  fireEvent.click(document.querySelector<HTMLButtonElement>("[data-document-stop]")!);
  await waitFor(() => expect(cancelJob).toHaveBeenCalledWith("job-9"));
  unmount();

  docs.listExtractions.mockResolvedValue([{ ...done, id: "x2", status: "cancelled", job_id: "job-9", sections: 0 }]);
  mount();
  await waitFor(() => expect(document.querySelector("[data-document-stopped]")?.textContent).toContain("docParseStopped"));
  expect(document.querySelector("[data-document-stop]")).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("表格按全高排,不套一个 300px 的小滚动框(几百行的表只看得见前几行)", async () => {
  docs.listExtractions.mockResolvedValue([{ ...done, id: "x3", unit: "sheet", page_images: [], notes: [] }]);
  const rows = Array.from({ length: 40 }, (_, i) => `| ${i + 1} | 学生${i + 1} |`).join("\n");
  docs.extractionSections.mockResolvedValue({ total: 1, unit: "sheet", sections: [
    { index: 1, title: "Sheet1", image: null, markdown: `| 序号 | 姓名 |\n| --- | --- |\n${rows}` }] });
  mount();
  await waitFor(() => expect(document.querySelector("[data-document-text] table")).not.toBeNull());
  const box = document.querySelector("[data-document-text] table")!.parentElement!;
  expect(box.style.maxHeight).toBe("");
});
