import React from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Lock, Play } from "lucide-react";

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
import { CapabilityUseList } from "@/components/settings/CapabilityUseList";
import { SettingsBlock } from "@/components/settings/settings-layout";
import { Button } from "@/components/ui/button";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { AssetPreviewModalById } from "@/features/media/AssetPreviewModalById";
import { ToolRowFrame } from "@/features/plugins/ToolRowFrame";

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
      <div data-plugin-host-tools="" className="-mx-1 grid auto-rows-min content-start gap-1.5 px-1">
        {tools.map((tool) => (
          <HostToolRow key={tool.name} tool={tool} instanceId={instanceId} workspaceId={workspaceId} blocked={blocked} />
        ))}
      </div>
    </SettingsBlock>
  );
}

/** 和开放的工具同一个外壳(ToolRowFrame):左边一把锁代替开放的勾,点开是「用在哪」和「试一下」。 */
function HostToolRow({ tool, instanceId, workspaceId, blocked }: {
  tool: HostTool;
  instanceId: string;
  workspaceId: string;
  blocked: boolean;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const trials = blocked ? [] : (tool.provides ?? []).filter((one) => TRIALS[one]);
  return (
    <ToolRowFrame
      data-host-tool={tool.name}
      lead={<Lock size={13} aria-hidden className="text-muted-foreground" />}
      label={tool.label || tool.name}
      description={tool.description}
      badges={
        <small className="whitespace-nowrap rounded-full bg-secondary px-1.5 py-px text-ui-2xs text-muted-foreground">
          {t("pluginHostToolBadge")}
        </small>
      }
      open={open}
      onOpenChange={setOpen}
    >
      {(tool.used_by ?? []).length === 0 ? (
        <p data-host-tool-unused="" className="m-0 text-ui-xs text-muted-foreground">{t("pluginHostToolUnused")}</p>
      ) : (
        <CapabilityUseList uses={tool.used_by ?? []} label={t("capabilityUsedBy")} />
      )}
      {trials.map((capability) => (
        <HostToolTry key={capability} capability={capability} instanceId={instanceId} workspaceId={workspaceId} />
      ))}
    </ToolRowFrame>
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
    <div data-host-tool-try={capability} className="grid gap-1.5">
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
