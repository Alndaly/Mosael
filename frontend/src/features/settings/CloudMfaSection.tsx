import React from "react";
import QRCode from "qrcode";

import {
  describeCloudFailure,
  disableCloudMfa,
  enableCloudMfa,
  getCloudMfaStatus,
  regenerateCloudMfaRecoveryCodes,
  setupCloudMfa,
  type CloudMfaSetup,
  type CloudMfaStatus,
} from "@/api/domains/cloud";
import { useI18n } from "@/app/preferences";
import { FailureCard } from "@/components/failure/FailureCard";
import { FallbackImage } from "@/components/ui/fallback-image";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SettingsBlock, SettingsField, SettingsForm } from "@/components/settings/settings-layout";

/**
 * 桌面端 MosaelCloud 账号的双因素设置。和官网「安全」分区共用 Cloud 的 /mfa 接口;
 * 开启后登录仍走 CloudAccountSection 的二次验证。
 */
export function CloudMfaSection() {
  const t = useI18n();
  const [status, setStatus] = React.useState<CloudMfaStatus | null>(null);
  const [setup, setSetup] = React.useState<CloudMfaSetup | null>(null);
  const [qr, setQr] = React.useState("");
  const [code, setCode] = React.useState("");
  const [codes, setCodes] = React.useState<string[]>([]);
  const [failure, setFailure] = React.useState("");
  const [busy, setBusy] = React.useState("");
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let alive = true;
    void getCloudMfaStatus()
      .then((next) => {
        if (alive) setStatus(next);
      })
      .catch((error: unknown) => {
        if (alive) setFailure(describeCloudFailure(error).message);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const fail = (error: unknown) => setFailure(describeCloudFailure(error).message);

  const startSetup = async () => {
    setFailure("");
    setBusy("setup");
    try {
      const started = await setupCloudMfa();
      setSetup(started);
      setQr(await QRCode.toDataURL(started.otpauth_uri, { width: 170, margin: 1 }));
    } catch (error) {
      fail(error);
    } finally {
      setBusy("");
    }
  };

  const enable = async () => {
    if (!code.trim()) {
      setFailure(t("settingsCloudMfaCodeRequired"));
      return;
    }
    setFailure("");
    setBusy("enable");
    try {
      const result = await enableCloudMfa(code.trim());
      setCodes(result.recovery_codes);
      setStatus({ enabled: true, recovery_codes_remaining: result.recovery_codes.length });
      setSetup(null);
      setQr("");
      setCode("");
    } catch (error) {
      fail(error);
    } finally {
      setBusy("");
    }
  };

  const disable = async () => {
    if (!code.trim()) {
      setFailure(t("settingsCloudMfaCodeRequired"));
      return;
    }
    setFailure("");
    setBusy("disable");
    try {
      await disableCloudMfa(code.trim());
      setStatus({ enabled: false, recovery_codes_remaining: 0 });
      setCodes([]);
      setCode("");
    } catch (error) {
      fail(error);
    } finally {
      setBusy("");
    }
  };

  const regenerate = async () => {
    if (!code.trim()) {
      setFailure(t("settingsCloudMfaCodeRequired"));
      return;
    }
    setFailure("");
    setBusy("recovery");
    try {
      const result = await regenerateCloudMfaRecoveryCodes(code.trim());
      setCodes(result.recovery_codes);
      setStatus((current) =>
        current ? { ...current, recovery_codes_remaining: result.recovery_codes.length } : current,
      );
      setCode("");
    } catch (error) {
      fail(error);
    } finally {
      setBusy("");
    }
  };

  return (
    <SettingsBlock>
      <div className="grid gap-3">
        <div className="grid gap-1">
          <strong className="text-ui-lg font-semibold leading-snug">{t("settingsCloudMfaTitle")}</strong>
          <small className="text-ui-sm leading-[1.5] text-muted-foreground">{t("settingsCloudMfaDesc")}</small>
        </div>
        {loading ? (
          <small className="text-ui-sm text-muted-foreground">{t("settingsCloudMfaLoading")}</small>
        ) : (
          <>
            {failure && (
              <FailureCard
                size="inline"
                status="failed"
                title={t("settingsCloudMfaTitle")}
                summary={failure}
                copyText={failure}
              />
            )}
            {codes.length > 0 && (
              <div className="grid gap-2 rounded-md border border-border bg-secondary/40 p-3">
                <strong className="text-ui-sm font-medium">{t("settingsCloudMfaRecoveryTitle")}</strong>
                <small className="text-ui-sm leading-[1.5] text-muted-foreground">
                  {t("settingsCloudMfaRecoveryHint")}
                </small>
                <pre className="m-0 overflow-x-auto font-mono text-ui-sm">{codes.join("\n")}</pre>
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    onClick={() => void navigator.clipboard.writeText(codes.join("\n")).catch(() => undefined)}
                  >
                    {t("settingsCloudMfaCopy")}
                  </Button>
                  <Button variant="ghost" onClick={() => setCodes([])}>
                    {t("settingsCloudMfaSaved")}
                  </Button>
                </div>
              </div>
            )}
            {!status?.enabled && !setup && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-ui-sm text-muted-foreground">{t("settingsCloudMfaOff")}</span>
                <Button variant="outline" onClick={() => void startSetup()} loading={busy === "setup"}>
                  {t("settingsCloudMfaEnable")}
                </Button>
              </div>
            )}
            {setup && (
              <div className="grid gap-3">
                <small className="text-ui-sm leading-[1.5] text-muted-foreground">{t("settingsCloudMfaScan")}</small>
                {qr && (
                  <FallbackImage
                    src={qr}
                    alt={t("settingsCloudMfaQrAlt")}
                    width={170}
                    height={170}
                    className="rounded-md"
                  />
                )}
                <small className="text-ui-sm leading-[1.5] text-muted-foreground">
                  {t("settingsCloudMfaSecret")}
                </small>
                <code className="font-mono text-ui-sm [overflow-wrap:anywhere]">{setup.secret}</code>
                <SettingsForm>
                  <SettingsField label={t("settingsCloudMfaSetupCode")}>
                    <Input
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      value={code}
                      onChange={(event) => setCode(event.target.value)}
                    />
                  </SettingsField>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <Button
                      variant="outline"
                      onClick={() => {
                        setSetup(null);
                        setQr("");
                        setCode("");
                        setFailure("");
                      }}
                    >
                      {t("settingsCloudMfaCancel")}
                    </Button>
                    <Button onClick={() => void enable()} loading={busy === "enable"}>
                      {t("settingsCloudMfaConfirm")}
                    </Button>
                  </div>
                </SettingsForm>
              </div>
            )}
            {status?.enabled && (
              <div className="grid gap-3 border-t border-border pt-4">
                <small className="text-ui-sm text-muted-foreground">
                  {t("settingsCloudMfaRemaining").replace("{count}", String(status.recovery_codes_remaining))}
                </small>
                <SettingsField label={t("settingsCloudMfaSetupCode")}>
                  <Input
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    value={code}
                    onChange={(event) => setCode(event.target.value)}
                  />
                </SettingsField>
                <div className="flex flex-wrap gap-2">
                  <Button variant="outline" onClick={() => void regenerate()} loading={busy === "recovery"}>
                    {t("settingsCloudMfaRegenerate")}
                  </Button>
                  <Button variant="outline" onClick={() => void disable()} loading={busy === "disable"}>
                    {t("settingsCloudMfaDisable")}
                  </Button>
                </div>
                <small className="text-ui-sm leading-[1.5] text-muted-foreground">
                  {t("settingsCloudMfaDisableHint")}
                </small>
              </div>
            )}
          </>
        )}
      </div>
    </SettingsBlock>
  );
}
