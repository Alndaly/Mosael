/**
 * 往文件框塞文件:**点了名的选择器就只认它**。
 *
 * 发布适配器传的是「这个平台的上传框大概长这样」,平台把文件框藏进 shadow DOM 时退回「页面上第一个文件框」
 * 是对的。浏览器自动化的「上传文件」节点上写的选择器是**用户点名的那一个**:页面上有视频框和封面框时,
 * 写错一个字就把视频塞进封面框、节点还报成功(实测:#nofile 不存在,文件进了 #file)。
 */
import { describe, expect, it, vi } from "vitest";

vi.mock("electron", () => ({ app: { getPath: () => "/tmp" } }));

const { PageDriver } = await import("./pageDriver");

/** 一份 CDP 的 DOM:document(1) 下一个 #file(5);一个 shadow root(9)里藏着 #deep(12)。 */
function cdpPage() {
  const sent: Array<[string, Record<string, unknown>]> = [];
  const byRoot: Record<number, Record<string, number>> = {
    1: { "#file": 5, 'input[type="file"]': 5 },
    9: { "#deep": 12, 'input[type="file"]': 12 },
  };
  const wc = {
    on: () => undefined,
    debugger: {
      isAttached: () => true,
      attach: () => undefined,
      sendCommand: async (method: string, params: Record<string, unknown> = {}) => {
        sent.push([method, params]);
        if (method === "DOM.getDocument") return { root: { nodeId: 1 } };
        if (method === "DOM.querySelector") {
          return { nodeId: byRoot[params.nodeId as number]?.[params.selector as string] ?? 0 };
        }
        if (method === "DOM.getFlattenedDocument") {
          return {
            nodes: [
              { nodeId: 1, nodeName: "#document" },
              { nodeId: 5, nodeName: "INPUT", attributes: ["id", "file", "type", "file"] },
              { nodeId: 9, nodeName: "#document-fragment" },
              { nodeId: 12, nodeName: "INPUT", attributes: ["id", "deep", "type", "file"] },
            ],
          };
        }
        return {};
      },
    },
  };
  return { driver: new PageDriver(wc as never), sent };
}

const setFilesTarget = (sent: Array<[string, Record<string, unknown>]>) =>
  sent.filter(([method]) => method === "DOM.setFileInputFiles").map(([, params]) => params.nodeId);

describe("文件框:点了名的选择器只认它", () => {
  it("点名的选择器不存在:找不到就是找不到,不退回页面上别的文件框", async () => {
    const { driver, sent } = cdpPage();
    await expect(driver.fileInputAttached("#nofile", 0, { exact: true })).resolves.toBe(false);
    await expect(driver.setFiles("#nofile", "/tmp/a.txt", { exact: true })).rejects.toThrow(/#nofile/);
    expect(setFilesTarget(sent)).toEqual([]);
  });

  it("点名的选择器在 shadow DOM 里:照样找得到,塞进的就是它", async () => {
    const { driver, sent } = cdpPage();
    await expect(driver.fileInputAttached("#deep", 0, { exact: true })).resolves.toBe(true);
    await driver.setFiles("#deep", "/tmp/a.txt", { exact: true });
    expect(setFilesTarget(sent)).toEqual([12]);
  });

  it("发布适配器那种(不点名):选择器没对上时仍退回页面上的文件框", async () => {
    const { driver, sent } = cdpPage();
    await driver.setFiles("input[accept*=video]", "/tmp/a.mp4");
    expect(setFilesTarget(sent)).toEqual([5]);
  });
});
