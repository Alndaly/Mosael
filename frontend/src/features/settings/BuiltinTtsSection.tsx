import React from "react";
import { useQuery } from "@tanstack/react-query";

import { listTtsEngines, type TtsEngineChoice } from "@/api/client";
import { useIsDeploymentAdmin } from "@/app/auth";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { gotoAdmin } from "@/lib/deepLink";

import { SettingsBlock, SettingsGroup, SettingsRow } from "@/components/settings/settings-layout";

/**
 * 无需供应商连接的配音引擎(本地克隆、Edge 免费语音)现在能不能用。只读 —— 设置页只有「连接」时,
 * 没配任何 Key 的用户看到的是几个空区块,读起来像"配音不可用",而剪辑页明明即开即用。
 * 元数据来自 /api/tts/engines(needs_key=false 的就是内置),后端加引擎这里自动跟进。
 *
 * 本地克隆没装时,**谁能装就给谁路**:装引擎只给部署管理员(routes/voices.download_tts_model),
 * 所以管理员看到一个去管理页「引擎」的按钮,成员看到一句「由部署管理员安装」—— 给成员一个
 * 点了就 403、或者跳进一页他打不开的按钮,等于一个死入口。
 *
 * 一条内置引擎都没有时(接口回空、或全是 needs_key),**这一组照旧在**:配音页的说明会提到这一组,
 * 组凭空消失那句话就没有落点 —— 而底下什么都不画,读起来是"没有内置引擎这回事",不是"这台机器上
 * 现在没有"。给一行说清现状和下一步;加载中(`data` 还是 undefined)不写,免得这一版的数据没到就
 * 断言"没有"。
 */
export function BuiltinTtsSection() {
  const t = useI18n();
  const isAdmin = useIsDeploymentAdmin();
  // staleTime 不能是 Infinity:这份数据里带着"本地引擎装了没有",而管理员就是会在管理页
  // 把它装上再回来(和 VoicePanel 同一个 query key —— 那边已经因此改过一次,这边漏了)。
  const engines = useQuery({ queryKey: ["tts-engines"], queryFn: listTtsEngines, staleTime: 30_000 });
  const builtin = (engines.data ?? []).filter((engine) => !engine.needs_key);
  // 一条内置的都没有:接口回空,或者回来的全是 `needs_key`(要连接的那些,不是这一组的东西)。
  // 数据到之前(`data` 还是 undefined)不写这一行,免得"还没拉到"被读成"没有"。
  const none = engines.data !== undefined && builtin.length === 0;
  return (
    <SettingsGroup title={t("builtinTtsTitle")} description={t("builtinTtsDesc")}>
      {none ? (
        <SettingsBlock>
          <p className="m-0 px-0.5 text-ui-sm leading-[1.6] text-muted-foreground">{t("builtinTtsNoEngines")}</p>
        </SettingsBlock>
      ) : (
        builtin.map((engine) => <BuiltinEngineRow key={engine.id} engine={engine} isAdmin={isAdmin} />)
      )}
    </SettingsGroup>
  );
}

/** 一个内置引擎一行:能用就说「即开即用」,没装就按看的人给入口(见上面的说明)。 */
function BuiltinEngineRow({ engine, isAdmin }: { engine: TtsEngineChoice; isAdmin: boolean }) {
  const t = useI18n();
  return (
    <SettingsRow label={engine.label} description={engine.note}>
      {engine.ready ? (
        <Badge variant="outline" className="border-[color:var(--ok,#22a06b)] text-[color:var(--ok,#22a06b)]">
          {t("builtinTtsReady")}
        </Badge>
      ) : isAdmin ? (
        <Button size="sm" variant="outline" onClick={() => gotoAdmin("engines")}>
          {t("engineGoInstall")}
        </Button>
      ) : (
        <span className="text-ui-xs text-muted-foreground">{t("engineInstalledByAdmin")}</span>
      )}
    </SettingsRow>
  );
}
