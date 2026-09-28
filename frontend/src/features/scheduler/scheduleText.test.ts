import { describe, expect, it } from "vitest";

import { messages } from "@/app/messages";
import { nextRunText, scheduleText } from "./scheduleText";

const t = (key: keyof (typeof messages)["zh-CN"]) => messages["zh-CN"][key];
const formatTime = (iso: string) => `@${iso}`;
const task = (over: Partial<Parameters<typeof scheduleText>[0]>) => ({
  trigger_type: "manual",
  schedule: {},
  enabled: true,
  next_run_at: null,
  ...over,
});

describe("计划一格", () => {
  it("每天定时说钟点,不端出原始 JSON", () => {
    expect(scheduleText(task({ trigger_type: "daily", schedule: { time: "09:00" } }), t, "zh-CN", formatTime)).toBe("每天 09:00");
  });

  it("按小时建的说「每小时」,不说「每 3600 秒」", () => {
    expect(scheduleText(task({ trigger_type: "interval", schedule: { seconds: 3600 } }), t, "zh-CN", formatTime)).toBe("每小时");
    expect(scheduleText(task({ trigger_type: "interval", schedule: { seconds: 7200 } }), t, "zh-CN", formatTime)).toBe("每 2 小时");
    expect(scheduleText(task({ trigger_type: "interval", schedule: { seconds: 300 } }), t, "zh-CN", formatTime)).toBe("每 5 分钟");
    expect(scheduleText(task({ trigger_type: "interval", schedule: { seconds: 45 } }), t, "zh-CN", formatTime)).toBe("每 45 秒");
  });

  it("每周说星期几(weekday 0 = 周一,和后端同一个约定)", () => {
    expect(scheduleText(task({ trigger_type: "weekly", schedule: { weekday: 0, time: "08:30" } }), t, "zh-CN", formatTime)).toBe(
      "每星期一 08:30",
    );
  });

  it("手动、webhook 说触发方式;不认识的结构才退回 JSON", () => {
    expect(scheduleText(task({ trigger_type: "manual" }), t, "zh-CN", formatTime)).toBe("手动");
    expect(scheduleText(task({ trigger_type: "webhook" }), t, "zh-CN", formatTime)).toBe("Webhook");
    expect(scheduleText(task({ trigger_type: "cron", schedule: { expr: "* * * * *" } }), t, "zh-CN", formatTime)).toBe(
      '{"expr":"* * * * *"}',
    );
  });
});

describe("下次运行一格", () => {
  it("有时间说时间", () => {
    expect(nextRunText(task({ trigger_type: "daily", next_run_at: "2026-09-29T01:00:00" }), t, formatTime)).toBe("@2026-09-29T01:00:00");
  });

  it("没有时间时分开说:手动、webhook、停用不是一回事", () => {
    expect(nextRunText(task({ trigger_type: "manual" }), t, formatTime)).toBe(messages["zh-CN"].manualNoSchedule);
    expect(nextRunText(task({ trigger_type: "webhook" }), t, formatTime)).toBe(messages["zh-CN"].webhookNoSchedule);
    expect(nextRunText(task({ trigger_type: "interval", schedule: { seconds: 3600 }, enabled: false }), t, formatTime)).toBe(
      messages["zh-CN"].taskPausedNoSchedule,
    );
    expect(nextRunText(task({ trigger_type: "daily", schedule: { time: "09:00" }, enabled: false }), t, formatTime)).not.toBe(
      messages["zh-CN"].manualNoSchedule,
    );
  });
});
