import { app, Menu, nativeImage, Tray } from "electron";

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

/** 托盘图标像素尺寸:menu bar / 通知区域都按小图标渲染,给原图会糊或过大。 */
const ICON_SIZE = 18;

function buildIcon(ctx: SystemContext) {
  // Mosael 的新图标本身承载品牌渐变，因此各平台都使用应用图标；旧的单色模板不再分发。
  const template = process.platform === "darwin" && ctx.trayIconPath;
  const image = nativeImage.createFromPath(template ? ctx.trayIconPath! : ctx.iconPath);
  if (image.isEmpty()) return image;
  if (template) {
    // 模板图像交给系统着色,自己不要再 resize:@2x 那份会被一起丢掉,Retina 上就糊了。
    image.setTemplateImage(true);
    return image;
  }
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
      dispose: () => trayIcon.destroy(),
    };
  },
};
