/** @vitest-environment jsdom */
import React from "react";
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 两个智能体输入框(对话页 tab / 工作流侧栏)共用这一套附件逻辑。
 * 以前它们各写一份而且不一样 —— 工作流那边能内联文本文件、对话页不能;两边都不认粘贴。
 */

const importAsset = vi.fn();
vi.mock("@/api/client", () => ({
  importAsset: (...args: unknown[]) => importAsset(...args),
  assetFileUrl: (id: string) => `/file/${id}`,
  assetThumbnailUrl: (id: string) => `/thumb/${id}`,
}));
const openImagePreview = vi.fn();
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview }) }));
// 文案里带上 {name} 占位符:被拒绝的文件必须报出是哪一个,只说"读不了"等于没说。
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => `${key}:{name}|{reason}` }));
const toastError = vi.fn();
vi.mock("sonner", () => ({ toast: { error: (...args: unknown[]) => toastError(...args) } }));

import { ComposerChips } from "./ComposerChips";
import { textAttachmentBlock, useComposerAttachments } from "./composerAttachments";

type Handle = ReturnType<typeof useComposerAttachments>;

function Harness({ onReady }: { onReady: (handle: Handle) => void }) {
  const attach = useComposerAttachments("ws-1");
  React.useEffect(() => {
    onReady(attach);
  });
  return <ComposerChips chips={attach.chips} uploading={attach.uploading} />;
}

function mount() {
  let handle!: Handle;
  render(<Harness onReady={(h) => (handle = h)} />);
  return () => handle;
}

beforeEach(() => {
  importAsset.mockReset();
  toastError.mockReset();
  openImagePreview.mockReset();
});

describe("附件分流", () => {
  it("图片进素材库,文本文件内联", async () => {
    importAsset.mockResolvedValue({ id: "a1", name: "shot.png", kind: "image" });
    const get = mount();

    await act(async () => {
      await get().accept([
        new File(["binary"], "shot.png", { type: "image/png" }),
        new File(["第一幕"], "scene.srt", { type: "text/plain" }),
      ]);
    });

    expect(importAsset).toHaveBeenCalledTimes(1);
    expect(get().media.map((a) => a.id)).toEqual(["a1"]);
    expect(get().files).toEqual([{ name: "scene.srt", content: "第一幕" }]);
    // 两类附件都在同一排小条里,不再是两套长得不一样的东西。
    expect(screen.getByTitle("shot.png")).toBeTruthy();
    expect(screen.getByTitle("scene.srt")).toBeTruthy();
    // 图片带缩略图,点开走全局灯箱;文本附件点开看到的是它真正带上去的那段字。
    expect(screen.getByTitle("shot.png").querySelector("img")).toHaveAttribute("src", "/thumb/a1");
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
      await get().accept([new File(["print(1)"], "run.py", { type: "" })]);
    });
    expect(get().files).toEqual([{ name: "run.py", content: "print(1)" }]);
  });

  it("超过上限的文本(素材库不当文档的那种)拒绝", async () => {
    const get = mount();
    const huge = new File(["x".repeat(200 * 1024 + 1)], "big.json", { type: "application/json" });
    await act(async () => {
      await get().accept([huge]);
    });
    expect(get().isEmpty).toBe(true);
    expect(importAsset).not.toHaveBeenCalled();
    expect(toastError).toHaveBeenCalledWith(expect.stringContaining("big.json"));
  });

  it("超过一条消息能带的文本也拒:内联上限和消息上限对得上", async () => {
    //: 用户截图:附件条上好好的,一发送「String should have at most 8000 characters」。
    const get = mount();
    await act(async () => {
      await get().accept([new File(["x".repeat(3001)], "long.json", { type: "application/json" })]);
    });
    expect(get().files).toEqual([]);
    expect(toastError).toHaveBeenCalledWith(expect.stringContaining("long.json"));
  });

  it("短的 Markdown 也进素材库当文档,不内联进消息", async () => {
    importAsset.mockResolvedValue({ id: "d0", name: "提纲.md", kind: "document" });
    const get = mount();
    await act(async () => {
      await get().accept([new File(["# 提纲"], "提纲.md", { type: "text/markdown" })]);
    });
    expect(get().media.map((one) => one.id)).toEqual(["d0"]);
    expect(get().files).toEqual([]);
  });

  it("超过上限的 Markdown 进素材库当文档 —— 智能体按段读,不再说「太大了」", async () => {
    //: 用户截图:「赛里木湖纪录片全案_整理版(1).md」附不上。
    importAsset.mockResolvedValue({ id: "d1", name: "全案.md", kind: "document" });
    const get = mount();
    const huge = new File(["# 全案\n" + "字".repeat(80 * 1024)], "全案.md", { type: "text/markdown" });
    await act(async () => {
      await get().accept([huge]);
    });
    expect(importAsset).toHaveBeenCalledTimes(1);
    expect(get().media.map((one) => one.id)).toEqual(["d1"]);
    expect(get().files).toEqual([]);
    expect(toastError).not.toHaveBeenCalled();
  });

  it("这里读不出来的 Markdown 交给素材库再试一次;还不行,说清是哪一个、为什么", async () => {
    const broken = new File(["# x"], "占位.md", { type: "text/markdown" });
    broken.text = () => Promise.reject(new DOMException("could not be read", "NotReadableError"));
    importAsset.mockResolvedValueOnce({ id: "d2", name: "占位.md", kind: "document" });
    const get = mount();
    await act(async () => {
      await get().accept([broken]);
    });
    expect(get().media.map((one) => one.id)).toEqual(["d2"]);
    expect(toastError).not.toHaveBeenCalled();

    importAsset.mockRejectedValueOnce(new Error("上传被拒:磁盘满了"));
    await act(async () => {
      await get().accept([broken]);
    });
    expect(toastError).toHaveBeenCalledWith(expect.stringMatching(/占位\.md.*磁盘满了/));
  });

  it("文件本身读不出来时,上传失败不说成「后端连不上」", async () => {
    //: 用户截图:「……整理版(1).md」没附上:http://127.0.0.1:8800 连不上 —— 后端好好的,是系统不让读这个文件
    //: (从聊天软件里直接拖出来的,在别的应用的沙盒里)。
    const locked = new File(["# x".repeat(100)], "锁着.md", { type: "text/markdown" });
    const refuse = () => Promise.reject(new DOMException("could not be read", "NotReadableError"));
    locked.text = refuse;
    locked.slice = () => Object.assign(new Blob(), { arrayBuffer: refuse });
    importAsset.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const get = mount();
    await act(async () => {
      await get().accept([locked]);
    });
    expect(toastError).toHaveBeenCalledWith(expect.stringMatching(/锁着\.md.*composerFileNotReadable/));
  });

  it("读不出来的不是文档类文本:原因说人话,不是一句光秃秃的「读不出来」", async () => {
    const broken = new File(["{}"], "cfg.json", { type: "application/json" });
    broken.text = () => Promise.reject(new DOMException("could not be read", "NotReadableError"));
    const get = mount();
    await act(async () => {
      await get().accept([broken]);
    });
    expect(importAsset).not.toHaveBeenCalled();
    expect(toastError).toHaveBeenCalledWith(expect.stringMatching(/cfg\.json.*composerFileNotReadable/));
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
