import React from "react";

import { OverChromeModals } from "@/components/ui/overChromeModal";
import { useNativeViewInFront } from "@/lib/nativeView";

/**
 * **原生视图在前台时,应用级的浮层怎么让**(ADR 0051)。
 *
 * 内嵌浏览器、ComfyUI 工作台的画布是挂在主窗口上的原生视图,永远画在 Mosael 的界面上面。应用级的浮层大多不是人在视图里
 * 点出来的,是系统通知、后台轮询、快捷键从外面开的 —— 画在视图底下就是看不见、点不着,人还以为什么都没发生。
 *
 * 一条规矩:**要么画在看得见的地方(外壳里、浮层视图上),要么请视图让开,要么先收起视图再走;不许画在视图底下。**
 * 按浮层的性质分四种处理,下面这张表登记每一个,`design/overlaysOverNativeViews.test.ts` 盯着新加的全局浮层都进表、
 * 每一种处理都真的接上了:
 *
 * - `aside` 让开:要人马上看、要操作的(弹出层、对话框、命令面板)。挂在 `<OverNativeView>` 里,里面的弹窗抬过外壳、开着时
 *   请原生视图让开(和看大图同一套,先铺冻结的画面再挪开,见 nativeViewAside)。
 * - `chrome` 收进外壳:后台冒出来的、常驻的(确认卡、免提浮标)。自己跳出来盖住正在看的网页不合适 —— 收成外壳顶栏上的
 *   一个小标(`ChromeStatusSlot`),人点了才展开。
 * - `float` 画在视图上面:只是告知、几秒就走的(提示条)。交给浮层视图画在网页上面,上面的按钮照样点得到(toastMirror)。
 * - `leave` 先收起视图再走:换地方的(深链落地、命令面板和任务中心里的「前往」)。工作台里没存的改动还在(视图只是收起),
 *   不另弹确认。
 *
 * 内嵌浏览器和工作台是同一个视图机制,同一条规矩(D38)。
 */
export type OverlayHandling = "aside" | "chrome" | "float" | "leave";

export const GLOBAL_OVERLAYS = {
  //: 系统通知「需要登录」「需要你处理」点进来(mosael:open-tasks):让开,打开任务中心(D34)
  TaskCenter: { file: "components/jobs/TaskCenter.tsx", handling: "aside" },
  //: ⌘K、顶栏的搜索按钮;网页里按的 ⌘K 由主进程截下来交回(D36)
  CommandPalette: { file: "components/layout/CommandPalette.tsx", handling: "aside" },
  //: 配音库的嗓子第一次交给远端引擎念时那一问:后台的请求撞上 409 才弹
  RemoteVoiceConsentHost: { file: "features/voice/remoteVoiceConsent.tsx", handling: "aside" },
  //: 等人拍板的卡:外壳顶栏上亮「N 张卡等你拍板」,点了才让开、展开(ADR §3)
  ConfirmationCenter: { file: "features/agent/ConfirmationCenter.tsx", handling: "chrome" },
  //: 免提浮标:收成外壳顶栏上的一个图标,说话照常(D37)
  VoiceDock: { file: "features/agent/VoiceDock.tsx", handling: "chrome" },
  //: 右下角的提示条:画进浮层视图,按钮点得到(D33)
  AppToaster: { file: "app/App.tsx", handling: "float" },
  //: mosael:// 深链、拖到 Dock 图标上的文件(D35)
  DesktopDeepLinks: { file: "lib/deepLink.ts", handling: "leave" },
  //: 邀请链接 mosael://open?join=…:加入之后切到那个工作区(ADR 0054)
  InviteDeepLinks: { file: "lib/inviteLinks.ts", handling: "leave" },
} as const satisfies Record<string, { file: string; handling: OverlayHandling }>;

export type GlobalOverlay = keyof typeof GLOBAL_OVERLAYS;

/**
 * `aside` 那一类挂在它里面:原生视图在前台时,里面打开的 Dialog / AlertDialog 抬过外壳、开着时请视图让开
 * (见 overChromeModal);弹出层(任务中心)读同一个范围自己接(`useOverChromeModal().aside`)。视图不在前台时什么都不变。
 */
export function OverNativeView({ children }: { children: React.ReactNode }) {
  const inFront = useNativeViewInFront();
  return <OverChromeModals.Provider value={inFront}>{children}</OverChromeModals.Provider>;
}
