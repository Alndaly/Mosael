import React from "react";
import { useQuery } from "@tanstack/react-query";
import { AudioLines } from "lucide-react";

import { listTtsEngines } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

import { SettingsGroup, SettingsRow } from "./ui";

/**
 * 无需供应商档案的配音引擎(本地克隆、Edge 免费语音)。设置页只有「档案」时,
 * 没配任何 Key 的用户在这页看到的是两个空区块,读起来像"配音不可用"——
 * 而剪辑页明明即开即用。这一节把内置引擎摆到档案区上面,元数据来自
 * /api/tts/engines(needs_key=false 的就是内置),后端加引擎这里自动跟进。
 */
export function BuiltinTtsSection({ onOpenVoiceClone }: { onOpenVoiceClone: () => void }) {
  const t = useI18n();
  // staleTime 不能是 Infinity:这份数据里带着"本地引擎装了没有",而用户就是会在另一个页面
  // 把它装上再回来(和 VoicePanel 同一个 query key —— 那边已经因此改过一次,这边漏了)。
  const engines = useQuery({ queryKey: ["tts-engines"], queryFn: listTtsEngines, staleTime: 30_000 });
  const builtin = (engines.data ?? []).filter((engine) => !engine.needs_key);
  if (builtin.length === 0) return null;
  return (
    <SettingsGroup title={t("builtinTtsTitle")} description={t("builtinTtsDesc")}>
      {builtin.map((engine) => (
        <SettingsRow key={engine.id} label={engine.label} description={engine.note}>
          {engine.id === "clone" ? (
            <Button variant="outline" size="sm" onClick={onOpenVoiceClone}>
              <AudioLines size={13} /> {t("builtinTtsManageClone")}
            </Button>
          ) : (
            <Badge variant="outline" className="border-[color:var(--ok,#22a06b)] text-[color:var(--ok,#22a06b)]">
              {t("builtinTtsReady")}
            </Badge>
          )}
        </SettingsRow>
      ))}
    </SettingsGroup>
  );
}
