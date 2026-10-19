import React from "react";

import {
  completeCloudBinding,
  getCloudBinding,
  startCloudBinding,
  unbindCloudBinding,
  type CloudBindingIssued,
  type CloudBindingStatus,
} from "@/api/domains/cloud";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { SettingsBlock } from "@/components/settings/settings-layout";

/**
 * 「绑定 MosaelCloud」—— 桌面端这一期只做一件事:把云端账号绑到**当前本地用户**身上。
 *
 * 它和上面的本地账号是两套：这里显示的是云端邮箱，不是本地用户名。绑定结果存在本地后端
 * (`cloud_bindings`)，云端凭据落盘加密，本地接口只回 `email / device_id`，**从不回 token**。
 */
export function CloudBindingSection() {
  const t = useI18n();
  const [binding, setBinding] = React.useState<CloudBindingStatus | null>(null);
  const [issued, setIssued] = React.useState<CloudBindingIssued | null>(null);
  const [busy, setBusy] = React.useState<"" | "loading" | "starting" | "completing" | "removing">("loading");
  const [notice, setNotice] = React.useState("");

  React.useEffect(() => {
    let alive = true;
    void getCloudBinding()
      .then((found) => {
        if (alive) setBinding(found);
      })
      .catch((error: unknown) => {
        if (alive) setNotice(errorText(error));
      })
      .finally(() => {
        if (alive) setBusy("");
      });
    return () => {
      alive = false;
    };
  }, []);

  const start = async () => {
    setBusy("starting");
    setNotice("");
    try {
      setIssued(await startCloudBinding());
    } catch (error) {
      setNotice(errorText(error));
    } finally {
      setBusy("");
    }
  };

  const complete = async () => {
    if (!issued) return;
    setBusy("completing");
    setNotice("");
    try {
      const result = await completeCloudBinding(issued.device_code);
      if (result.status === "approved") {
        setBinding({ bound: true, email: result.email, device_id: result.device_id });
        setIssued(null);
        setNotice(t("cloudBindingGranted"));
      } else {
        setNotice(t("cloudBindingPending"));
      }
    } catch (error) {
      setNotice(errorText(error));
    } finally {
      setBusy("");
    }
  };

  const unbind = async () => {
    setBusy("removing");
    setNotice("");
    try {
      await unbindCloudBinding();
      setBinding({ bound: false });
      setNotice(t("cloudBindingRemoved"));
    } catch (error) {
      setNotice(errorText(error));
    } finally {
      setBusy("");
    }
  };

  return (
    <SettingsBlock>
      <div className="grid gap-3" data-cloud-binding="">
        <div className="grid gap-1">
          <strong className="text-ui-lg font-semibold leading-snug">{t("cloudBindingTitle")}</strong>
          <small className="text-ui-sm leading-[1.5] text-muted-foreground">{t("cloudBindingIntro")}</small>
        </div>

        {busy === "loading" ? (
          <small className="text-ui-sm text-muted-foreground">{t("cloudBindingChecking")}</small>
        ) : binding?.bound ? (
          <div className="flex min-w-0 flex-wrap items-center gap-3">
            <span className="min-w-0 break-all text-sm">
              {t("cloudBindingBoundTo").replace("{email}", binding.email ?? "")}
            </span>
            <Button variant="outline" size="sm" loading={busy === "removing"} onClick={() => void unbind()}>
              {t("cloudBindingUnbind")}
            </Button>
          </div>
        ) : issued ? (
          <div className="grid gap-2">
            <strong className="text-sm">{t("cloudBindingCodeTitle")}</strong>
            <code className="w-fit rounded-md border border-border bg-muted px-3 py-1.5 font-mono text-base tracking-[0.18em]">
              {issued.user_code}
            </code>
            <small className="text-ui-sm text-muted-foreground">{t("cloudBindingCodeHint")}</small>
            <div className="flex flex-wrap items-center gap-2">
              <a
                href={issued.verification_uri_complete}
                target="_blank"
                rel="noreferrer"
                className="text-sm font-medium text-primary underline-offset-4 hover:underline"
              >
                {t("cloudBindingOpen")}
              </a>
              <Button size="sm" loading={busy === "completing"} onClick={() => void complete()}>
                {t("cloudBindingApproved")}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setIssued(null)}>
                {t("cloudBindingCancel")}
              </Button>
            </div>
          </div>
        ) : (
          <div>
            <Button size="sm" loading={busy === "starting"} onClick={() => void start()}>
              {t("cloudBindingBind")}
            </Button>
          </div>
        )}

        {busy === "starting" && <small className="text-ui-sm text-muted-foreground">{t("cloudBindingStarting")}</small>}
        {busy === "completing" && (
          <small className="text-ui-sm text-muted-foreground">{t("cloudBindingCompleting")}</small>
        )}
        {notice && (
          <small className="text-ui-sm leading-[1.5] text-muted-foreground" role="status">
            {notice}
          </small>
        )}
      </div>
    </SettingsBlock>
  );
}
