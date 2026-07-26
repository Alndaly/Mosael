import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SettingsGroup, SettingsRow } from "@/features/settings/ui";

type AiRuntimeConfig = components["schemas"]["AiRuntimeConfigOut"];

const clampRetries = (n: number): number => Math.max(0, Math.min(10, Math.floor(Number.isFinite(n) ? n : 3)));

/** AI 运行时设置:目前只有「供应商瞬断时的最大重试次数」(0..10)。工作流 LLM 节点用。 */
export function AiRuntimeSection() {
  const t = useI18n();
  const qc = useQueryClient();
  const config = useQuery({
    queryKey: ["ai-runtime"],
    queryFn: () => api<AiRuntimeConfig>("/api/settings/ai-runtime"),
  });
  const [draft, setDraft] = React.useState<number | null>(null);
  React.useEffect(() => {
    if (config.data && draft === null) setDraft(config.data.max_retries);
  }, [config.data, draft]);

  const save = useMutation({
    mutationFn: (max_retries: number) =>
      api<AiRuntimeConfig>("/api/settings/ai-runtime", { method: "PUT", body: JSON.stringify({ max_retries }) }),
    onSuccess: (data) => {
      qc.setQueryData(["ai-runtime"], data);
      setDraft(data.max_retries);
      toast.success(t("saved"));
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : String(e)),
  });

  const current = draft ?? config.data?.max_retries ?? 3;
  const dirty = config.data != null && current !== config.data.max_retries;

  return (
    <SettingsGroup title={t("aiRuntimeTitle")} description={t("aiRuntimeDesc")}>
      <SettingsRow label={t("aiMaxRetriesLabel")} description={t("aiMaxRetriesDesc")}>
        <Input
          type="number"
          min={0}
          max={10}
          className="w-20"
          value={String(current)}
          disabled={config.isLoading}
          onChange={(e) => setDraft(e.target.value === "" ? 0 : clampRetries(Number(e.target.value)))}
        />
        <Button size="sm" disabled={!dirty || save.isPending} onClick={() => save.mutate(clampRetries(current))}>
          {t("save")}
        </Button>
      </SettingsRow>
    </SettingsGroup>
  );
}
