/** 登录排障用的站点请求追踪(见 netTrace.cjs)。 */
export interface NetEvent {
  kind: "done" | "error" | "redirect";
  method: string;
  path: string;
  status: number | string;
  resource: string;
}
export declare const DEFAULT_HOSTS: string[];
export declare function makeFilter(hosts?: string[]): (url: string) => URL | null;
export declare function watchSession(
  session: Electron.Session | null | undefined,
  onEvent: (event: NetEvent) => void,
  options?: { hosts?: string[]; seen?: WeakSet<object> },
): void;
