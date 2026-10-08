import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Settings2 } from "lucide-react";

import { listCapabilityModels, listProviderDefaults, listProviderProfiles } from "@/api/client";
import { providerKeys } from "@/api/queryKeys";
import { useEffectiveChatModel } from "@/features/agent/effectiveModel";
import { useSessionSettings } from "@/features/agent/currentAgentSession";
import type { AgentPlace } from "@/features/agent/places";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { gotoSettings } from "@/lib/deepLink";

type AgentSession = components["schemas"]["AgentSessionOut"];

const SEP = "::";

/**
 * 对话模型选择器:列出**对话**模型(`/settings/capability-models/chat`:他自己的连接下启用、会对话的那几行),
 * 选中后写回会话的 provider_profile_id + model。会话未选则后端回退默认。
 *
 * 此前列的是每条连接的 `/providers/{id}/models` —— 那是设置页用的**整份目录**(加上已配置的行),不分能力、
 * 不分配没配:付费实测里百炼一条连接就摊出 277 行,生视频的 wan2.2-s2v、改口型的 videoretalk、作曲的 fun-music
 * 都在对话模型的下拉里,没配置的目录模型(百炼上的 kimi-k3)也在 —— 选中前者这一轮必然失败,选中后者是悄悄走另一份账单。
 *
 * 草稿(还没有会话)上照样能选:记在草稿上,第一句话发出去建会话时一起带上(见 useSessionSettings)。
 */
export function ModelPicker({ workspaceId, place, session }: { workspaceId: string; place: AgentPlace; session: AgentSession | null }) {
  const t = useI18n();

  const providers = useQuery({
    queryKey: providerKeys.profiles(),
    queryFn: listProviderProfiles,
  });
  const defaults = useQuery({
    queryKey: providerKeys.defaults(),
    queryFn: listProviderDefaults,
  });
  //: 思考档位那边读的是同一份(同一个 queryKey → 同一份缓存,不多打一次请求)。
  const chatModels = useQuery({
    queryKey: providerKeys.capabilityModels("chat"),
    queryFn: () => listCapabilityModels("chat"),
    staleTime: 60_000,
  });
  const enabled = (providers.data ?? []).filter((profile) => profile.enabled);
  const defaultChat = (defaults.data ?? []).find((item) => item.capability === "chat");
  // 「这轮实际用哪个模型」只有一处算法(effectiveModel),思考档位那边用的是同一个。
  const { settings, update } = useSessionSettings(workspaceId, place, session);
  const effective = useEffectiveChatModel(settings);

  //: 按连接分组,连接的顺序照设置页。会话上选过的、能力默认指着的那个总在里面 —— 列表没读出来(或者那一行后来停用了)
  //: 也认得出「现在用的是哪个」,不显示成「选择模型」。
  const byProfile = new Map<string, Set<string>>(enabled.map((profile) => [profile.id, new Set<string>()]));
  for (const model of chatModels.data ?? []) byProfile.get(model.provider_profile_id)?.add(model.model);
  if (defaultChat?.provider_profile_id && defaultChat.model) byProfile.get(defaultChat.provider_profile_id)?.add(defaultChat.model);
  if (settings.provider_profile_id && settings.model) byProfile.get(settings.provider_profile_id)?.add(settings.model);
  const offering = enabled.filter((profile) => (byProfile.get(profile.id)?.size ?? 0) > 0);
  const options = offering.flatMap((profile) =>
    [...(byProfile.get(profile.id) ?? [])].map((model) => ({
      value: `${profile.id}${SEP}${model}`,
      label: offering.length > 1 ? `${profile.name} · ${model}` : model,
    })),
  );

  const setModel = (value: string) => {
    const [providerProfileId, ...rest] = value.split(SEP);
    update.mutate({ provider_profile_id: providerProfileId, model: rest.join(SEP) });
  };

  const loading = providers.isPending || defaults.isPending || chatModels.isPending;
  const failed = providers.isError || defaults.isError || chatModels.isError;

  /**
   * **这一格永远占着位置。**
   *
   * 此前只要「还在读」或「任何一条连接的模型列表出错」,整个选择器就 `return null` —— 控件凭空
   * 消失,而且不说为什么。两种后果都很坏:
   *
   * - 读取期间它闪没再闪回来,页面一慢就变成"模型选择框怎么没了"(用户报的就是这个);
   * - 某一条连接的端点挂了,会把**其余所有连接**的模型一起带走 —— 一条坏连接吃掉了整个功能。
   *
   * 现在:读取中显示一个禁用的占位(名字优先用会话上已经存着的那个,所以多数时候你看到的还是
   * 同一行字);对话模型清单读不出来时,会话上选着的、能力默认指着的照样在,并说一声少了东西。
   * (清单现在是后端汇总好的一份,一条连接的目录读不出来不再影响它。)
   */
  if (loading) {
    //: 还在读:同一颗下拉,点不了、箭头换成转圈(和读完之后同一个样子、同一个位置,读完不跳)
    return (
      <SearchableSelect
        size="xs"
        className="w-auto max-w-[220px]"
        disabled
        busy
        ariaLabel={t("agentModelLabel")}
        value=""
        onValueChange={() => undefined}
        options={[]}
        placeholder={settings.model || t("agentModelPlaceholder")}
      />
    );
  }
  if (options.length === 0) {
    return (
      <Button
        variant="outline"
        size="xs"
        className="text-muted-foreground hover:text-foreground"
        onClick={() => gotoSettings("providers:chat")}
      >
        <Settings2 />
        {t("agentConfigureModel")}
      </Button>
    );
  }
  const { providerProfileId: currentProfileId, model: currentModel } = effective;
  const current = currentProfileId && currentModel ? `${currentProfileId}${SEP}${currentModel}` : "";
  const currentLabel = options.find((option) => option.value === current)?.label ?? t("agentModelPlaceholder");

  // 供应商(如火山)可能一次暴露几十个模型,普通下拉会顶穿屏幕 → 可搜索、封顶高度的选择器。
  return (
    <SearchableSelect
      value={current}
      onValueChange={setModel}
      options={options}
      searchPlaceholder={t("agentModelPlaceholder")}
      emptyText={t("cmdkEmpty")}
      //: 有连接读不出来时说一声 —— 少了几个模型总比"整个控件不见了"好,但也不能一声不吭。
      hint={failed ? t("agentModelSomeUnavailable") : undefined}
      //: 输入框底栏那一档(xs,28px);默认的触发器 —— 此前自己画了一颗「像下拉的按钮」,箭头、留白、聚焦样子都和别的下拉不一样
      size="xs"
      className="w-auto max-w-[220px]"
      ariaLabel={t("agentModelLabel")}
      placeholder={currentLabel}
      //: 没有会话时这一下要先建会话再写,不止一个来回 —— 转圈说明"收到了,在办"
      busy={update.isPending}
    />
  );
}
