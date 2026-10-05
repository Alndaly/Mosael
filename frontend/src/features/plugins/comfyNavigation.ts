/**
 * 内嵌 ComfyUI 画布的操控方式(触控板 / 鼠标)在渲染层这一侧:**按连接记在这台电脑上**(localStorage),缺省看平台 ——
 * macOS 是触控板,别的是鼠标(也是 ComfyUI 自己的缺省)。真正去设的是主进程(electron/publish/comfyNavigation):只在这个视图里
 * 生效,写回 ComfyUI 服务器的那一下被拦下,坐在那台机器前面的人不受影响。
 */
import React from "react";

export type ComfyNavigation = "trackpad" | "mouse";

const PREFIX = "persist:pool-comfyui-";
const storageKey = (connectionId: string) => `mosael:comfy-navigation:${connectionId}`;

/** 内嵌视图的分区 → ComfyUI 连接 id;不是 ComfyUI 连接的视图是 null。 */
export function comfyConnectionOf(partition: string | null | undefined): string | null {
  if (!partition?.startsWith(PREFIX)) return null;
  const id = partition.slice(PREFIX.length);
  return /^[A-Za-z0-9_-]{1,64}$/.test(id) ? id : null;
}

/** 缺省:Mac 上是触控板(在 Mac 上用另一台机器上的 ComfyUI 时,它存的往往是鼠标的那一套),别处是鼠标。 */
export function defaultNavigation(platform = window.mosaelDesktop?.platform ?? ""): ComfyNavigation {
  return platform === "darwin" ? "trackpad" : "mouse";
}

export function readNavigation(connectionId: string, platform?: string): ComfyNavigation {
  try {
    const stored = window.localStorage.getItem(storageKey(connectionId));
    if (stored === "trackpad" || stored === "mouse") return stored;
  } catch {
    // 存不了(隐私模式):用缺省
  }
  return defaultNavigation(platform);
}

export function writeNavigation(connectionId: string, mode: ComfyNavigation): void {
  try {
    window.localStorage.setItem(storageKey(connectionId), mode);
  } catch {
    // 存不了就只管这一次
  }
}

/** 这座桥在不在(桌面版、主进程是带操控方式的那一版)。 */
export const navigationBridge = () => typeof window.mosaelBrowser?.setComfyNavigation === "function";

/**
 * 一个连接的操控方式:读记着的那个,挂上时交给主进程设一次(视图每次载入之后主进程自己再设),换了就记下、再设。
 * `supported`:不知道(还没回话 / 没就绪)是 null,这版前端没有这个设置是 false。
 */
export function useComfyNavigation(connectionId: string) {
  const [mode, setMode] = React.useState<ComfyNavigation>(() => readNavigation(connectionId));
  const [supported, setSupported] = React.useState<boolean | null>(null);
  React.useEffect(() => {
    setMode(readNavigation(connectionId));
    setSupported(null);
  }, [connectionId]);
  React.useEffect(() => {
    if (!navigationBridge()) return;
    let alive = true;
    void window.mosaelBrowser!.setComfyNavigation({ connectionId, mode }).then(
      (result) => {
        if (!alive || !result.ok) return;
        if (result.outcome === "unsupported") setSupported(false);
        else if (result.outcome === "applied") setSupported(true);
      },
      () => undefined,
    );
    return () => {
      alive = false;
    };
  }, [connectionId, mode]);
  const choose = React.useCallback(
    (next: ComfyNavigation) => {
      writeNavigation(connectionId, next);
      setMode(next);
    },
    [connectionId],
  );
  return { mode, choose, supported };
}
