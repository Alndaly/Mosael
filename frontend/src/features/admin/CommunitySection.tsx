import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { getCommunityUrl, setCommunityUrl } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { ADMIN_CARD, AdminRow, AdminSection } from "./adminLayout";

const QUERY_KEY = ["community-url"] as const;

/**
 * 这台部署连哪个社区(ADR 0026)。默认是官网;清空 = 不连社区(设置里的「社区账号」、画板分享、
 * 发布到社区、插件市场的「社区」一栏都会说「社区未配置」)。和开放注册一样是**这台部署**的决定。
 */
export function CommunitySection() {
  const t = useI18n();
  const qc = useQueryClient();
  const current = useQuery({ queryKey: QUERY_KEY, queryFn: getCommunityUrl });
  const [draft, setDraft] = React.useState<string | null>(null);
  const value = draft ?? current.data?.url ?? "";
  const save = useMutation({
    mutationFn: (url: string) => setCommunityUrl(url),
    onSuccess: (data) => {
      qc.setQueryData(QUERY_KEY, data);
      setDraft(null);
      void qc.invalidateQueries({ queryKey: ["community-status"] });
      toast.success(t("deployCommunitySaved"));
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const dirty = draft !== null && draft.trim() !== (current.data?.url ?? "");

  return (
    <AdminSection id="community" title={t("deployCommunityTitle")} description={t("deployCommunityDesc")}>
      <div className={ADMIN_CARD}>
        <AdminRow
          label={t("deployCommunityUrl")}
          description={current.data ? t("deployCommunityDefault").replace("{url}", current.data.default_url) : undefined}
        >
          {current.isPending ? (
            <Skeleton className="h-9 w-64" />
          ) : (
            <>
              <Input
                className="w-64"
                value={value}
                placeholder={current.data?.default_url}
                aria-label={t("deployCommunityUrl")}
                onChange={(event) => setDraft(event.currentTarget.value)}
              />
              <Button variant="outline" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate(value.trim())}>
                {t("save")}
              </Button>
            </>
          )}
        </AdminRow>
      </div>
    </AdminSection>
  );
}
