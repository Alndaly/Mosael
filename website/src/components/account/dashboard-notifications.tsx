import { Bell } from "lucide-react";

import type { Messages } from "@/i18n/messages";

/**
 * 通知:**只有空态**。
 *
 * 云端的通知接口还没有(那是下一步的事),所以这里不拉任何数据、不画假条目、也不写「即将
 * 上线」—— 只把「以后什么会出现在这里」说清楚。接口有了之后再在这一块接上,空态就是它
 * 天然的零条分支。
 */
export function DashboardNotifications({ copy }: { copy: Messages["dashboard"] }) {
  return (
    <div className="rounded-3xl border border-dashed border-border bg-card px-6 py-16 text-center">
      <span className="inline-flex size-12 items-center justify-center rounded-2xl bg-secondary text-muted-foreground">
        <Bell className="size-5" aria-hidden />
      </span>
      <p className="mx-auto mt-4 mb-0 max-w-[34ch] text-sm leading-7 text-muted-foreground">{copy.notificationsEmpty}</p>
    </div>
  );
}
