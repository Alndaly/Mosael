import React from "react";
import { Loader2, Server } from "lucide-react";

import { API_BASE, DEFAULT_API_BASE, isCustomServer, setServerUrl } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** 后端服务器入口(本地/团队)。必须先于登录:hasUsers 探测与 login 都打向 API_BASE,
 *  而 API_BASE 在模块加载时从 localStorage 解析一次——切服务器 = 写 localStorage + 整页重载
 *  让它重新解析(会话随之失效,落回登录页)。登录页和设置页复用同一组件。 */
export function ServerPicker() {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const [mode, setMode] = React.useState<"local" | "remote">(isCustomServer() ? "remote" : "local");
  const [url, setUrl] = React.useState(isCustomServer() ? API_BASE : "");
  const [testing, setTesting] = React.useState(false);
  const [failed, setFailed] = React.useState<string | null>(null);

  const currentLabel = isCustomServer() ? safeHost(API_BASE) : t("serverLocal");

  const apply = async (force: boolean) => {
    // 本地:清覆盖回默认;远程:探活通过(或强连)才写入。
    if (mode === "local") {
      setServerUrl(null);
      window.location.reload();
      return;
    }
    const target = url.trim().replace(/\/+$/, "");
    if (!/^https?:\/\/.+/i.test(target)) {
      setFailed(t("serverBadUrl"));
      return;
    }
    if (!force) {
      setTesting(true);
      setFailed(null);
      try {
        const res = await fetch(`${target}/api/health`, { signal: AbortSignal.timeout(4000) });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
      } catch (error) {
        setTesting(false);
        setFailed(error instanceof Error ? error.message : String(error));
        return; // 探不通:不盲切,给「仍要连接」兜底
      }
    }
    setServerUrl(target);
    window.location.reload();
  };

  if (!open) {
    return (
      <button type="button" className="inline-flex cursor-pointer items-center gap-[5px] border-0 bg-transparent p-0 text-xs text-muted-foreground transition-colors duration-100 hover:text-foreground [&_strong]:font-semibold [&_strong]:text-foreground" onClick={() => setOpen(true)}>
        <Server size={13} />
        {t("serverLabel")}
        <strong>{currentLabel}</strong>
        <span className="opacity-50">·</span>
        {t("serverSwitchShort")}
      </button>
    );
  }

  return (
    <div className="flex w-full flex-col gap-2.5 text-left [&_input]:w-full">
      <div className="seg h-[30px] w-full [&_.seg-btn]:flex-1 [&_.seg-btn]:justify-center">
        <button
          type="button"
          className={mode === "local" ? "seg-btn active" : "seg-btn"}
          onClick={() => {
            setMode("local");
            setFailed(null);
          }}
        >
          {t("serverModeLocal")}
        </button>
        <button
          type="button"
          className={mode === "remote" ? "seg-btn active" : "seg-btn"}
          onClick={() => {
            setMode("remote");
            setFailed(null);
          }}
        >
          {t("serverModeTeam")}
        </button>
      </div>
      {mode === "remote" && (
        <Input
          value={url}
          placeholder="https://team.example.com"
          onChange={(event) => {
            setUrl(event.target.value);
            setFailed(null);
          }}
        />
      )}
      {failed && (
        <p className="m-0 text-[11px] text-destructive">
          {t("serverTestFailed")}
          {failed ? ` — ${failed}` : ""}
        </p>
      )}
      <div className="flex items-center gap-1.5">
        <Button
          size="sm"
          variant="secondary"
          className="flex-1"
          disabled={testing || (mode === "remote" && !url.trim())}
          onClick={() => void apply(false)}
        >
          {testing ? <Loader2 size={13} className="spin" /> : null}{" "}
          {mode === "local" ? t("serverConnectLocal") : t("serverConnect")}
        </Button>
        {failed && mode === "remote" && (
          <Button size="sm" variant="outline" onClick={() => void apply(true)}>
            {t("serverForceConnect")}
          </Button>
        )}
        <Button size="sm" variant="ghost" disabled={testing} onClick={() => setOpen(false)}>
          {t("cancel")}
        </Button>
      </div>
      <p className="m-0 text-[11px] leading-normal text-muted-foreground">{t("serverPickerHint")}</p>
    </div>
  );
}

function safeHost(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url === DEFAULT_API_BASE ? url : url;
  }
}
