import { Copy, Globe, MonitorSmartphone } from "lucide-react";
import { toast } from "sonner";

import { useI18n } from "@/app/preferences";
import { IconButton } from "@/components/ui/icon-button";
import { inviteLinkUrls } from "@/lib/inviteLinks";

/**
 * 刚发出去的那张邀请链接(ADR 0054):网页地址和桌面端深链各一行,各自能复制。**只在这一次看得到** —— 库里只有哈希,
 * 列表里认它靠末尾几位。网页地址在部署配了网页地址(或这个界面本身是网页版)时才有,桌面单机只有深链(D52)。
 */
export function InviteLinkReveal({ code, webUrl }: { code: string; webUrl: string }) {
  const t = useI18n();
  const urls = inviteLinkUrls(code, webUrl);
  const copy = (value: string) => {
    void navigator.clipboard?.writeText(value);
    toast.success(t("inviteLinkCopied"));
  };
  const rows = [
    ...(urls.web ? [{ key: "web", icon: <Globe size={13} />, label: t("inviteLinkWeb"), value: urls.web }] : []),
    { key: "app", icon: <MonitorSmartphone size={13} />, label: t("inviteLinkApp"), value: urls.app },
  ];
  return (
    <div data-invite-link-reveal="" className="grid gap-2">
      {rows.map((row) => (
        <div key={row.key} className="grid gap-1">
          <span className="flex items-center gap-1.5 text-ui-xs text-muted-foreground">
            {row.icon} {row.label}
          </span>
          <div className="flex min-w-0 items-center gap-1.5 rounded-md border border-border bg-field py-1 pl-2.5 pr-1">
            <code data-invite-link={row.key} className="timecode min-w-0 flex-1 select-all break-all text-ui-xs">
              {row.value}
            </code>
            <IconButton label={t("inviteLinkCopy")} onClick={() => copy(row.value)}>
              <Copy />
            </IconButton>
          </div>
        </div>
      ))}
      <p className="m-0 text-ui-xs leading-[1.6] text-muted-foreground">
        {urls.web ? t("inviteLinkOnceNote") : t("inviteLinkOnceNoteAppOnly")}
      </p>
    </div>
  );
}
