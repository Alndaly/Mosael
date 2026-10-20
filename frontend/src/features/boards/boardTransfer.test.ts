import { describe, expect, it, vi } from "vitest";

import { messages, type MessageKey } from "@/app/messages";
import type { BoardCanvas } from "@/api/client";

import {
  BoardFileError,
  MAX_BOARD_FILE_BYTES,
  boardExportFilename,
  boardFileOf,
  boardImportErrorText,
  parseBoardFile,
  readBoardFile,
  uniqueBoardName,
} from "./boardTransfer";

/** 一份带各种格子、连线、标记的画布:导出的必须原样是它。 */
const canvas: BoardCanvas = {
  items: [
    {
      id: "n1",
      kind: "note",
      x: 12,
      y: 34,
      width: 220,
      height: 140,
      text: "一只猫",
      color: "yellow",
      form: { prompt: "画一只猫", provider: "local" },
    },
    { id: "i1", kind: "image", x: 300, y: 34, asset_id: "asset-1" },
  ],
  edges: [{ id: "e1", source: "n1", target: "i1", label: "参考" }],
  markers: [{ id: "m1", name: "开头", x: 0, y: 0 }],
};

const boardFile = (overrides: Record<string, unknown> = {}) => ({
  format: "mosael.board",
  version: 1,
  name: "灵感",
  canvas,
  ...overrides,
});

const problemOf = (input: string, filename?: string): string => {
  try {
    parseBoardFile(input, filename);
  } catch (error) {
    expect(error).toBeInstanceOf(BoardFileError);
    return (error as BoardFileError).problem;
  }
  throw new Error("这份文件应当被拒绝");
};

const zh = (key: MessageKey) => messages["zh-CN"][key];

/** 坏文件 -> 给用户看的那一句(不是错误码)。 */
const messageOf = (input: string): string => {
  try {
    parseBoardFile(input);
  } catch (error) {
    return boardImportErrorText(zh, error as BoardFileError);
  }
  throw new Error("这份文件应当被拒绝");
};

describe("导出画板文件", () => {
  it("内容是 format / version / name / canvas,canvas 原样引用、不裁剪", () => {
    const file = boardFileOf("灵感", canvas);
    expect(file).toEqual({ format: "mosael.board", version: 1, name: "灵感", canvas });
    //: 原样 —— 不是副本、也不只挑 items / edges。
    expect(file.canvas).toBe(canvas);
  });

  it("文件名是「画板名.mosael-board.json」,非法字符替换、过长截断、留出扩展名", () => {
    expect(boardExportFilename("灵感")).toBe("灵感.mosael-board.json");
    expect(boardExportFilename('分镜/甲:乙*?"<>|')).toBe("分镜_甲_乙______.mosael-board.json");
    expect(boardExportFilename("  名字...  ")).toBe("名字.mosael-board.json");
    //: ASCII 长名按码点封顶 80。
    expect(boardExportFilename("a".repeat(120))).toBe(`${"a".repeat(80)}.mosael-board.json`);
    //: 中文名同时受 UTF-8 字节封顶(255 字节留给扩展名),存得下。
    const cjk = boardExportFilename("板".repeat(120));
    expect(cjk.endsWith(".mosael-board.json")).toBe(true);
    expect(new TextEncoder().encode(cjk).length).toBeLessThanOrEqual(255);
    //: 名字是空的也得存得下来。
    expect(boardExportFilename("   ")).toBe("board.mosael-board.json");
  });
});

describe("导入画板文件", () => {
  it("合法文件读出 name 和 canvas", () => {
    const parsed = parseBoardFile(JSON.stringify(boardFile()), "灵感.mosael-board.json");
    expect(parsed.name).toBe("灵感");
    expect(parsed.canvas).toEqual(canvas);
  });

  it("文件里没写名字时退回文件名(去掉 .mosael-board.json)", () => {
    const parsed = parseBoardFile(
      JSON.stringify(boardFile({ name: undefined })),
      "我的画板.mosael-board.json",
    );
    expect(parsed.name).toBe("我的画板");
    expect(parseBoardFile(JSON.stringify(boardFile({ name: "  " })), "x.json").name).toBe("x");
  });

  it("不是 JSON / 不是画板文件 / 没有 canvas / 版本不认识 / 太大 —— 各自拒绝", () => {
    expect(problemOf("not json")).toBe("invalidJson");
    expect(problemOf(JSON.stringify(boardFile({ format: "something.else" })))).toBe("notBoard");
    expect(problemOf(JSON.stringify({ format: "mosael.board", version: 1 }))).toBe("noCanvas");
    expect(problemOf(JSON.stringify(boardFile({ canvas: null })))).toBe("noCanvas");
    expect(problemOf(JSON.stringify(boardFile({ canvas: [] })))).toBe("noCanvas");
    expect(problemOf(JSON.stringify(boardFile({ version: 2 })))).toBe("version");
    expect(problemOf(JSON.stringify(boardFile({ version: undefined })))).toBe("version");

    const huge = JSON.stringify(boardFile({ canvas: { items: [], edges: [], note: "x".repeat(MAX_BOARD_FILE_BYTES + 1) } }));
    expect(problemOf(huge)).toBe("tooLarge");
  });

  it("大小按紧凑 JSON 的 UTF-8 字节数算,和社区分享的 2 MiB 同一把尺子", () => {
    expect(MAX_BOARD_FILE_BYTES).toBe(2 * 1024 * 1024);
    const fits = JSON.stringify(boardFile({ canvas: { items: [], edges: [], note: "x".repeat(MAX_BOARD_FILE_BYTES - 1024) } }));
    expect(parseBoardFile(fits).bytes).toBeLessThanOrEqual(MAX_BOARD_FILE_BYTES);
  });

  it("坏文件给的是人话(不是 error code)", () => {
    expect(messageOf("not json")).toBe(zh("boardsImportInvalidJson"));
    expect(messageOf(JSON.stringify(boardFile({ format: "something.else" })))).toBe(zh("boardsImportNotBoard"));
    expect(messageOf(JSON.stringify({ format: "mosael.board", version: 1 }))).toBe(zh("boardsImportNoCanvas"));
    expect(messageOf(JSON.stringify(boardFile({ version: 2 })))).toBe(
      zh("boardsImportVersion").replace("{version}", "2"),
    );
    const huge = JSON.stringify(boardFile({ canvas: { items: [], edges: [], note: "x".repeat(MAX_BOARD_FILE_BYTES + 1) } }));
    expect(messageOf(huge)).toBe(zh("boardsImportTooLarge"));
  });

  it("文件明显过大时先按文件大小挡掉,不读进内存", async () => {
    const text = vi.fn(async () => "{}");
    await expect(
      readBoardFile({ name: "huge.json", size: MAX_BOARD_FILE_BYTES * 8 + 1, text }),
    ).rejects.toMatchObject({ problem: "tooLarge" });
    expect(text).not.toHaveBeenCalled();
  });

  it("重名时加「副本」后缀;副本也重名就再编号", () => {
    const copy = (name: string) => `${name} 副本`;
    expect(uniqueBoardName("灵感", ["分镜"], copy)).toBe("灵感");
    expect(uniqueBoardName("灵感", ["灵感"], copy)).toBe("灵感 副本");
    expect(uniqueBoardName("灵感", ["灵感", "灵感 副本"], copy)).toBe("灵感 副本 2");
  });
});
