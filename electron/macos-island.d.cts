export interface MacosIslandActivity {
  id: string;
  state: "ongoing" | "done" | "failed";
  title: string;
  detail?: string;
  progress?: number;
  priority?: number;
}

export interface MacosIslandOptions {
  binaryPath: string;
  onOpen?: (id: string) => void;
  log?: (line: string) => void;
  spawn?: (...args: unknown[]) => unknown;
  exists?: (path: string) => boolean;
  platform?: NodeJS.Platform;
}

export function createMacosIsland(options: MacosIslandOptions): {
  start(): boolean;
  setActivities(activities: readonly MacosIslandActivity[]): void;
  dispose(): void;
  readonly running: boolean;
};
export function encodeState(activities: readonly MacosIslandActivity[]): string;
export function parseIslandOutput(line: string): { type: "open"; id: string } | null;
export function toWire(activity: unknown): MacosIslandActivity | null;
