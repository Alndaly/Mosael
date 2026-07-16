export type AutomationBlockReason = "login_required" | "manual_required" | "permission_required";

export class AutomationBlockedError extends Error {
  constructor(
    readonly reason: AutomationBlockReason,
    message: string,
  ) {
    super(message);
    this.name = "AutomationBlockedError";
  }
}

export const isAutomationBlockedError = (error: unknown): error is AutomationBlockedError => {
  return error instanceof AutomationBlockedError;
};
