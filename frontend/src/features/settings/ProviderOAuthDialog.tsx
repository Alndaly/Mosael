/**
 * 订阅计划的授权登录弹窗(设备码 / 浏览器授权)。
 *
 * 授权流程各家不同,但界面不为任何一家写死:后端把 pi 的 AuthEvent **原样**送上来,这里按
 * 事件类型渲染(授权链接、设备码、进度、提示),要用户作答时再按 prompt 类型渲染一个输入。
 * 上游新增一种事件时,最差也只是多一条纯文本,而不是一片空白。
 */
import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, ExternalLink, Loader2 } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ModalShell } from "@/components/app/modals";

type LoginState = components["schemas"]["OAuthLoginOut"];

/** 授权要等用户去浏览器操作,轮询得足够勤才不会让「已经点完了」还转圈。 */
const POLL_MS = 1000;

function EventLine({ event }: { event: Record<string, unknown> }) {
  const t = useI18n();
  const [copied, setCopied] = React.useState(false);
  const type = String(event.type ?? "");

  if (type === "device_code") {
    const code = String(event.userCode ?? "");
    const uri = String(event.verificationUri ?? "");
    return (
      <div className="grid gap-1.5 rounded-md border border-border bg-panel p-2.5">
        <span className="text-[11.5px] text-muted-foreground">{t("providerOauthDeviceCode")}</span>
        <div className="flex items-center gap-1.5">
          <code className="flex-1 rounded bg-field px-2 py-1 text-[15px] font-semibold tracking-[0.18em] text-foreground">
            {code}
          </code>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              void navigator.clipboard.writeText(code);
              setCopied(true);
              setTimeout(() => setCopied(false), 1600);
            }}
          >
            {copied ? <Check size={12} /> : <Copy size={12} />}
            {copied ? t("providerOauthCopied") : t("providerOauthCopyCode")}
          </Button>
        </div>
        {uri && (
          <a
            className="inline-flex w-fit items-center gap-1 text-[11.5px] font-medium text-primary no-underline hover:underline"
            href={uri}
            target="_blank"
            rel="noreferrer noopener"
          >
            {t("providerOauthOpenLink")}
            <ExternalLink size={11} />
          </a>
        )}
      </div>
    );
  }

  if (type === "auth_url") {
    const url = String(event.url ?? "");
    return (
      <div className="grid gap-1.5 rounded-md border border-border bg-panel p-2.5">
        {typeof event.instructions === "string" && (
          <span className="text-[11.5px] leading-[1.5] text-muted-foreground">{event.instructions}</span>
        )}
        <a
          className="inline-flex w-fit items-center gap-1 text-[11.5px] font-medium text-primary no-underline hover:underline"
          href={url}
          target="_blank"
          rel="noreferrer noopener"
        >
          {t("providerOauthOpenLink")}
          <ExternalLink size={11} />
        </a>
      </div>
    );
  }

  // progress / info / 上游新增的类型:退回纯文本,总比空白强。
  const message = typeof event.message === "string" ? event.message : JSON.stringify(event);
  return <p className="m-0 text-[11.5px] leading-[1.5] text-muted-foreground">{message}</p>;
}

type Prompt = NonNullable<LoginState["prompt"]>;

/**
 * 一步提问的输入区。
 *
 * 抽出来是因为它漏过一次:select 类型(如 Codex 的「浏览器授权 / 设备码」)和文本类型
 * 共用了一个输入框,用户看到的是一个**空框**,得凭空猜出 "browser" 这个 id 才能往下走。
 * 单独成组件才测得到。
 */
export function AuthPromptField({
  prompt,
  pending,
  submitLabel,
  onSubmit,
}: {
  prompt: Prompt;
  pending?: boolean;
  submitLabel: string;
  onSubmit: (value: string) => void;
}) {
  const [answer, setAnswer] = React.useState("");

  return (
    <div className="grid gap-1.5">
      <span className="text-[11.5px] text-foreground">{prompt.message}</span>
      {prompt.prompt_type === "select" ? (
        // 提交的是选项 id,不是它的显示文案。
        <div className="grid gap-1">
          {(prompt.options ?? []).map((option) => {
            const row = option as Record<string, unknown>;
            const id = String(row.id ?? "");
            const label = String(row.label ?? id);
            const description = typeof row.description === "string" ? row.description : "";
            return (
              <Button
                key={id}
                type="button"
                variant="outline"
                size="sm"
                className="h-auto justify-start py-1.5 text-left"
                disabled={pending}
                onClick={() => onSubmit(id)}
              >
                <span className="grid gap-px">
                  <span className="text-[12px] font-medium">{label}</span>
                  {description && <span className="text-[10.5px] font-normal text-muted-foreground">{description}</span>}
                </span>
              </Button>
            );
          })}
        </div>
      ) : (
        <div className="flex items-center gap-1.5">
          <Input
            autoFocus
            type={prompt.prompt_type === "secret" ? "password" : "text"}
            placeholder={prompt.placeholder || ""}
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && answer.trim()) onSubmit(answer.trim());
            }}
          />
          <Button type="button" size="sm" disabled={!answer.trim() || pending} onClick={() => onSubmit(answer.trim())}>
            {submitLabel}
          </Button>
        </div>
      )}
    </div>
  );
}

