import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, ExternalLink, KeyRound } from "lucide-react";
import { toast } from "sonner";

import {
  finishPluginOauth,
  listPluginCredentials,
  savePluginCredentials,
  startPluginOauth,
  type PluginInstance,
} from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SETTINGS_FIELD_WIDTH, SettingsRow } from "@/components/settings/settings-layout";
import { GroupActions } from "@/features/plugins/GroupActions";
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
 * 连接的**授权**:一行「授权 [状态] —— 去授权 / 重新授权」,下面按需再长出两种行 ——
 * 贴授权码的那一行(点了授权之后),和授权会填的令牌(点了「手动填写」之后)。
 *
 * **它是连接级别的,所以排在连接卡片正文的第一行**;**长相和卡片里其他各项同一套**(设置行:左边
 * 标题和一句说明,右边控件,行间由组画分隔线)。上一版把它做成一只带边框的小卡片嵌在行与行之间,
 * 一张卡片里出现两种版式,读起来像是另一个东西塞了进来。
 *
 * 授权会填的令牌(Refresh Token、Access Token)**归这里管**,不和 AppKey 摆在一起当主输入:
 * 它们本来由授权填,摆在最显眼的位置等于告诉人「这里要手抄」—— 而手抄正是授权要替掉的那一步。
 * 已经有令牌的人点「手动填写」,就在授权这一行下面展开、单独保存。
 *
 * 替用户走完的是 OAuth 里那段机械的部分:拼授权链接、拿 code 换令牌、把令牌存进清单 `stores` 指的
 * 那几格。注册应用拿 AppKey / SecretKey 替代不了,所以那两格仍在下面的凭据里。
 *
 * **为什么还要粘贴一次 code。** 回调不走 mosael://(自定义协议是外部输入面,任何网页都能触发它),
 * 也不在本机开监听端口(重定向地址要在对方控制台预先登记,而后端端口会变)。详见
 * backend/app/domain/plugins/oauth.py 的文件头。多一次粘贴,换这条路上没有可伪造的输入。
 */
export function ConnectionAuthorization({
  instanceId,
  state,
  fields,
}: {
  instanceId: string;
  state: AuthorizationState;
  /** 授权会填的凭据键(清单 `oauth.stores` 指向的),按清单先后。 */
  fields: string[];
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [url, setUrl] = React.useState("");
  const [code, setCode] = React.useState("");
  const [manual, setManual] = React.useState(false);
  const [draft, setDraft] = React.useState<Record<string, string>>({});
  const look = LOOK[state];

  const credentials = useQuery({
    queryKey: ["plugin-credentials", instanceId],
    queryFn: () => listPluginCredentials(instanceId),
    enabled: manual,
  });
  const tokens = (credentials.data ?? []).filter((item) => fields.includes(item.key));

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

  const settled = () => {
    void qc.invalidateQueries({ queryKey: ["plugin-credentials", instanceId] });
    // 连接上的授权状态、「还没授权」都跟着这次写入变,由整份插件列表重新报。
    invalidatePluginDependents(qc);
  };
  const finish = useMutation({
    mutationFn: () => finishPluginOauth(instanceId, code),
    onSuccess: () => {
      setUrl("");
      setCode("");
      toast.success(t("pluginOauthDone"));
      settled();
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const save = useMutation({
    mutationFn: () => savePluginCredentials(instanceId, draft),
    onSuccess: () => {
      setDraft({});
      settled();
    },
  });

  return (
    <>
      <SettingsRow
        label={
          <span data-slot="plugin-authorization" className="inline-flex items-center gap-2">
            {t("pluginAuthTitle")}
            <AuthorizationPill state={state} />
          </span>
        }
        description={t(look.hint)}
      >
        {fields.length > 0 && (
          <Button variant="ghost" className="text-muted-foreground" aria-expanded={manual} onClick={() => setManual((open) => !open)}>
            {manual ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            {t("pluginOauthManual")}
          </Button>
        )}
        <Button variant={look.primary ? "default" : "outline"} loading={begin.isPending} onClick={() => begin.mutate()}>
          <ExternalLink size={13} /> {t(look.action)}
        </Button>
      </SettingsRow>

      {url && (
        <SettingsRow
          label={t("pluginOauthCodeTitle")}
          description={
            <>
              {t("pluginOauthCodeDesc")}{" "}
              {/* 链接留着:弹窗被拦、或者他想换个浏览器登录时,总得有个能点的东西。 */}
              <a
                className="inline-flex items-center gap-1 font-medium text-primary no-underline hover:underline"
                href={url}
                target="_blank"
                rel="noreferrer noopener"
              >
                {t("pluginOauthOpenLink")}
                <ExternalLink size={11} />
              </a>
            </>
          }
        >
          <Input
            className={SETTINGS_FIELD_WIDTH}
            value={code}
            placeholder={t("pluginOauthCodePlaceholder")}
            onChange={(event) => setCode(event.target.value)}
          />
          <Button disabled={!code.trim()} loading={finish.isPending} onClick={() => finish.mutate()}>
            <KeyRound size={13} /> {t("pluginOauthExchange")}
          </Button>
        </SettingsRow>
      )}

      {/* 展开后是一样的设置行,直接排在组里(不包一层):组的分隔线只认行和块这一层。 */}
      {manual &&
        tokens.map((item) => (
          <SettingsRow
            key={item.key}
            label={item.label}
            description={item.filled ? t("pluginCredentialFilled") : t("pluginCredentialEmpty")}
          >
            <Input
              className="w-[240px] max-w-full"
              type={item.secret ? "password" : "text"}
              value={draft[item.key] ?? item.value}
              placeholder={item.key}
              onChange={(event) => setDraft((current) => ({ ...current, [item.key]: event.target.value }))}
            />
          </SettingsRow>
        ))}
      {manual && Object.keys(draft).length > 0 && (
        <GroupActions>
          <Button size="sm" loading={save.isPending} onClick={() => save.mutate()}>
            <KeyRound size={13} /> {t("pluginCredentialsSave")}
          </Button>
        </GroupActions>
      )}
    </>
  );
}
