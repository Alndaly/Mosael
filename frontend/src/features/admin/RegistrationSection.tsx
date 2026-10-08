import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { authBootstrap, setOpenRegistration, setWebUrl } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { SETTINGS_FIELD_WIDTH } from "@/components/settings/settings-layout";
import { useDraftText } from "@/components/ui/draft-text";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { ADMIN_CARD, AdminRow, AdminSection } from "./adminLayout";

/**
 * 谁能进这台部署:开不开放自助注册。
 *
 * 只在管理控制台里出现 —— 它管的是这台后端,不是某个人怎么用应用,所以不在「设置」里。
 * 开关在这里改,不必去改环境变量重启后端。关掉之后发码在「成员」那个 tab 里(InvitesSection)。
 */
export function RegistrationSection() {
  const t = useI18n();
  const qc = useQueryClient();
  const bootstrap = useQuery({ queryKey: ["auth-bootstrap"], queryFn: authBootstrap });
  const open = bootstrap.data?.open_registration !== false;
  const setRegistration = useMutation({
    mutationFn: (next: boolean) => setOpenRegistration(next),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["auth-bootstrap"] });
      void qc.invalidateQueries({ queryKey: ["admin", "deployment-invites"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <AdminSection id="registration" title={t("deployRegistrationTitle")} description={t("deployRegistrationDesc")}>
      <div className={ADMIN_CARD}>
        <AdminRow
          label={t("deployRegistrationOpen")}
          description={open ? t("deployRegistrationOpenOn") : t("deployRegistrationOpenOff")}
        >
          {bootstrap.isPending ? (
            <Skeleton className="h-6 w-11 rounded-full" />
          ) : (
            <Switch
              checked={open}
              disabled={setRegistration.isPending}
              onCheckedChange={(next) => setRegistration.mutate(next)}
              aria-label={t("deployRegistrationOpen")}
            />
          )}
        </AdminRow>
        {/* ADR 0054 D52:配了网页地址,邀请链接就多一个网页版(对方可能还没装客户端);桌面单机空着,只给深链。 */}
        <AdminRow label={t("deployWebUrl")} description={t("deployWebUrlDesc")}>
          {bootstrap.isPending ? (
            <Skeleton className="h-8 w-48 rounded-md" />
          ) : (
            <WebUrlField value={bootstrap.data?.web_url ?? ""} />
          )}
        </AdminRow>
      </div>
    </AdminSection>
  );
}

/** 网页地址:离开时才存(值住在服务端,每敲一个字发一次请求会把字吞掉);清空就是没有网页版。 */
function WebUrlField({ value }: { value: string }) {
  const t = useI18n();
  const qc = useQueryClient();
  const save = useMutation({
    mutationFn: (next: string) => setWebUrl(next),
    onSuccess: () => {
      toast.success(t("deployWebUrlSaved"));
      void qc.invalidateQueries({ queryKey: ["auth-bootstrap"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const draft = useDraftText<HTMLInputElement>({
    value,
    onValueChange: (next) => {
      if (next.trim() !== value) save.mutate(next.trim());
    },
    commit: "blur",
  });
  return (
    <Input
      className={SETTINGS_FIELD_WIDTH}
      aria-label={t("deployWebUrl")}
      placeholder={t("deployWebUrlPlaceholder")}
      spellCheck={false}
      {...draft}
    />
  );
}
