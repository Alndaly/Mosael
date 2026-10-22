/** 内嵌浏览器的坐标换算(见 coords.cjs):四套坐标系只在这里相乘。 */
export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}
export declare function safeZoom(value: unknown): number;
export declare function pageToView(value: number, pageZoom: number): number;
export declare function cssToDip(rect: Rect, hostZoom: number): Rect;
export declare function dipToCss(rect: Rect, hostZoom: number): Rect;
export declare function pageToDip(value: number, options?: { pageZoom?: number; hostZoom?: number }): number;
export declare function captureToCss(
  captured: { width: number; height: number },
  cssSize: [number, number],
): { width: number; height: number } | null;
