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

/**
 * 页面上找不到要操作的元素(按选择器或按文字)。单独一类,调用方才分得清「还没出现,再等等」和别的失败:
 * 浏览器自动化的点击 / 输入据此在一个短等待里重试(见 browserActions),而不是页面还在渲染就报错。
 */
export class ElementMissingError extends Error {
  constructor(
    readonly target: string,
    message: string,
  ) {
    super(message);
    this.name = "ElementMissingError";
  }
}
