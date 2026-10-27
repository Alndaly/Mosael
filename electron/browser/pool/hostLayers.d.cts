/** 声明式让位(见 hostLayers.cjs)。 */
export type HostLayerKind = "region" | "cover" | "overlay" | "panels" | "inset";
export interface HostLayerDirectives {
  reasons: string[];
  panelsHidden: boolean;
  insetRight: number;
  insetLeft: number;
}
export declare function createHostLayers(): {
  set(id: string, claim: { kind: string; active: boolean; width?: number; side?: "left" | "right" }): HostLayerDirectives;
  clear(id: string): HostLayerDirectives;
  directives(): HostLayerDirectives;
  size(): number;
};
export declare const KINDS: readonly string[];
