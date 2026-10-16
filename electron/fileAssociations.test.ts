/**
 * 「打开方式」里声明的后缀,主进程必须真的接得住。
 *
 * 这两份清单住在两个语言、两个进程里,谁也不知道谁:`package.json` 的 `build.mac.fileAssociations`
 * 是给 **macOS 的 Info.plist**(`CFBundleDocumentTypes`)看的 —— 系统据此把 Mosael 摆进右键
 * 「打开方式」;而**收不收**这个文件由主进程的 `MEDIA_EXTENSIONS` 说了算(见
 * electron/system/protocol.handleOpenFiles)。
 *
 * 两边对不上的后果是**静默的**:系统喊 Mosael 去开一个 `.heic`,`handleOpenFiles` 一看后缀不在集合里,
 * 连 IPC 都不发 —— 渲染层从头到尾不知道有人开过文件,没有提示、没有失败、什么都没发生。用户看到的是
 * 「双击了,应用闪一下,没了」,而这条路上没有任何地方会报错。
 *
 * 所以这里钉一个方向:**声明出去的,必须是主进程认识的**(反过来不要求:`MEDIA_EXTENSIONS` 里的
 * `.avi` 就没进「打开方式」,那是"能拖进来"和"系统替我们开"两件事,不必一样多)。
 *
 * mac 的真实注册发生在打包产物里,这条测试**不能**代替真机验证:它只保证写进 package.json 的形状
 * 是对的、且和主进程对得上。装出来的包上还得看一眼 `Info.plist`(见报告里的步骤)。
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const ROOT = path.resolve(__dirname, "..");
const build = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8")).build as {
  mac: { fileAssociations: { ext: string[]; name: string; role?: string; rank?: string }[] };
  win?: Record<string, unknown>;
  nsis?: Record<string, unknown>;
  linux?: unknown;
  fileAssociations?: unknown;
};
const associations = build.mac.fileAssociations;

/** 主进程那份集合。它 import 了 electron,不能直接 require;从源码里读出来(和 packagedFiles.test.ts 同一个办法)。 */
function mainProcessExtensions(): Set<string> {
  const source = fs.readFileSync(path.join(__dirname, "system", "protocol.ts"), "utf8");
  const block = /const MEDIA_EXTENSIONS = new Set\(\[([\s\S]*?)\]\);/.exec(source);
  expect(block, "electron/system/protocol.ts 里的 MEDIA_EXTENSIONS 没找到 —— 改名了就同步改这条").not.toBeNull();
  const found = [...block![1].matchAll(/"(\.[a-z0-9]+)"/g)].map((match) => match[1]);
  expect(found.length).toBeGreaterThan(10);
  return new Set(found);
}

const declared = associations.flatMap((one) => one.ext.map((ext) => `.${ext.toLowerCase()}`));

describe("「打开方式」里声明的后缀", () => {
  it("主进程都接得住 —— 对不上的那个是静默的「双击了没反应」", () => {
    const accepted = mainProcessExtensions();
    expect(declared.filter((ext) => !accepted.has(ext))).toEqual([]);
  });

  it("图片这一组在:主进程认的每一种图片后缀都进了「打开方式」", () => {
    const images = associations.find((one) => one.name === "图片");
    expect(images, "mac.fileAssociations 里没有「图片」这一组").toBeDefined();
    const acceptedImages = [...mainProcessExtensions()].filter((ext) =>
      [".png", ".jpg", ".jpeg", ".webp", ".gif"].includes(ext),
    );
    expect(acceptedImages.length).toBe(5);
    expect([...images!.ext].sort()).toEqual(acceptedImages.map((ext) => ext.slice(1)).sort());
  });

  it("只当看的程序、而且是备选:不与 QuickTime / 预览 争当默认程序", () => {
    //: rank 缺省是 Default、role 缺省是 Editor —— 那样双击图片打开的会是 Mosael(用户报过的正是这个)。
    for (const one of associations) {
      expect({ name: one.name, rank: one.rank, role: one.role }).toEqual({
        name: one.name,
        rank: "Alternate",
        role: "Viewer",
      });
    }
  });

  it("每一组的 name 都是中文字,且不重名 —— 名字就是 Info.plist 里的 CFBundleTypeName", () => {
    const names = associations.map((one) => one.name);
    expect(new Set(names).size).toBe(names.length);
    for (const name of names) expect(name).toMatch(/^[\u4e00-\u9fa5]+$/);
  });

  it("mac 之外一处都不声明:Windows 交给 build/installer.nsh,顶层的会进 Windows 包抢默认程序", () => {
    //: Windows 由 build/installer.nsh 自己写注册表(只进 OpenWithProgids 的候选),那边的清单
    //: 由 backend/tests/test_windows_file_associations.py 与这里钉成同一份。
    expect(build.fileAssociations).toBeUndefined();
    expect(build.win?.fileAssociations).toBeUndefined();
    expect(build.nsis?.fileAssociations).toBeUndefined();
  });
});
