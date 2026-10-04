/**
 * 下载收不收的规则,以及它和后端那一份对得上。
 *
 * 两边各有一份扩展名清单、一个文件名清洗规则:Electron 下载之前先拦,后端入库时再收一次。对不上的后果
 * 都很安静 —— Electron 多收了,文件整个下完才被后端拒;Electron 少收了,后端认得的文件在这边就被取消。
 * 所以清单直接对着后端源码比,不在这里再抄一遍。
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import {
  DOWNLOAD_SUFFIXES,
  MAX_DOWNLOAD_BYTES,
  httpUrlOrEmpty,
  refuseDownload,
  safeDownloadName,
} from "./downloadRules";

const BACKEND = path.resolve(__dirname, "../../backend/app");

/** 从 Python 源码里取 `NAME = {".a", ".b", ...}` 这样一个集合字面量。 */
function pythonSet(file: string, name: string): string[] {
  const source = fs.readFileSync(path.join(BACKEND, file), "utf8");
  const match = source.match(new RegExp(`^${name}\\s*=\\s*\\{([^}]*)\\}`, "m"));
  if (!match) throw new Error(`${file} 里找不到 ${name} —— 后端改了写法,这条比对要跟着改`);
  return [...match[1].matchAll(/"(\.[a-z0-9]+)"/g)].map((m) => m[1]);
}

describe("下载规则", () => {
  it("扩展名清单和后端 web_download.DOWNLOAD_SUFFIXES 是同一份", () => {
    const backend = new Set([
      ...pythonSet("domain/assets/web_download.py", "_VIDEO"),
      ...pythonSet("domain/assets/web_download.py", "_IMAGE"),
      ...pythonSet("media/probe.py", "AUDIO_EXTENSIONS"),
      ...pythonSet("media/probe.py", "DOCUMENT_EXTENSIONS"),
    ]);
    expect(backend.size).toBeGreaterThan(30);
    expect([...DOWNLOAD_SUFFIXES].sort()).toEqual([...backend].sort());
  });

  it("文件名只取名字本身、清掉怪字符,和后端 safe_filename 一个结果", () => {
    // 这几条和 backend/tests/test_web_download.py 的 test_safe_filename_清掉控制字符与分隔符 一一对应。
    expect(safeDownloadName("a\\b\\c:d?.pdf")).toBe("c_d_.pdf");
    expect(safeDownloadName("\x00\x1f.png")).toBe("_.png");
    expect(safeDownloadName("")).toBe("download");
    expect(safeDownloadName("../../../etc/x.png")).toBe("x.png");
    const long = safeDownloadName(`${"长".repeat(300)}.mp4`);
    expect(long.endsWith(".mp4")).toBe(true);
    expect(long.length).toBeLessThanOrEqual(121);
  });

  it("类型不收、服务端报的总长超过上限都当场拒;不知道总长的先放行(边下边数)", () => {
    expect(refuseDownload("setup.exe", 10)).toEqual({ key: "downloadErr_type", params: { name: "setup.exe" } });
    expect(refuseDownload("archive.zip", 0)?.key).toBe("downloadErr_type");
    expect(refuseDownload("clip.MP4", MAX_DOWNLOAD_BYTES + 1)).toEqual({
      key: "downloadErr_tooLarge",
      params: { maxGb: 2 },
    });
    expect(refuseDownload("clip.mp4", 0)).toBeNull();
    expect(refuseDownload("report.pdf", 1024)).toBeNull();
  });

  it("出处只记 http(s) 的地址", () => {
    expect(httpUrlOrEmpty("https://cdn.example.com/a.png")).toBe("https://cdn.example.com/a.png");
    expect(httpUrlOrEmpty("blob:https://example.com/1234")).toBe("");
    expect(httpUrlOrEmpty("data:image/png;base64,AAAA")).toBe("");
  });
});
