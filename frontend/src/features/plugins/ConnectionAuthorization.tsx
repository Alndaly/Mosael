import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, KeyRound } from "lucide-react";
import { toast } from "sonner";

import { finishPluginOauth, startPluginOauth, type PluginInstance } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { invalidatePluginDependents } from "@/features/plugins/pluginCaches";
import { cn } from "@/lib/utils";

type AuthorizationState = Exclude<PluginInstance["authorization"], "" | undefined>;

/**
 * 每一种授权状态在界面上的样子。状态由后端算(见 backend domain/plugins/oauth.authorization_state):
 * 授权会写的那几格填没填、插件上一次有没有说「对方不认了」。这里不再推一遍。
 *
 * 药丸的色调和工具行上的「需确认」同一套(`bg-<色>/15 text-<色>`),深浅两套主题都由色板 token 管。
 */
const LOOK: Record<AuthorizationState, { label: MessageKey; hint: MessageKey; tone: string; action: MessageKey; primary: boolean }> = {
  unauthorized: {
    label: "pluginAuthUnauthorized",
    hint: "pluginAuthHintUnauthorized",
    tone: "bg-secondary text-muted-foreground",
    action: "pluginOauthStart",
    primary: true,
  },
  authorized: {
    label: "pluginAuthAuthorized",
    hint: "pluginAuthHintAuthorized",
    tone: "bg-success/15 text-success",
    action: "pluginOauthRestart",
    primary: false,
  },
  rejected: {
    label: "pluginAuthRejected",
    hint: "pluginAuthHintRejected",
    tone: "bg-warning/15 text-warning",
    action: "pluginOauthRestart",
    primary: true,
  },
};

export function AuthorizationPill({ state }: { state: AuthorizationState }) {
  const t = useI18n();
  return (
    <small
      data-slot="plugin-authorization-state"
      data-state={state}
      className={cn("whitespace-nowrap rounded-full px-1.5 py-px text-ui-2xs font-medium", LOOK[state].tone)}
    >
      {t(LOOK[state].label)}
    </small>
  );
}

/**
 * 连接的**授权**那一条:状态 + 一句话 + 「去授权 / 重新授权」,点了之后在同一条里贴授权码。
 *
 * **它是连接级别的,所以摆在连接卡片的抬头正下方**,不是凭据那组的末尾。授权写的是**这个连接**的
 * 令牌、决定的是这个连接能不能用 —— 此前它是凭据组最后一行里的一颗按钮,排在 Access Token 下面,
 * 读起来像「Access Token 的一个附属操作」,而且看不出这个连接到底授权过没有。
 *
 * 替用户走完的是 OAuth 里那段机械的部分:拼授权链接、拿 code 换令牌、把令牌存进清单 `stores` 指的
 * 那几格。注册应用拿 AppKey / SecretKey 替代不了,所以那两格仍在下面的凭据里。
 *
 * **为什么还要粘贴一次 code。** 回调不走 mosael://(自定义协议是外部输入面,任何网页都能触发它),
 * 也不在本机开监听端口(重定向地址要在对方控制台预先登记,而后端端口会变)。详见
 * backend/app/domain/plugins/oauth.py 的文件头。多一次粘贴,换这条路上没有可伪造的输入。
 */
export function ConnectionAuthorization({ instanceId, state }: { instanceId: string; state: AuthorizationState }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [url, setUrl] = React.useState("");
  const [code, setCode] = React.useState("");
  const look = LOOK[state];

  const begin = useMutation({
    mutationFn: () => startPluginOauth(instanceId),
    onSuccess: (data) => {
      setUrl(data.authorize_url);
      // 直接开出去 —— 主进程把 http(s) 交给系统浏览器(见 electron/main 的 setWindowOpenHandler)。
      window.open(data.authorize_url, "_blank", "noreferrer");
    },
    // 「先填 AppKey」这类原因由后端说,原样转出来:换成"授权失败"等于把唯一有用的信息扔掉。
    onError: (error: Error) => toast.error(error.message),
  });

  const finish = useMutation({
    mutationFn: () => finishPluginOauth(instanceId, code),
    onSuccess: () => {
      setUrl("");
      setCode("");
      toast.success(t("pluginOauthDone"));
      void qc.invalidateQueries({ queryKey: ["plugin-credentials", instanceId] });
      // 连接上的授权状态、「缺少凭据」都跟着这次写入变,由整份插件列表重新报。
      invalidatePluginDependents(qc);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    // 排在组的正文里,所以要守组的契约(只放行和块,分隔线由组画):它就是一个块,内距和行同一刻度。
    <div data-slot="plugin-authorization" className="px-0.5 py-4">
      <div className="grid gap-3 rounded-lg border border-border bg-panel px-4 py-3">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <KeyRound size={14} className="shrink-0 text-muted-foreground" aria-hidden />
          <span className="text-ui-md font-medium">{t("pluginAuthTitle")}</span>
          <AuthorizationPill state={state} />
          {/* 说明先缩、按钮不掉行:min-w-0 + flex-1。basis 给它一个起码的宽度,窄了再整句换到下一行。 */}
          <small className="min-w-0 flex-1 basis-56 text-ui-sm leading-[1.5] text-muted-foreground">{t(look.hint)}</small>
          <Button
            size="sm"
            variant={look.primary ? "default" : "outline"}
            loading={begin.isPending}
            onClick={() => begin.mutate()}
          >
            <ExternalLink size={13} /> {t(look.action)}
          </Button>
        </div>
        {url && (
          <div className="grid gap-2 border-t border-divider pt-3">
            {/* 链接留着:弹窗被拦、或者他想换个浏览器登录时,总得有个能点的东西。 */}
            <a
              className="inline-flex w-fit items-center gap-1 text-ui-xs font-medium text-primary no-underline hover:underline"
              href={url}
              target="_blank"
              rel="noreferrer noopener"
            >
              {t("pluginOauthOpenLink")}
              <ExternalLink size={11} />
            </a>
            {/* 和上面那颗按钮同一档(sm):一条窄面板里的一行,不是表单底部。 */}
            <div className="flex items-center gap-2">
              <Input
                size="sm"
                className="min-w-0 flex-1"
                value={code}
                placeholder={t("pluginOauthCodePlaceholder")}
                onChange={(event) => setCode(event.target.value)}
              />
              <Button size="sm" disabled={!code.trim()} loading={finish.isPending} onClick={() => finish.mutate()}>
                <KeyRound size={13} /> {t("pluginOauthExchange")}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
