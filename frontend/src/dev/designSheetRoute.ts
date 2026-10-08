import React from "react";

/** 规格样张的地址(docs/DESIGN_LANGUAGE.md)。只在开发构建里认它,见 app/App.tsx。 */
export const DESIGN_SHEET_HASH = "#/dev/design";

const subscribe = (notify: () => void) => {
  window.addEventListener("hashchange", notify);
  return () => window.removeEventListener("hashchange", notify);
};

/** 地址此刻是不是规格样张。 */
export function useDesignSheetRoute(): boolean {
  return React.useSyncExternalStore(subscribe, () => window.location.hash.startsWith(DESIGN_SHEET_HASH), () => false);
}
