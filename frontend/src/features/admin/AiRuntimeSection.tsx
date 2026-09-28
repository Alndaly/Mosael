import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ADMIN_CARD, AdminRow, AdminSection } from "./adminLayout";

type AiRuntimeConfig = components["schemas"]["AiRuntimeConfigOut"];

const clampRetries = (n: number): number => Math.max(0, Math.min(10, Math.floor(Number.isFinite(n) ? n : 3)));

/**
 * AI 运行时:目前只有「供应商瞬断时的最大重试次数」(0..10),对所有 AI 出站调用生效。
 *
 * 和出站代理挨着放在「部署设置」里:两者回答的是同一个问题 —— 这台部署的 AI 调用怎么出去;
 * 写入也同一条权限(部署管理员,见 routes/settings/system.py)。
 */
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
    onError: (e) => toast.error(errorText(e)),
  });

  const current = draft ?? config.data?.max_retries ?? 3;
  const dirty = config.data != null && current !== config.data.max_retries;

  return (
    <AdminSection id="ai-runtime" title={t("aiRuntimeTitle")} description={t("aiRuntimeDesc")}>
      <div className={ADMIN_CARD}>
        <AdminRow label={t("aiMaxRetriesLabel")} description={t("aiMaxRetriesDesc")}>
          <Input
            type="number"
            min={0}
            max={10}
            // 0–10 的两位数,标准字段宽度在这儿只会拖一条空槽。
            className="w-20"
            aria-label={t("aiMaxRetriesLabel")}
            value={String(current)}
            disabled={!config.data}
            onChange={(e) => setDraft(e.target.value === "" ? 0 : clampRetries(Number(e.target.value)))}
          />
          <Button disabled={!dirty} loading={save.isPending} onClick={() => save.mutate(clampRetries(current))}>
            {t("save")}
          </Button>
        </AdminRow>
      </div>
    </AdminSection>
  );
}
