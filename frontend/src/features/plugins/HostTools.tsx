import React from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Play } from "lucide-react";

import {
  denoiseAsset,
  listAssets,
  parseDocument,
  separateAssetAudio,
  type PluginInstance,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { assetKeys } from "@/api/queryKeys";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { CapabilityUseList } from "@/components/settings/CapabilityUseList";
import { SettingsBlock } from "@/components/settings/settings-layout";
import { Button } from "@/components/ui/button";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { AssetPreviewModalById } from "@/features/media/AssetPreviewModalById";

type HostTool = NonNullable<PluginInstance["host_tools"]>[number];

/**
 * 「试一下」:挑一份素材,**走宿主真实的那个入口**跑一次这个连接 —— 文档详情的「重新解析」、素材库的降噪 / 分离。
 * 不另开一条「直接调插件」的后门:插件说的是宿主协议(ADR 0032 §3),试的就该是用户真用时的那条路。
 * 认不出的能力(生成走模型选择器、`tools` 只报工具清单)没有「试一下」。
 */
const TRIALS: Record<string, { kinds: string[]; run: (assetId: string, instanceId: string) => Promise<unknown>; done: MessageKey; opens?: boolean }> = {
  document_parse: { kinds: ["document"], run: (asset, instance) => parseDocument(asset, instance), done: "pluginHostTryParsing", opens: true },
  audio_denoise: { kinds: ["audio", "video"], run: (asset, instance) => denoiseAsset(asset, { engine: instance }), done: "pluginHostTryJob" },
  audio_separation: { kinds: ["audio", "video"], run: (asset, instance) => separateAssetAudio(asset, instance), done: "pluginHostTryJob" },
};

/**
 * 只给 Mosael 调用的工具(认领了文档解析、降噪、生成这类宿主能力)。不能勾选开放 —— 它们说的是宿主那一套协议 ——
 * 但要列出来:它做什么、**用在哪**(能力表现算的,ADR 0032 §4:哪个页面入口、哪个工作流节点、哪个智能体工具点得到它)、
 * 能不能在这里试一下。此前 MinerU 那一块是空的,后来是一句手写的「用在哪」(用户截图:「为何这个列表不是动态的」)。
 */
export function HostToolList({ tools, instanceId, workspaceId, blocked }: {
  tools: HostTool[];
  instanceId: string;
  workspaceId: string;
  /** 连接还不能用(未启用、缺配置……)时不给「试一下」,理由在卡片抬头已经说了。 */
  blocked: boolean;
}) {
  const t = useI18n();
  return (
    <SettingsBlock>
      <p className="m-0 text-ui-xs text-muted-foreground">{t("pluginHostToolsDesc")}</p>
      <ul data-plugin-host-tools="" className="m-0 grid list-none gap-2 p-0">
        {tools.map((tool) => (
          <li key={tool.name} data-host-tool={tool.name} className="grid gap-2 rounded-lg border border-border px-3 py-2.5">
            <span className="flex min-w-0 items-baseline gap-2">
              <span className="text-ui-sm font-medium text-foreground">{tool.label || tool.name}</span>
              <code className="truncate text-ui-2xs text-muted-foreground">{tool.name}</code>
            </span>
            {tool.description && (
              <span className="text-ui-xs leading-relaxed text-muted-foreground">
                <InlineMarkdown text={tool.description} />
              </span>
            )}
            {(tool.used_by ?? []).length === 0 ? (
              <span data-host-tool-unused="" className="text-ui-xs text-muted-foreground">{t("pluginHostToolUnused")}</span>
            ) : (
              <CapabilityUseList uses={tool.used_by ?? []} label={t("capabilityUsedBy")} />
            )}
            {!blocked && (tool.provides ?? []).filter((one) => TRIALS[one]).map((capability) => (
              <HostToolTry key={capability} capability={capability} instanceId={instanceId} workspaceId={workspaceId} />
            ))}
          </li>
        ))}
      </ul>
    </SettingsBlock>
  );
}

function HostToolTry({ capability, instanceId, workspaceId }: { capability: string; instanceId: string; workspaceId: string }) {
  const t = useI18n();
  const trial = TRIALS[capability];
  const [assetId, setAssetId] = React.useState("");
  const [opened, setOpened] = React.useState<string | null>(null);
  const assets = useQuery({
    queryKey: assetKeys.list(workspaceId),
    queryFn: () => listAssets(workspaceId),
    enabled: Boolean(workspaceId),
  });
  const options = (assets.data ?? [])
    .filter((asset) => trial.kinds.includes(asset.kind))
    .map((asset) => ({ value: asset.id, label: asset.name }));
  const run = useMutation({ mutationFn: () => trial.run(assetId, instanceId) });
  return (
    <div data-host-tool-try={capability} className="grid gap-1.5 border-t border-divider pt-2">
      <div className="flex flex-wrap items-center gap-2">
        <SearchableSelect
          value={assetId}
          onValueChange={(next) => {
            setAssetId(next);
            run.reset();
          }}
          options={options}
          placeholder={t("pluginHostTryPick")}
          emptyText={t("pluginHostTryNoAssets")}
          size="sm"
          className="min-w-[220px] flex-1"
        />
        <Button size="sm" variant="outline" disabled={!assetId} loading={run.isPending} onClick={() => run.mutate()}>
          <Play size={12} />
          {t("pluginHostTry")}
        </Button>
      </div>
      {run.isSuccess && (
        <p role="status" className="m-0 flex flex-wrap items-center gap-2 text-ui-xs text-muted-foreground">
          {t(trial.done)}
          {trial.opens && (
            <Button size="xs" variant="ghost" className="px-1.5 text-ui-xs" onClick={() => setOpened(assetId)}>
              {t("pluginHostTryOpen")}
            </Button>
          )}
        </p>
      )}
      {run.isError && <p role="alert" className="m-0 text-ui-xs text-destructive">{errorText(run.error)}</p>}
      {opened && <AssetPreviewModalById id={opened} onClose={() => setOpened(null)} />}
    </div>
  );
}
