/** 结构化事件日志(见 trace.cjs)。 */
export declare function safeUrl(url: string): string;
export declare function scrub(value: unknown): unknown;
export interface Trace {
  event: (scene: string, fields?: Record<string, unknown>) => void;
  span: <T>(scene: string, fields: Record<string, unknown>, run: () => Promise<T>) => Promise<T>;
  file: string;
}
export declare function createTrace(options?: {
  dir?: string;
  maxBytes?: number;
  now?: () => number;
  fs?: unknown;
}): Trace;
