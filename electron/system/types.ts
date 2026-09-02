import type { BrowserWindow } from "electron";

/**
 * 系统能力层的公共上下文。
 *
 * 这里刻意**只有窗口和几个动作**,没有任何业务查询接口:系统层不许反过来去问后端
 * 「现在有几个任务在跑」。它对业务的唯一了解来自 pushStatus() 推进来的那点状态——
 * 这条单向依赖是这一层能被单独测、也能被整体摘掉的原因。
 */
export interface SystemContext {
  /** 取主窗口;可能为 null(mac 上窗口关掉但应用还活着的那段时间)。 */
  getWindow: () => BrowserWindow | null;
  /** 把主窗口显示出来并聚焦;窗口不在时由宿主重建。 */
  showWindow: () => void;
  isDev: boolean;
  /** 打包时随包分发的托盘图标绝对路径。 */
  iconPath: string;
  /** macOS 菜单栏模板图:黑色字形+透明底,系统会按菜单栏明暗自动着色。 */
  trayTemplatePath?: string;
  /** Windows 浅色任务栏上的深色托盘图。 */
  trayLightPath?: string;
  /** Windows 深色任务栏上的浅色托盘图。 */
  trayDarkPath?: string;
}

/** 渲染层推上来的运行状态。系统层只消费,不生产。 */
export interface SystemStatus {
  /** 正在跑的任务数(渲染/发布/生成/工作流合计)。 */
  runningJobs: number;
  /** 运行中任务的整体进度 0..1;后端还没报进度时给 null(此时任务栏走不确定态)。 */
  progress?: number | null;
}

export const EMPTY_STATUS: SystemStatus = { runningJobs: 0 };

/** 一个系统能力模块。register 返回的清理函数在退出时调用。 */
export interface Capability {
  name: string;
  register: (ctx: SystemContext) => CapabilityHandle | void;
}

export interface CapabilityHandle {
  /** 状态变化时被调用(所有能力都收到同一份快照)。 */
  onStatus?: (status: SystemStatus) => void;
  dispose?: () => void;
}
