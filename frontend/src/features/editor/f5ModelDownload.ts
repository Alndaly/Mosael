import type { F5Model } from "@/api/domains/speech";

/**
 * 配音面板里「这份权重要不要下 / 下到哪了」那一行的状态。
 *
 * **全部从后端那份清单派生**(`GET /api/tts/f5-models`),组件里不存"我在下载"这种状态:
 * 刷新、切走再切回、重开面板,看到的都该是同一个答案。此前这一行只看 `status === "downloading"`,
 * 于是一次失败之后 status 变成 `failed`,界面就当它从没开始过 —— 直接变回「下载这个模型」,
 * 原因一个字都不说。那正是维护者截图里的第二种样子。
 */
export type F5DownloadPhase = "missing" | "downloading" | "failed" | "unknown";

export function f5DownloadPhase(model: F5Model | undefined, statusUnknown: boolean): F5DownloadPhase {
  //: "查不到"不是"没在下" —— 轮询本身失败时不能把这一行当成初始状态。
  if (statusUnknown) return "unknown";
  if (!model) return "missing";
  if (model.status === "downloading") return "downloading";
  if (model.status === "failed") return "failed";
  return "missing";
}

/**
 * 百分比**只从字节算**。
 *
 * 后端的 `progress` 和字节是同一份数据算出来的,但它可能还停在 0(量盘的那一拍还没到,
 * 或者下载在写出第一个字节之前就失败了)。照它画,用户看到的就是截图里的
 * 「下载中 0% · 0 MB / 5.4 GB」—— 和"卡住了"长得一模一样。
 *
 * 总量不知道就返回 `null`:界面说「大小未知」,不编一个 0%。
 * 封顶 99:100% 由「检查点在盘上」说,不由进度条说。
 */
export function f5DownloadPercent(model: F5Model): number | null {
  const total = model.total_bytes ?? 0;
  if (total <= 0) return null;
  const done = Math.max(0, model.downloaded_bytes ?? 0);
  const raw = (done / total) * 100;
  // 1% 以下保留一位小数:5.4 GB 在慢网络上下十几分钟,整数百分比会一直是 0% ——
  // 那和"卡住了"看起来一模一样。字节和速度也在走,百分比不该是唯一不动的那个。
  return Math.min(99, raw < 1 ? Math.round(raw * 10) / 10 : Math.round(raw));
}

/**
 * 这份清单还要不要接着问。
 *
 * 还在下 → 1.5 秒(和任务中心、工作台下载同一条规矩);都结束了 → 8 秒,慢慢看有没有别的窗口 /
 * 部署管理员那边重新点了一次。**不因为"失败了"就停**:停了的话,下一次变化永远看不到。
 */
export function f5ModelsPollMs(rows: readonly F5Model[] | undefined): number {
  return (rows ?? []).some((row) => row.status === "downloading") ? 1500 : 8000;
}