export function ProviderOAuthDialog({
  profileId,
  profileName,
  open,
  onOpenChange,
}: {
  profileId: string;
  profileName: string;
  open: boolean;
  onOpenChange: (next: boolean) => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [loginId, setLoginId] = React.useState<string | null>(null);
  const [answer, setAnswer] = React.useState("");

  const start = useMutation({
    mutationFn: () => api<LoginState>(`/api/settings/providers/${profileId}/oauth/login`, { method: "POST" }),
    onSuccess: (state) => setLoginId(state.login_id),
  });

  // 打开即发起:用户点的是「授权登录」,再让他在弹窗里点一次同样的按钮没有意义。
  React.useEffect(() => {
    if (open && !loginId && !start.isPending) start.mutate();
    if (!open) {
      setLoginId(null);
      setAnswer("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const state = useQuery({
    queryKey: ["provider-oauth-login", profileId, loginId],
    queryFn: () => api<LoginState>(`/api/settings/providers/${profileId}/oauth/login/${loginId}`),
    enabled: open && Boolean(loginId),
    refetchInterval: (query) => (query.state.data?.status === "running" ? POLL_MS : false),
  });

  const submitAnswer = useMutation({
    mutationFn: (value: string) =>
      api<LoginState>(`/api/settings/providers/${profileId}/oauth/login/${loginId}/answer`, {
        method: "POST",
        body: JSON.stringify({ prompt_id: state.data?.prompt?.prompt_id ?? "", answer: value }),
      }),
    onSuccess: () => {
      setAnswer("");
      void state.refetch();
    },
  });

  const close = () => {
    // 关掉弹窗就放弃这次授权 —— 否则会留下一个最长等 15 分钟的进程。
    if (loginId && state.data?.status === "running") {
      void api(`/api/settings/providers/${profileId}/oauth/login/${loginId}`, { method: "DELETE" }).catch(() => undefined);
    }
    void qc.invalidateQueries({ queryKey: ["provider-profiles"] });
    void qc.invalidateQueries({ queryKey: ["provider-models", profileId] });
    onOpenChange(false);
  };

  const status = state.data?.status ?? "running";
  const prompt = state.data?.prompt ?? null;

  return (
    <ModalShell open={open} onOpenChange={(next) => !next && close()} title={`${t("providerOauthTitle")} · ${profileName}`}>
      <div className="grid gap-2.5">
        <p className="m-0 text-[11.5px] leading-[1.5] text-muted-foreground">{t("providerOauthHint")}</p>

        {(state.data?.events ?? []).map((event, index) => (
          <EventLine key={index} event={event as Record<string, unknown>} />
        ))}

        {prompt && status === "running" && (
          <AuthPromptField
            prompt={prompt}
            pending={submitAnswer.isPending}
            submitLabel={t("providerOauthSubmit")}
            onSubmit={(value) => submitAnswer.mutate(value)}
          />
        )}

        {status === "running" && !prompt && (
          <p className="m-0 flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
            <Loader2 size={12} className="animate-spin" />
            {t("providerOauthWaiting")}
          </p>
        )}

        {status === "done" && (
          <p className="m-0 text-[11.5px] font-medium text-primary">
            {t("providerOauthDone").replace("{count}", String(state.data?.models?.length ?? 0))}
          </p>
        )}
        {(status === "error" || status === "cancelled") && (
          <p className="m-0 text-[11.5px] text-destructive">
            {t("providerOauthFailed")}
            {state.data?.error ? `:${state.data.error}` : ""}
          </p>
        )}

        <div className="mt-1 flex justify-end">
          <Button type="button" variant={status === "done" ? "default" : "outline"} size="sm" onClick={close}>
            {status === "done" ? t("close") : t("cancel")}
          </Button>
        </div>
      </div>
    </ModalShell>
  );
}
