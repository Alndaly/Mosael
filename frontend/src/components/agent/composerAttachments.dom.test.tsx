/** @vitest-environment jsdom */
import React from "react";
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 两个智能体输入框(对话页 tab / 工作流侧栏)共用这一套附件逻辑。
 * 以前它们各写一份而且不一样 —— 工作流那边能内联文本文件、对话页不能;两边都不认粘贴。
 */

const importAsset = vi.fn();
vi.mock("@/api/client", () => ({ importAsset: (...args: unknown[]) => importAsset(...args) }));
// 文案里带上 {name} 占位符:被拒绝的文件必须报出是哪一个,只说"读不了"等于没说。
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => `${key}:{name}` }));
const toastError = vi.fn();
vi.mock("sonner", () => ({ toast: { error: (...args: unknown[]) => toastError(...args) } }));

import { AttachmentChips, textAttachmentBlock, useComposerAttachments } from "./composerAttachments";

type Handle = ReturnType<typeof useComposerAttachments>;

function Harness({ onReady }: { onReady: (handle: Handle) => void }) {
  const attach = useComposerAttachments("ws-1");
  React.useEffect(() => {
    onReady(attach);
  });
  return <AttachmentChips attachments={attach} />;
}

function mount() {
  let handle!: Handle;
  render(<Harness onReady={(h) => (handle = h)} />);
  return () => handle;
}

beforeEach(() => {
  importAsset.mockReset();
  toastError.mockReset();
});

describe("附件分流", () => {
  it("图片进素材库,文本文件内联", async () => {
    importAsset.mockResolvedValue({ id: "a1", name: "shot.png", kind: "image" });
    const get = mount();

    await act(async () => {
      await get().accept([
        new File(["binary"], "shot.png", { type: "image/png" }),
        new File(["第一幕"], "script.txt", { type: "text/plain" }),
      ]);
    });

    expect(importAsset).toHaveBeenCalledTimes(1);
    expect(get().media.map((a) => a.id)).toEqual(["a1"]);
    expect(get().files).toEqual([{ name: "script.txt", content: "第一幕" }]);
    // 两类附件都在同一排小条里,不再是两套长得不一样的东西。
    expect(screen.getByTitle("shot.png")).toBeTruthy();
    expect(screen.getByTitle("script.txt")).toBeTruthy();
  });

  it("读不了的类型明确拒绝,而不是静默丢掉", async () => {
    const get = mount();
    await act(async () => {
      await get().accept([new File(["x"], "bundle.zip", { type: "application/zip" })]);
    });
    expect(get().isEmpty).toBe(true);
    expect(toastError).toHaveBeenCalledWith(expect.stringContaining("bundle.zip"));
  });

  it("没有 MIME 的文件按文本试读(从终端拖出来的常常没有)", async () => {
    const get = mount();
    await act(async () => {
      await get().accept([new File(["a,b"], "data.csv", { type: "" })]);
    });
    expect(get().files).toEqual([{ name: "data.csv", content: "a,b" }]);
  });

  it("超过上限的文本拒绝 —— 那么大该进知识库", async () => {
    const get = mount();
    const huge = new File(["x".repeat(200 * 1024 + 1)], "big.txt", { type: "text/plain" });
    await act(async () => {
      await get().accept([huge]);
    });
    expect(get().isEmpty).toBe(true);
    expect(toastError).toHaveBeenCalledWith(expect.stringContaining("big.txt"));
  });
});

describe("粘贴", () => {
  it("粘贴截图会上传,并给它一个名字", async () => {
    importAsset.mockResolvedValue({ id: "a2", name: "pasted.png", kind: "image" });
    const get = mount();
    // 截图粘贴进来的 File 名字是空串;不补名字的话素材库里会出现一排无名文件。
    const pasted = new File(["png"], "", { type: "image/png" });
    const preventDefault = vi.fn();

    await act(async () => {
      const handled = get().onPaste({
        clipboardData: { files: [pasted] },
        preventDefault,
      } as unknown as React.ClipboardEvent);
      expect(handled).toBe(true);
    });

    expect(preventDefault).toHaveBeenCalled();
    expect(importAsset).toHaveBeenCalledTimes(1);
    const sent = importAsset.mock.calls[0][0] as { file: File };
    expect(sent.file.name).not.toBe("");
    expect(sent.file.name).toMatch(/\.png$/);
  });

  it("剪贴板里没有文件时放行,普通粘贴文字不受影响", () => {
    const get = mount();
    const preventDefault = vi.fn();
    const handled = get().onPaste({
      clipboardData: { files: [] },
      preventDefault,
    } as unknown as React.ClipboardEvent);
    expect(handled).toBe(false);
    expect(preventDefault).not.toHaveBeenCalled();
  });
});

describe("发送时的拼装", () => {
  it("文本附件拼成围栏块 —— 两个输入框同一种拼法", () => {
    expect(textAttachmentBlock([{ name: "a.txt", content: "hi" }], "附件")).toBe(
      "[附件 a.txt]\n```\nhi\n```",
    );
  });
});
