import fs from "node:fs";
import path from "node:path";

import { app, shell } from "electron";

import { IPC } from "../ipc-contract.cjs";
import type { Capability, SystemContext } from "./types";

/**
 * 用户自定义 CSS:一个磁盘上的文件,内容注入渲染层,改一下存盘就立刻生效。
 *
 * **为什么在 userData 而不是 `~/.mosael`。** 那个目录是**后端**的家(主库、媒体),而
 * 这个应用支持分布式部署 —— 后端可能根本不在这台机器上。把外观放过去意味着:你的个人配色
 * 住在服务器上、对该服务器的所有人生效、换台机器还不跟着你走。userData 才是客户端自己的
 * 存储(logs/ 和各账号的 Partitions/ 已经住在这儿),而外观在这个仓库里本来就是逐设备的
 * 概念(见 frontend/src/app/appearance.tsx:背景、透明度、模糊全存 localStorage)。
 *
 * **为什么盯目录而不是盯文件。** 大部分编辑器保存是「写临时文件 + 改名覆盖」,原文件的 inode
 * 就此作废,`fs.watch(文件)` 之后再也不响 —— 表现为「头一次改生效,之后怎么改都没反应」。
 * 盯着目录、按文件名过滤,改名换 inode 也照样收得到。
 */

const FILE_NAME = "custom.css";

/** 新建时写进去的模板。空文件对着一片空白无从下手,给几个真的能改的东西。 */
const TEMPLATE = `/* Mosael —— 自定义 CSS
 *
 * 这个文件里的样式**压过应用自带的所有样式**(它是无层级的,而且注入在最后),
 * 所以多数时候不需要 !important。存盘即生效,不用重启。
 *
 * 改主题色、圆角这类整体观感,最省事的是覆盖设计令牌:
 */

/*
:root {
  --primary: #7c3aed;
  --radius: 6px;
}
*/

/* 深色主题单独调: */
/*
.dark {
  --primary: #a78bfa;
}
*/

/* 也可以直接改某个元素。用开发者工具(Cmd/Ctrl+Option+I)选中它看类名。 */
`;

export function customCssPath(): string {
  return path.join(app.getPath("userData"), FILE_NAME);
}

/** 读文件内容;不存在或读不动时给空串 —— 自定义样式缺席不该让应用出问题。 */
export function readCustomCss(): string {
  try {
    return fs.readFileSync(customCssPath(), "utf8");
  } catch {
    return "";
  }
}

/** 文件不存在就按模板建一个,然后交给系统默认编辑器打开。返回路径。 */
export function ensureCustomCss(): string {
  const file = customCssPath();
  try {
    if (!fs.existsSync(file)) {
      fs.mkdirSync(path.dirname(file), { recursive: true });
      fs.writeFileSync(file, TEMPLATE, "utf8");
    }
  } catch (error) {
    console.warn("[custom-css] 建文件失败:", (error as Error).message);
  }
  return file;
}

/** 在访达 / 资源管理器里定位这个文件。文件还不存在时先建。 */
export function revealCustomCss(): string {
  const file = ensureCustomCss();
  shell.showItemInFolder(file);
  return file;
}

/** 用系统默认程序打开它(通常是用户自己的编辑器)。 */
export async function openCustomCss(): Promise<string> {
  const file = ensureCustomCss();
  await shell.openPath(file);
  return file;
}

export const customCss: Capability = {
  name: "custom-css",
  register(ctx: SystemContext) {
    const dir = app.getPath("userData");
    let watcher: fs.FSWatcher | null = null;
    // 一次保存往往触发多个事件(rename + change),抖一下再读,免得连推好几遍。
    let timer: ReturnType<typeof setTimeout> | null = null;

    const push = (): void => {
      const win = ctx.getWindow();
      if (!win || win.isDestroyed()) return;
      win.webContents.send(IPC.event.customCss, readCustomCss());
    };

    try {
      fs.mkdirSync(dir, { recursive: true });
      watcher = fs.watch(dir, (_event, filename) => {
        if (filename !== FILE_NAME) return;
        if (timer) clearTimeout(timer);
        timer = setTimeout(push, 80);
      });
    } catch (error) {
      // 监听不上不是致命的:设置页里还能手动重新加载,只是没有存盘即生效。
      console.warn("[custom-css] 监听 userData 目录失败:", (error as Error).message);
    }

    return {
      dispose: () => {
        if (timer) clearTimeout(timer);
        watcher?.close();
      },
    };
  },
};
