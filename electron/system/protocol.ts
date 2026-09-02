import { app } from "electron";
import path from "node:path";

import { deepLinkFromArgv, parseDeepLink, PROTOCOL, type DeepLink } from "./deepLink";
import type { Capability, SystemContext } from "./types";

/**
 * mosael:// 协议唤起 + 拖到应用图标上的媒体文件。
 *
 * 两件事放一起,是因为它们在系统层面是同一类东西:**别的程序把一个东西交给我们**。
 * mac 走 open-url / open-file 事件,Windows/Linux 走命令行参数(第二个实例的 argv)。
 *
 * 安全边界见 deepLink.ts —— 协议只导航,不执行。
 */

/** 能被拖进来入库的媒体后缀。不认识的类型直接忽略,不要试图"猜"用户想干嘛。 */
const MEDIA_EXTENSIONS = new Set([
  ".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi",
  ".mp3", ".wav", ".m4a", ".aac", ".flac",
  ".png", ".jpg", ".jpeg", ".webp", ".gif",
]);

let context: SystemContext | null = null;

function deliver(channel: string, payload: unknown): void {
  if (!context) return;
  context.showWindow();
  const win = context.getWindow();
  if (!win || win.isDestroyed()) return;
  // 窗口可能刚被重建、页面还没加载完,这时 send 会丢。等到 did-finish-load 再发。
  if (win.webContents.isLoading()) {
    win.webContents.once("did-finish-load", () => win.webContents.send(channel, payload));
  } else {
    win.webContents.send(channel, payload);
  }
}

export function handleDeepLink(link: DeepLink | null): void {
  if (link) deliver("mosael:deep-link", link);
}

export function handleOpenFiles(paths: readonly string[]): void {
  const media = paths.filter((p) => typeof p === "string" && MEDIA_EXTENSIONS.has(path.extname(p).toLowerCase()));
  if (media.length) deliver("mosael:open-files", media);
}

/** 从 argv 里挑出可入库的文件路径(Windows/Linux 的「用 Mosael 打开」走这条)。 */
export function filesFromArgv(argv: readonly string[]): string[] {
  return argv.filter(
    (arg) => typeof arg === "string" && !arg.startsWith("-") && MEDIA_EXTENSIONS.has(path.extname(arg).toLowerCase()),
  );
}

export const protocol: Capability = {
  name: "protocol",
  register(ctx) {
    context = ctx;

    // 开发模式下 execPath 是 Electron 二进制,注册协议会把 mosael:// 指向裸 Electron ——
    // 而且这个注册是**系统级**的,卸载开发版之后还留在系统里劫持真实安装版。所以只在打包版注册。
    if (!ctx.isDev) {
      try {
        app.setAsDefaultProtocolClient(PROTOCOL);
      } catch (err) {
        console.warn("[system] 协议注册失败:", err);
      }
    }

    // mac:协议与文件都以事件送达(应用已在运行,或被系统为此拉起)。
    const onOpenUrl = (event: Electron.Event, url: string) => {
      event.preventDefault();
      handleDeepLink(parseDeepLink(url));
    };
    const onOpenFile = (event: Electron.Event, filePath: string) => {
      event.preventDefault();
      handleOpenFiles([filePath]);
    };
    app.on("open-url", onOpenUrl);
    app.on("open-file", onOpenFile);

    // 冷启动:mac 之外的平台上,协议/文件是作为启动参数进来的。
    handleDeepLink(deepLinkFromArgv(process.argv));
    const initialFiles = filesFromArgv(process.argv.slice(1));
    if (initialFiles.length) handleOpenFiles(initialFiles);

    return {
      dispose: () => {
        app.off("open-url", onOpenUrl);
        app.off("open-file", onOpenFile);
        context = null;
      },
    };
  },
};

/** 第二个实例被拉起时(Windows/Linux 的协议与文件唤起):把它的 argv 交给当前实例。 */
export function adoptSecondInstance(argv: readonly string[]): void {
  handleDeepLink(deepLinkFromArgv(argv));
  const files = filesFromArgv(argv.slice(1));
  if (files.length) handleOpenFiles(files);
  context?.showWindow();
}
