import React from "react";

/**
 * 用户自定义 CSS。
 *
 * 文件在客户端自己的存储里(`<userData>/custom.css`,见 electron/system/customCss.ts 里
 * 关于「为什么不是 `~/.open-studio`」的说明),内容由主进程读出来推过来,这里负责注入。
 *
 * **注入方式决定它到底压不压得住。** 应用样式分两拨:Tailwind 的 `@layer base/components/
 * utilities`,以及 tokens.css 里少量无层级的规则。CSS 的规则是无层级 > 任何层,同层级再比
 * 出现顺序 —— 所以这段必须**无层级**(不包在 `@layer` 里)并且**排在最后**。实测确认过:
 * 这样注入的普通规则(不带 !important)压得过 `@layer utilities`,`:root` 上的令牌覆盖也生效。
 *
 * 「排在最后」不是插进去就完事:Vite 在开发模式下会不断把 HMR 的样式插到 `<head>` 里,
 * 插在我们后面就把我们压掉了。所以这里盯着 `<head>` 的子节点变化,一旦不是最后一个就挪回去。
 *
 * 开关存 localStorage,和背景/透明度那些一样是**逐设备**的偏好(见 appearance.tsx)。
 * 关掉不删文件 —— 它的用处正是「我的界面坏了,先关掉看看是不是我写的 CSS 干的」。
 */

const STYLE_ID = "openstudio-custom-css";
const ENABLED_KEY = "openstudio.customCss.enabled";

function readEnabled(): boolean {
  try {
    // 默认开:用户特地去建了这个文件,不该还要再找个开关才生效。
    return localStorage.getItem(ENABLED_KEY) !== "off";
  } catch {
    return true;
  }
}

function writeEnabled(enabled: boolean): void {
  try {
    localStorage.setItem(ENABLED_KEY, enabled ? "on" : "off");
  } catch {
    /* 隐私模式下写不了,忽略 —— 这一轮仍然生效,只是记不住 */
  }
}

function styleElement(): HTMLStyleElement {
  let el = document.getElementById(STYLE_ID) as HTMLStyleElement | null;
  if (!el) {
    el = document.createElement("style");
    el.id = STYLE_ID;
    document.head.append(el);
  }
  return el;
}

/** 把注入的 style 挪回 `<head>` 末尾。已经在末尾时什么都不做(否则会自触发 observer)。 */
function keepLast(el: HTMLStyleElement): void {
  if (document.head.lastElementChild !== el) document.head.append(el);
}

export interface CustomCssState {
  /** 这个环境支不支持(桌面端才有)。 */
  supported: boolean;
  /** 文件的绝对路径,拿不到时为空串。 */
  path: string;
  /** 文件当前内容。 */
  css: string;
  enabled: boolean;
  setEnabled: (enabled: boolean) => void;
  /** 用系统默认编辑器打开;文件不存在会先按模板建出来。 */
  open: () => Promise<void>;
  /** 在访达 / 资源管理器里定位。 */
  reveal: () => Promise<void>;
}

const CustomCssContext = React.createContext<CustomCssState | null>(null);

export function CustomCssProvider({ children }: { children: React.ReactNode }): React.ReactElement {
  const bridge = typeof window === "undefined" ? undefined : window.openStudioDesktop?.customCss;
  const supported = Boolean(bridge);
  const [css, setCss] = React.useState("");
  const [path, setPath] = React.useState("");
  const [enabled, setEnabledState] = React.useState(readEnabled);

  // 启动读一次 + 订阅存盘推送。
  React.useEffect(() => {
    if (!bridge) return;
    let alive = true;
    void bridge.read().then((value) => alive && setCss(value));
    void bridge.path().then((value) => alive && setPath(value));
    const off = bridge.onChange((value) => alive && setCss(value));
    return () => {
      alive = false;
      off();
    };
  }, [bridge]);

  // 注入,并守住「排在最后」。
  React.useEffect(() => {
    if (!supported) return;
    const el = styleElement();
    el.textContent = enabled ? css : "";
    keepLast(el);
    const observer = new MutationObserver(() => keepLast(el));
    observer.observe(document.head, { childList: true });
    return () => observer.disconnect();
  }, [css, enabled, supported]);

  const value = React.useMemo<CustomCssState>(
    () => ({
      supported,
      path,
      css,
      enabled,
      setEnabled: (next: boolean) => {
        writeEnabled(next);
        setEnabledState(next);
      },
      open: async () => {
        const file = await bridge?.open();
        if (file) setPath(file);
      },
      reveal: async () => {
        const file = await bridge?.reveal();
        if (file) setPath(file);
      },
    }),
    [bridge, css, enabled, path, supported],
  );

  return <CustomCssContext.Provider value={value}>{children}</CustomCssContext.Provider>;
}

export function useCustomCss(): CustomCssState {
  const value = React.useContext(CustomCssContext);
  if (!value) throw new Error("useCustomCss 必须在 CustomCssProvider 内使用");
  return value;
}
