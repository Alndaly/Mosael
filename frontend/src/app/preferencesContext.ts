import React from "react";

import type { InterfaceFont } from "@/app/interfaceFonts";
import type { MessageKey } from "@/app/messages";

/**
 * 偏好的 context —— 单独放在这里,**只依赖 React 和类型**(见 app/contextIdentity.test.ts)。
 *
 * 此前它和 PreferencesProvider 住在 preferences.tsx,而那个模块要在运行时引文案表(`@/app/messages`)。几乎每次改动都会
 * 加一条文案:热更新沿着 import 往上走,preferences.tsx 既导出组件又导出 hook,就地替换不了,只能整个重跑 —— 重跑
 * 一次就 createContext 一个新的。外层还挂着旧的 Provider,之后重新渲染的组件拿新的去读,读到 null,整个窗口报
 * 「usePreferences must be used inside PreferencesProvider」(维护者那边合并一批代码之后就这样整窗挂过)。
 */

export type Theme = "light" | "dark" | "system";
export type Locale = "zh-CN" | "en-US";

/**
 * 从系统那边把文件交给 Mosael 时(访达 / 资源管理器的「打开方式」、拖到程序坞或任务栏的图标上),
 * 拿这些文件怎么办。
 *
 * - `import`:入库。**这是此前的唯一行为**,所以它是默认值 —— 升级上来的人不必先改设置。
 * - `preview`:先入库,**再立刻打开预览**。
 *
 * 「打开预览」为什么也要入库:渲染层**没有**办法预览一份不在素材库里的本地文件(证据见
 * lib/openExternalFiles.ts 头部)。预览这一层吃的全是素材行的地址,所以两条路的前半段是同一条。
 */
export type ExternalOpenBehavior = "import" | "preview";

export type PreferencesContextValue = {
  font: InterfaceFont;
  setFont: (font: InterfaceFont) => void;
  theme: Theme;
  setTheme: (theme: Theme) => void;
  /** 免提浮标浮不浮着。本地偏好 —— 见 provider 里那段说明。 */
  voiceDock: boolean;
  setVoiceDock: (on: boolean) => void;
  /** 外部打开的文件怎么处理。本地偏好:同一台机器上「双击一张图想干什么」是这台机器的事。 */
  externalOpen: ExternalOpenBehavior;
  setExternalOpen: (behavior: ExternalOpenBehavior) => void;
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: MessageKey) => string;
};

export const PreferencesContext = React.createContext<PreferencesContextValue | null>(null);
