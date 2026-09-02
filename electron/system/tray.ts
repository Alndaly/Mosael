import { app, Menu, nativeImage, nativeTheme, Tray } from "electron";

import { getOpenAtLogin, setOpenAtLogin } from "./loginItem";
import type { Capability, SystemContext, SystemStatus } from "./types";

/**
 * 托盘:关窗不退之后,这是应用还活着的**唯一可见证据**。
 *
 * 没有它,「关窗只是隐藏」就变成了「关不掉的幽灵进程」——用户点了叉,窗口没了,进程还在,
 * 没有任何入口能把它叫回来,也没有任何入口能真的退出。所以 residency 和 tray 必须同时存在。
 *
 * 菜单里放运行中的任务数,是因为窗口藏起来之后那是唯一能看到「它还在替我干活」的地方。
 */

/** Linux 没有专用资源时仍从主图标缩到通知区域尺寸。 */
const ICON_SIZE = 18;

export interface TrayAsset {
  path: string;
  template: boolean;
  dedicated: boolean;
}

/** 平台外观只决定用哪张资源；做成纯函数，免得主题切换逻辑只能靠真机撞。 */
export function resolveTrayAsset(
  ctx: SystemContext,
  platform: NodeJS.Platform = process.platform,
  dark = nativeTheme.shouldUseDarkColors,
): TrayAsset {
  if (platform === "darwin" && ctx.trayTemplatePath) {
    return { path: ctx.trayTemplatePath, template: true, dedicated: true };
  }
  if (platform === "win32") {
    const themed = dark ? ctx.trayDarkPath : ctx.trayLightPath;
    if (themed) return { path: themed, template: false, dedicated: true };
  }
  return { path: ctx.iconPath, template: false, dedicated: false };
}

function buildIcon(ctx: SystemContext) {
  let asset = resolveTrayAsset(ctx);
  let image = nativeImage.createFromPath(asset.path);
  // 专用资源被误删/漏打包时退回主图标，托盘入口不能跟着消失。
  if (image.isEmpty() && asset.path !== ctx.iconPath) {
    asset = { path: ctx.iconPath, template: false, dedicated: false };
    image = nativeImage.createFromPath(asset.path);
  }
  if (image.isEmpty()) return image;
  if (asset.template) {
    // 模板图像交给系统着色,自己不要再 resize:@2x 那份会被一起丢掉,Retina 上就糊了。
    image.setTemplateImage(true);
    return image;
  }
  // Windows 专用图标带有 1x/2x 表示，保留它们让系统自己选择 DPI；主图标才需要缩小。
  if (asset.dedicated) return image;
  return image.resize({ width: ICON_SIZE, height: ICON_SIZE });
}

export const tray: Capability = {
  name: "tray",
  register(ctx: SystemContext) {
    const icon = buildIcon(ctx);
    if (icon.isEmpty()) {
      // 图标缺失就不要建托盘:一个空图标的托盘项在 Windows 上是一块看不见的占位,
      // 用户既看不到它、也点不到它,比没有更糟。
      console.warn("[system] 托盘图标读取失败,跳过托盘:", ctx.iconPath);
      return;
    }

    const trayIcon = new Tray(icon);
    let status: SystemStatus = { runningJobs: 0 };

    // Windows 没有 macOS template image：准备同一标记的深浅两份，系统主题变化时即时换色。
    const syncWindowsTheme = () => {
      const next = buildIcon(ctx);
      if (!next.isEmpty()) trayIcon.setImage(next);
    };
    if (process.platform === "win32") nativeTheme.on("updated", syncWindowsTheme);

    const rebuild = () => {
      const busy = status.runningJobs > 0;
      trayIcon.setToolTip(busy ? `Mosael · ${status.runningJobs} 个任务运行中` : "Mosael");
      trayIcon.setContextMenu(
        Menu.buildFromTemplate([
          { label: busy ? `${status.runningJobs} 个任务运行中` : "空闲", enabled: false },
          { type: "separator" },
          { label: "打开 Mosael", click: () => ctx.showWindow() },
          ...(ctx.isDev
            ? []
            : [
                {
                  label: "开机时启动",
                  type: "checkbox" as const,
                  // 待批准也勾上:系统里已经登记了,只差用户去「系统设置 → 登录项」点允许。
                  // 显示成没勾就是把一件待办说成一次失败(见 loginItem.LoginItemState)。
                  checked: getOpenAtLogin().enabled,
                  click: (item: { checked: boolean }) => {
                    setOpenAtLogin(item.checked);
                    rebuild();
                  },
                },
              ]),
          { type: "separator" },
          { label: "退出 Mosael", click: () => app.quit() },
        ]),
      );
    };
    rebuild();

    // Windows/Linux 的惯例是单击托盘图标就唤出窗口;mac 的菜单栏项单击是弹菜单,
    // 由系统处理,这里不要再抢。
    if (process.platform !== "darwin") trayIcon.on("click", () => ctx.showWindow());

    return {
      onStatus: (next) => {
        if (next.runningJobs === status.runningJobs) return;
        status = next;
        rebuild();
      },
      dispose: () => {
        if (process.platform === "win32") nativeTheme.off("updated", syncWindowsTheme);
        trayIcon.destroy();
      },
    };
  },
};
