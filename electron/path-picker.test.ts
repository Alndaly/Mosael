/**
 * 路径格旁边的「选择…」(本机服务的目录、解释器):主进程弹的是哪一种框、从哪儿开始,交回什么。
 */
import { describe, expect, it, vi } from "vitest";

// CommonJS is intentional: main.cjs loads this exact module.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const picker = require("./path-picker.cjs") as {
  openDialogOptions: (request: Request) => Record<string, unknown>;
  pickPath: (dialog: { showOpenDialog: (...args: unknown[]) => Promise<unknown> }, window: unknown, request: Request) => Promise<string | null>;
};
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { parsePickPath } = require("./ipc-contract.cjs") as { parsePickPath: (value: unknown) => Request };

type Request = {
  kind: "directory" | "file";
  title: string;
  defaultPath: string;
  filters: { name: string; extensions: string[] }[];
};

function fakeDialog(result: { canceled: boolean; filePaths: string[] }) {
  return { showOpenDialog: vi.fn().mockResolvedValue(result) };
}

describe("选路径的对话框", () => {
  it("选文件夹:只能选文件夹,能当场新建,从格子里现在的值开始,挂在发起的窗口上", async () => {
    const dialog = fakeDialog({ canceled: false, filePaths: ["/Users/me/ComfyUI"] });
    const window = { id: 1 };
    const request = parsePickPath({ kind: "directory", title: "装在哪", defaultPath: " /Users/me " });

    await expect(picker.pickPath(dialog, window, request)).resolves.toBe("/Users/me/ComfyUI");
    const [parent, options] = dialog.showOpenDialog.mock.calls[0];
    expect(parent).toBe(window);
    expect(options).toEqual({
      properties: ["openDirectory", "createDirectory", "noResolveAliases"],
      title: "装在哪",
      defaultPath: "/Users/me",
    });
  });

  it("选文件:只能选文件;显示隐藏文件(解释器在 .venv 里),不把 .venv/bin/python 解析成基础解释器;过滤只给选文件用", async () => {
    const dialog = fakeDialog({ canceled: false, filePaths: ["/Users/me/ComfyUI/.venv/bin/python"] });
    const request = parsePickPath({
      kind: "file", title: "解释器", defaultPath: "/Users/me/ComfyUI/.venv/bin/python",
      filters: [{ name: "Python", extensions: ["exe"] }],
    });

    await expect(picker.pickPath(dialog, null, request)).resolves.toBe("/Users/me/ComfyUI/.venv/bin/python");
    const [options] = dialog.showOpenDialog.mock.calls[0];
    expect(options, "没有窗口就不挂").toEqual({
      properties: ["openFile", "showHiddenFiles", "noResolveAliases"],
      title: "解释器",
      defaultPath: "/Users/me/ComfyUI/.venv/bin/python",
      filters: [{ name: "Python", extensions: ["exe"] }],
    });
    expect(picker.openDialogOptions(parsePickPath({ kind: "directory", filters: [{ name: "x", extensions: ["py"] }] })))
      .not.toHaveProperty("filters");
  });

  it("格子是空的:不给 defaultPath,由系统决定从哪儿开始;取消是 null", async () => {
    const dialog = fakeDialog({ canceled: true, filePaths: [] });
    const request = parsePickPath({ kind: "file", defaultPath: "   " });

    await expect(picker.pickPath(dialog, null, request)).resolves.toBeNull();
    expect(dialog.showOpenDialog.mock.calls[0][0]).not.toHaveProperty("defaultPath");
    expect(dialog.showOpenDialog.mock.calls[0][0]).not.toHaveProperty("title");
  });

  it("渲染层送来的不对就不弹", () => {
    expect(() => parsePickPath({ kind: "folder" })).toThrow(/kind/);
    expect(() => parsePickPath(null)).toThrow(/object/);
    expect(() => parsePickPath({ kind: "file", defaultPath: "x".repeat(5000) })).toThrow(/too long/);
    expect(() => parsePickPath({ kind: "file", filters: [{ name: "x", extensions: ["../evil"] }] })).toThrow(/extensions/);
    expect(() => parsePickPath({ kind: "file", filters: "exe" })).toThrow(/filters/);
  });
});
