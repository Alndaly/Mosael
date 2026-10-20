import React from "react";
import { Check, Copy, ExternalLink } from "lucide-react";

import {
  completeCloudBinding,
  describeCloudBindingFailure,
  getCloudBinding,
  startCloudBinding,
  unbindCloudBinding,
  type CloudBindingFailure,
  type CloudBindingIssued,
  type CloudBindingStatus,
} from "@/api/domains/cloud";
import { useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { SettingsBlock } from "@/components/settings/settings-layout";
import { parseServerTime } from "@/lib/time";

/**
 * 设置 → 账户里的「MosaelCloud 账号」。
 *
 * **为什么这里只能走设备码。** 云端的登录态是一枚第一方 `HttpOnly` cookie
 *(`mosael_cloud_session`,Path=/api/cloud/v1):它只属于浏览器里的官网 Origin,桌面窗口里没有它。
 * 所以软件内拿不到「邮箱 + 密码 → 云端会话」这条捷径 —— 那只能是一个假登录。这里照设备码走:
 * 本地后端向云端要一枚 `user_code`,用户在**浏览器**里(可以用密码 / 验证码 / GitHub / Google)确认,
 * 回来点「我已确认」,本地后端拿 `device_code` 换凭据并落盘。渲染层从头到尾看不到 token。
 *
 * **绑没绑、绑了谁只有一个来源**:`GET /api/cloud/binding`。完成与解绑之后都重读它,不拿
 * `complete` 的回包或本地猜测当状态 —— 否则云端那边撤销了,软件里还显示「已登录」。
 *
 * 解绑的真实语义是**只删本地这一行**:浏览器里的云端会话、云端那台设备都不动;要撤销云端设备
 * 得到官网账号页。界面上照这个语义写,不把「解除本机绑定」说成「云端也退出了」。
 */
export function CloudBindingSection() {
  const t = useI18n();
  const { locale } = usePreferences();
  const [binding, setBinding] = React.useState<CloudBindingStatus | null>(null);
  const [issued, setIssued] = React.useState<CloudBindingIssued | null>(null);
  const [busy, setBusy] = React.useState<"" | "loading" | "starting" | "completing" | "removing">("loading");
  const [notice, setNotice] = React.useState("");
  const [pending, setPending] = React.useState(false);
  const [failure, setFailure] = React.useState<CloudBindingFailure | null>(null);
  const [readFailure, setReadFailure] = React.useState<CloudBindingFailure | null>(null);
  const [copied, setCopied] = React.useState(false);

  React.useEffect(() => {
    let alive = true;
    void getCloudBinding()
      .then((found) => {
        if (!alive) return;
        setBinding(found);
        setReadFailure(null);
      })
      .catch((error: unknown) => {
        if (alive) setReadFailure(describeCloudBindingFailure(error));
      })
      .finally(() => {
        if (alive) setBusy("");
      });
    return () => {
      alive = false;
    };
  }, []);

  /** 重新问一次后端。完成 / 解绑之后都走它,不拿回包或本地状态冒充结果。 */
  const readStatus = async (): Promise<CloudBindingStatus | null> => {
    try {
      const found = await getCloudBinding();
      setBinding(found);
      setReadFailure(null);
      return found;
    } catch (error) {
      setReadFailure(describeCloudBindingFailure(error));
      return null;
    }
  };

  const refresh = async () => {
    setBusy("loading");
    setReadFailure(null);
    await readStatus();
    setBusy("");
  };

  const start = async () => {
    setBusy("starting");
    setNotice("");
    setPending(false);
    setFailure(null);
    setCopied(false);
    try {
      setIssued(await startCloudBinding());
    } catch (error) {
      setFailure(describeCloudBindingFailure(error));
    } finally {
      setBusy("");
    }
  };

  const complete = async () => {
    if (!issued) return;
    setBusy("completing");
    setNotice("");
    setPending(false);
    setFailure(null);
    try {
      const result = await completeCloudBinding(issued.device_code);
      if (result.status === "approved") {
        //: 不拿 result 里的 email/device_id 直接拼一个「已绑定」:那只是这次回包,不是当前状态。
        //: 重读期间先留着确认码那一块(它显示「正在向 MosaelCloud 确认…」),别闪一下「登录」。
        const refreshed = await readStatus();
        setIssued(null);
        if (refreshed?.bound) setNotice(t("cloudBindingGranted"));
      } else {
        setPending(true);
      }
    } catch (error) {
      setFailure(describeCloudBindingFailure(error));
    } finally {
      setBusy("");
    }
  };

  const unbind = async () => {
    setBusy("removing");
    setNotice("");
    setFailure(null);
    try {
      await unbindCloudBinding();
      const refreshed = await readStatus();
      if (refreshed && !refreshed.bound) setNotice(t("cloudBindingRemoved"));
    } catch (error) {
      setFailure(describeCloudBindingFailure(error));
    } finally {
      setBusy("");
    }
  };

  const copyCode = async () => {
    if (!issued) return;
    try {
      await navigator.clipboard.writeText(issued.user_code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      // 没有剪贴板权限时确认码还在页面上,可以手动选中;不谎报「已复制」。
    }
  };

  const cancel = () => {
    setIssued(null);
    setPending(false);
    setFailure(null);
    setNotice("");
    setCopied(false);
  };

  const expiredCode = failure?.code === "device_code_expired" || failure?.code === "device_code_used";

  return (
    <SettingsBlock>
      <div className="grid gap-3" data-cloud-binding="">
        <div className="grid gap-1">
          <strong className="text-ui-lg font-semibold leading-snug">{t("cloudBindingTitle")}</strong>
          <small className="text-ui-sm leading-[1.5] text-muted-foreground">{t("cloudBindingIntro")}</small>
          <small className="text-ui-sm leading-[1.5] text-muted-foreground">{t("cloudBindingOauthNote")}</small>
        </div>

        {busy === "loading" && !binding && !readFailure && (
          <small className="text-ui-sm text-muted-foreground" role="status">
            {t("cloudBindingChecking")}
          </small>
        )}

        {readFailure && (
          <div className="grid gap-2" data-cloud-binding-read-failure="">
            <FailureLine failure={readFailure} />
            <div>
              <Button variant="outline" size="sm" loading={busy === "loading"} onClick={() => void refresh()}>
                {t("cloudBindingRetry")}
              </Button>
            </div>
          </div>
        )}

        {binding?.bound ? (
          <div className="grid gap-2" data-cloud-binding-bound="">
            <div className="grid gap-1">
              <span className="min-w-0 break-all text-sm">
                {t("cloudBindingBoundTo").replace("{email}", binding.email ?? "")}
              </span>
              {binding.created_at && (
                <small className="text-ui-sm leading-[1.5] text-muted-foreground">
                  {t("cloudBindingBoundSince").replace("{time}", boundAt(binding.created_at, locale))}
                </small>
              )}
              {/* 本地后端只有当前这一条绑定,没有 /devices 可列;云端设备列表在官网账号页。 */}
              <small className="text-ui-sm leading-[1.5] text-muted-foreground">{t("cloudBindingBoundDevice")}</small>
              <small className="text-ui-sm leading-[1.5] text-muted-foreground">
                {t("cloudBindingBoundDeviceHint")}
              </small>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="outline" size="sm" loading={busy === "removing"} onClick={() => void unbind()}>
                {t("cloudBindingUnbind")}
              </Button>
            </div>
            <small className="text-ui-sm leading-[1.5] text-muted-foreground">{t("cloudBindingUnbindHint")}</small>
            {failure && <FailureLine failure={failure} />}
            {notice && (
              <small className="text-ui-sm leading-[1.5] text-muted-foreground" role="status">
                {notice}
              </small>
            )}
          </div>
        ) : issued ? (
          <div className="grid gap-2" data-cloud-binding-device-code="">
            <strong className="text-sm">{t("cloudBindingCodeTitle")}</strong>
            <div className="flex flex-wrap items-center gap-2">
              <code
                data-cloud-binding-user-code=""
                className="w-fit rounded-md border border-border bg-muted px-3 py-1.5 font-mono text-2xl font-semibold tracking-[0.22em]"
              >
                {issued.user_code}
              </code>
              <Button variant="outline" size="sm" onClick={() => void copyCode()}>
                {copied ? <Check size={12} /> : <Copy size={12} />}
                {copied ? t("cloudBindingCopied") : t("cloudBindingCopyCode")}
              </Button>
            </div>
            <small className="text-ui-sm leading-[1.5] text-muted-foreground">{t("cloudBindingCodeHint")}</small>
            <div className="flex flex-wrap items-center gap-2">
              <Button asChild variant="outline" size="sm">
                <a href={issued.verification_uri_complete} target="_blank" rel="noreferrer noopener">
                  {t("cloudBindingOpen")}
                  <ExternalLink size={12} />
                </a>
              </Button>
              {!expiredCode && (
                <Button size="sm" loading={busy === "completing"} onClick={() => void complete()}>
                  {t("cloudBindingApproved")}
                </Button>
              )}
              <Button variant="ghost" size="sm" onClick={cancel}>
                {t("cloudBindingCancel")}
              </Button>
            </div>
            {busy === "completing" ? (
              <small className="text-ui-sm leading-[1.5] text-muted-foreground" role="status">
                {t("cloudBindingCompleting")}
              </small>
            ) : failure ? (
              <FailureLine
                failure={failure}
                onRestart={() => {
                  setIssued(null);
                  void start();
                }}
              />
            ) : pending ? (
              <small className="text-ui-sm leading-[1.5] text-muted-foreground" role="status">
                {t("cloudBindingPending")}
              </small>
            ) : (
              <small className="text-ui-sm leading-[1.5] text-muted-foreground" role="status">
                {t("cloudBindingWaiting")}
              </small>
            )}
          </div>
        ) : (
          <div className="grid gap-2">
            <div>
              <Button size="sm" loading={busy === "starting"} onClick={() => void start()}>
                {t("cloudBindingBind")}
              </Button>
            </div>
            {busy === "starting" && (
              <small className="text-ui-sm leading-[1.5] text-muted-foreground" role="status">
                {t("cloudBindingStarting")}
              </small>
            )}
            {failure && <FailureLine failure={failure} />}
            {notice && (
              <small className="text-ui-sm leading-[1.5] text-muted-foreground" role="status">
                {notice}
              </small>
            )}
          </div>
        )}
      </div>
    </SettingsBlock>
  );
}

/**
 * 时间按**这台机器**的时区显示。后端给的是 UTC 的无时区串,必须经 `parseServerTime`。
 * 解析不出来时退回原串,总比「Invalid Date」强。
 */
function boundAt(iso: string, locale: string): string {
  const date = parseServerTime(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" });
}

/**
 * 一次失败的那几行。**只有这里决定「连不上」和「过期」怎么说话**:
 * - 连不上 →「连不上 MosaelCloud」,不把 `cloud_unreachable` 这种机器词甩给用户;
 * - 过期 / 已用 → 一句人话 + **原样**的错误码(用户拿它去搜、去报问题都对得上);
 * - 其余 → 后端那句原文 + 错误码。
 */
function FailureLine({ failure, onRestart }: { failure: CloudBindingFailure; onRestart?: () => void }) {
  const t = useI18n();
  const sentence = failure.unreachable
    ? t("cloudBindingUnreachable")
    : failure.notConfigured
      ? t("cloudBindingNotConfigured")
      : failure.code === "device_code_expired" || failure.code === "device_code_used"
        ? t("cloudBindingExpired")
        : failure.code === "cloud_already_bound"
          ? t("cloudBindingAlreadyBound")
          : failure.message;

  return (
    <div className="grid gap-1" role="alert" data-cloud-binding-failure={failure.code ?? undefined}>
      <small className="text-ui-sm leading-[1.5] text-muted-foreground">{sentence}</small>
      {failure.code && !failure.unreachable && (
        <small className="text-ui-xs leading-[1.5] text-muted-foreground">
          {t("cloudBindingErrorCode").replace("{code}", failure.code)}
        </small>
      )}
      {onRestart && (
        <div className="pt-1">
          <Button variant="outline" size="sm" onClick={onRestart}>
            {t("cloudBindingRestart")}
          </Button>
        </div>
      )}
    </div>
  );
}
