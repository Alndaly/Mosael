/** @vitest-environment jsdom */
import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 对话里附上压缩包 / 文件夹(ADR 0059):交给后端解开,技能包出一张「发现 N 个技能」的卡(点开是设置页同一个导入审阅,
 * 装了才算),别的进附件条、没收的逐个列出来。📎 菜单、拖放、粘贴走的都是 composerAttachments 这一套。
 */

const mocks = vi.hoisted(() => ({
  importAsset: vi.fn(),
  unpackArchive: vi.fn(),
  unpackFolder: vi.fn(),
  toastError: vi.fn(),
}));
vi.mock("@/api/client", () => ({
  importAsset: mocks.importAsset,
  unpackAgentBundleArchive: mocks.unpackArchive,
  unpackAgentBundleFolder: mocks.unpackFolder,
  assetFileUrl: (id: string) => `/file/${id}`,
  assetPreviewUrl: (id: string) => `/preview/${id}`,
  assetThumbnailUrl: (id: string) => `/thumb/${id}`,
}));
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: vi.fn() }) }));
//: 文案带上占位符,断言能看到填进去的是哪个文件夹、几个。
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => `${key}[{name}|{n}|{reason}]` }));
vi.mock("sonner", () => ({ toast: { error: mocks.toastError, success: vi.fn() } }));
//: 审阅本身(SkillImportDialog)有自己的测试;这里只看卡把哪份暂存交给了它、装好后卡收不收。
vi.mock("@/features/agent/skills/SkillImportDialog", () => ({
  SkillImportDialog: ({ staged, onClose, onInstalled }: { staged: { import_id: string } | null; onClose: () => void; onInstalled?: () => void }) =>
    staged ? (
      <div role="dialog" aria-label={`review-${staged.import_id}`}>
        <button type="button" onClick={() => { onInstalled?.(); onClose(); }}>install</button>
        <button type="button" onClick={onClose}>cancel</button>
      </div>
    ) : null,
}));

import { ComposerAttachMenu } from "./ComposerAttachMenu";
import { ComposerChips } from "./ComposerChips";
import { useComposerAttachments } from "./composerAttachments";

type Handle = ReturnType<typeof useComposerAttachments>;

function Harness({ onReady }: { onReady: (handle: Handle) => void }) {
  const attach = useComposerAttachments("ws-1");
  React.useEffect(() => {
    onReady(attach);
  });
  return (
    <div data-testid="area" {...attach.drop.handlers}>
      {attach.bundleNotes}
      <ComposerChips chips={attach.chips} uploading={attach.uploading} />
      <ComposerAttachMenu attach={attach} label="attach" />
    </div>
  );
}

function mount() {
  let handle!: Handle;
  render(<Harness onReady={(h) => (handle = h)} />);
  return () => handle;
}

const skillImport = (id: string, names: string[]) => ({
  import_id: id,
  source_name: "pack.zip",
  skills: names.map((name) => ({ name, title: "", description: "d", license: "", compatibility: "", allowed_tools: "", folder: name, conflict: "" })),
});
const bundle = (patch: Record<string, unknown>) => ({ source_name: "", skill_import: null, assets: [], skipped: [], ...patch });

/** 像 `<input webkitdirectory>` 选出来的文件:带着从选中那层开始的相对路径。 */
function picked(path: string, content = "x"): File {
  const file = new File([content], path.split("/").pop()!);
  Object.defineProperty(file, "webkitRelativePath", { value: path });
  return file;
}

beforeEach(() => {
  Object.values(mocks).forEach((mock) => mock.mockReset());
});

