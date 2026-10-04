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
 * 这一步被中止了:运行被取消、后端放弃了这条动作(见 browserWorker 的 abandon)。页面驱动在等页面的地方
 * (脚本、导航、轮询)都认中止开关,扳下的那一刻就抛它 —— 而不是等脚本自己跑完。
 * 消息沿用发布执行器一直用的那句(publishWorker 按它认「用户取消」)。
 */
export class ActionAbortedError extends Error {
  constructor() {
    super("Task was cancelled by user.");
    this.name = "ActionAbortedError";
  }
}

/** 页面里的脚本过了预算还没算完。带着预算,调用方才说得出「跑了多久」。 */
export class EvaluateTimeoutError extends Error {
  constructor(readonly budgetMs: number) {
    super("evaluate timeout (page not settled)");
    this.name = "EvaluateTimeoutError";
  }
}

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
