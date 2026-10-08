/**
 * 定时任务详情页头里「计划」「下次运行」两格的说法。
 *
 * 按 trigger_type 分别说(后端 scheduler.compute_next_run_at 认的那几种:manual / webhook /
 * once / interval / daily / weekly)。此前只认 interval 的秒数:每天 09:00 的任务端出原始
 * JSON `{"time":"09:00"}`,按小时建的说「每 3600 秒」;下次运行一格只要没有时间就说
 * 「手动触发,不排期」—— 停用的循环任务、webhook 任务也这么说,而它们都不是手动的。
 */
import type { ScheduledTask } from "@/api/client";
import type { MessageKey } from "@/app/messages";

type Translate = (key: MessageKey) => string;
type TaskLike = Pick<ScheduledTask, "trigger_type" | "schedule" | "enabled" | "next_run_at">;

/** 间隔秒数 → 最大的整单位:3600 说「每小时」,不说「每 3600 秒」。 */
function intervalText(seconds: number, t: Translate): string {
  if (seconds === 3600) return t("everyHour");
  if (seconds % 3600 === 0) return t("everyHours").replace("{n}", String(seconds / 3600));
  if (seconds % 60 === 0) return t("everyMinutes").replace("{n}", String(seconds / 60));
  return t("everySeconds").replace("{s}", String(seconds));
}

/** 后端 weekly 的 weekday 是 Python 的 weekday():0 = 周一。星期名交给 Intl 按当前语言给。 */
function weekdayName(weekday: number, locale: string): string {
  // 2024-01-01 是周一。
  return new Date(2024, 0, 1 + weekday).toLocaleDateString(locale, { weekday: "long" });
}

export function scheduleText(task: TaskLike, t: Translate, locale: string, formatTime: (iso: string) => string): string {
  const schedule = (task.schedule ?? {}) as Record<string, unknown>;
  const time = typeof schedule.time === "string" && schedule.time ? schedule.time : "09:00";
  switch (task.trigger_type) {
    case "manual":
      return t("trigger_manual");
    case "webhook":
      return t("trigger_webhook");
    case "interval":
      if (typeof schedule.seconds === "number" && schedule.seconds > 0) return intervalText(schedule.seconds, t);
      break;
    case "daily":
      return t("schedDailyAt").replace("{time}", time);
    case "weekly":
      if (typeof schedule.weekday === "number" && schedule.weekday >= 0 && schedule.weekday <= 6)
        return t("schedWeeklyAt").replace("{weekday}", weekdayName(schedule.weekday, locale)).replace("{time}", time);
      break;
    case "once":
      if (typeof schedule.run_at === "string" && schedule.run_at) return t("schedOnceAt").replace("{time}", formatTime(schedule.run_at));
      break;
  }
  // 手动/Webhook 以外的空 schedule 说「未设置」;真有结构而这里不认识的,才退回 JSON —— 那时原文就是信息。
  return Object.keys(schedule).length === 0 ? t("schedNone") : JSON.stringify(schedule);
}

/** 这台电脑的时区(IANA 名)。建定时任务时带上:「每天 09:00」说的是这里的 09:00(后端不给就按 UTC 算)。 */
export function localTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

/** 按某个钟点排程的任务(每天 / 每周):它的「几点」才和时区有关。 */
export function scheduleUsesClock(task: Pick<ScheduledTask, "trigger_type">): boolean {
  return task.trigger_type === "daily" || task.trigger_type === "weekly";
}

/** 下次运行:有时间说时间;没有的话说清楚**为什么**没有 —— 手动、webhook、停用是三回事。 */
export function nextRunText(task: TaskLike, t: Translate, formatTime: (iso: string) => string): string {
  if (task.next_run_at) return formatTime(task.next_run_at);
  if (task.trigger_type === "manual") return t("manualNoSchedule");
  if (task.trigger_type === "webhook") return t("webhookNoSchedule");
  if (!task.enabled) return t("taskPausedNoSchedule");
  //: 启用着却没有下次(单次任务已经跑过)。
  return "—";
}