describe("压缩包", () => {
  it("技能包:出一张「发现 N 个技能」的卡,点开是导入审阅;装好了卡才收起,什么都没装之前一直在", async () => {
    mocks.unpackArchive.mockResolvedValue(bundle({ source_name: "pack.zip", skill_import: skillImport("imp-1", ["authenticity-video-director", "minimax-h3-video-prompt"]) }));
    const get = mount();
    const zip = new File(["PK"], "pack.zip", { type: "application/zip" });
    await act(async () => {
      await get().accept([zip]);
    });

    expect(mocks.unpackArchive).toHaveBeenCalledWith("ws-1", zip);
    expect(mocks.importAsset).not.toHaveBeenCalled();
    expect(screen.getByText("composerBundleSkills[pack.zip|2|{reason}]")).toBeTruthy();
    expect(screen.getByText("authenticity-video-director、minimax-h3-video-prompt")).toBeTruthy();
    //: 卡不是附件:这条消息照样是空的。
    expect(get().isEmpty).toBe(true);

    //: 发一条消息(输入框清空)卡也还在 —— 「装好后帮我…」先说再装是常有的事。
    act(() => get().clear());
    fireEvent.click(screen.getByRole("button", { name: /composerBundleReview/ }));
    expect(screen.getByRole("dialog", { name: "review-imp-1" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "cancel" }));
    expect(screen.getByText(/composerBundleSkills/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /composerBundleReview/ }));
    fireEvent.click(screen.getByRole("button", { name: "install" }));
    expect(screen.queryByText(/composerBundleSkills/)).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("技能包点「忽略」:卡收起,什么都没装", async () => {
    mocks.unpackArchive.mockResolvedValue(bundle({ skill_import: skillImport("imp-2", ["x"]) }));
    const get = mount();
    await act(async () => {
      await get().accept([new File(["PK"], "x.zip")]);
    });
    fireEvent.click(screen.getByRole("button", { name: /composerBundleDismiss/ }));
    expect(screen.queryByText(/composerBundleSkills/)).toBeNull();
  });

  it("普通压缩包:进了素材库的出现在附件条里,没收的逐个列出原因;发出去以后这条提示收起", async () => {
    mocks.unpackArchive.mockResolvedValue(
      bundle({
        source_name: "资料 包.zip",
        assets: [
          { id: "img", name: "资料 包/图/封面.png", kind: "image" },
          { id: "doc", name: "资料 包.md", kind: "document" },
        ],
        skipped: [
          { path: "资料 包/tool.exe", reason: "unsupported" },
          { path: "资料 包/huge.log", reason: "too_large" },
        ],
      }),
    );
    const get = mount();
    await act(async () => {
      await get().accept([new File(["PK"], "资料 包.zip", { type: "application/zip" })]);
    });

    expect(get().media.map((one) => one.id)).toEqual(["img", "doc"]);
    expect(screen.getByRole("button", { name: "资料 包.md" })).toBeTruthy();
    expect(screen.getByText("composerBundleSkipped[资料 包.zip|2|{reason}]")).toBeTruthy();
    expect(screen.getByText(/资料 包\/tool\.exe · composerSkipUnsupported/)).toBeTruthy();
    expect(screen.getByText(/资料 包\/huge\.log · composerSkipTooLarge/)).toBeTruthy();

    act(() => get().clear());
    expect(screen.queryByText(/composerBundleSkipped/)).toBeNull();
  });

  it("后端拒了(炸弹、路径穿越):报出是哪个包、为什么,附件条上什么都不多", async () => {
    mocks.unpackArchive.mockRejectedValue(new Error("解开后超过 20MB"));
    const get = mount();
    await act(async () => {
      await get().accept([new File(["PK"], "bomb.zip")]);
    });
    expect(mocks.toastError).toHaveBeenCalledWith(expect.stringMatching(/bomb\.zip.*20MB/));
    expect(get().isEmpty).toBe(true);
  });
});

describe("文件夹", () => {
  it("📎 菜单里能选文件夹:系统垃圾先丢掉,文件和相对路径交给后端", async () => {
    mocks.unpackFolder.mockResolvedValue(bundle({ assets: [{ id: "doc", name: "笔记 🎬.md", kind: "document" }] }));
    mount();
    fireEvent.click(screen.getByRole("button", { name: "attach" }));
    expect(await screen.findByRole("menuitem", { name: /composerAttachFolder/ })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: /composerAttachFiles/ })).toBeTruthy();

    const input = screen.getByTestId("composer-folder-input") as HTMLInputElement;
    expect(input.hasAttribute("webkitdirectory")).toBe(true);
    const files = [picked("笔记 🎬/第一场.txt"), picked("笔记 🎬/.DS_Store"), picked("笔记 🎬/.git/HEAD"), picked("笔记 🎬/图/._a.png")];
    await act(async () => {
      fireEvent.change(input, { target: { files } });
    });

    await waitFor(() => expect(mocks.unpackFolder).toHaveBeenCalledTimes(1));
    const [workspaceId, name, sent] = mocks.unpackFolder.mock.calls[0] as [string, string, { path: string }[]];
    expect([workspaceId, name]).toEqual(["ws-1", "笔记 🎬"]);
    expect(sent.map((one) => one.path)).toEqual(["笔记 🎬/第一场.txt"]);
    expect(await screen.findByRole("button", { name: "笔记 🎬.md" })).toBeTruthy();
  });

  it("太大的文件夹不传,当场说一次最多多少", async () => {
    const get = mount();
    const big = picked("素材/片子.mov");
    Object.defineProperty(big, "size", { value: 21 * 1024 * 1024 });
    await act(async () => {
      await get().acceptFolder({ name: "素材", files: [{ file: big, path: "素材/片子.mov" }] });
    });
    expect(mocks.unpackFolder).not.toHaveBeenCalled();
    expect(mocks.toastError).toHaveBeenCalledWith("composerFolderTooLarge[素材|4000|{reason}]");
  });

  it("拖进一个文件夹:一层层读出来(跳过 .git),和选的文件夹走同一条路", async () => {
    mocks.unpackFolder.mockResolvedValue(bundle({ skill_import: skillImport("imp-3", ["authenticity-video-director"]) }));
    mount();
    const fileEntry = (name: string) => ({ isFile: true, isDirectory: false, name, file: (ok: (file: File) => void) => ok(new File(["x"], name)) });
    const dirEntry = (name: string, children: unknown[]) => ({
      isFile: false,
      isDirectory: true,
      name,
      createReader: () => {
        //: readEntries 要读到空为止:第一次给全部,第二次给空。
        let done = false;
        return {
          readEntries: (ok: (batch: unknown[]) => void) => {
            const batch = done ? [] : children;
            done = true;
            ok(batch);
          },
        };
      },
    });
    const root = dirEntry("活人感 skill", [
      fileEntry("SKILL.md"),
      dirEntry("references", [fileEntry("diagnosis.md")]),
      dirEntry(".git", [fileEntry("HEAD")]),
      fileEntry(".DS_Store"),
    ]);
    const shell = new File([""], "活人感 skill");
    const event = new MouseEvent("drop", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "dataTransfer", {
      value: { types: ["Files"], files: [shell], items: [{ kind: "file", type: "", webkitGetAsEntry: () => root, getAsFile: () => shell }] },
    });
    act(() => {
      screen.getByTestId("area").dispatchEvent(event);
    });

    await waitFor(() => expect(mocks.unpackFolder).toHaveBeenCalledTimes(1));
    const [, name, sent] = mocks.unpackFolder.mock.calls[0] as [string, string, { path: string }[]];
    expect(name).toBe("活人感 skill");
    expect(sent.map((one) => one.path)).toEqual(["活人感 skill/SKILL.md", "活人感 skill/references/diagnosis.md"]);
    //: 文件夹那个空壳不当文件处理(以前它会被当成一个读不了的文件报错)。
    expect(mocks.importAsset).not.toHaveBeenCalled();
    expect(mocks.toastError).not.toHaveBeenCalled();
    expect(await screen.findByText(/composerBundleSkills\[活人感 skill\|1/)).toBeTruthy();
  });
});
