/** 登录状态机(见 loginPhase.cjs)。 */
export type LoginPhase = "opening" | "waiting" | "verifying" | "bound" | "failed";
export interface LoginState {
  phase: LoginPhase;
  reason: string;
  detail: string;
  since: number;
  checks: number;
  lastError: string;
  terminal: boolean;
}
export declare function createLoginFlow(options?: {
  now?: () => number;
  onChange?: (state: LoginState) => void;
}): {
  state: () => LoginState;
  opened: () => boolean;
  verifying: () => boolean;
  notYet: (where?: string) => boolean;
  checkFailed: (error: unknown) => boolean;
  bound: () => boolean;
  fail: (reason: string, detail?: string) => boolean;
  isTerminal: () => boolean;
};
export declare const FAIL_REASONS: Set<string>;
