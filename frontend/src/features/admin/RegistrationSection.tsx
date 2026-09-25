import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { authBootstrap, setOpenRegistration } from "@/api/client";
import { useI18n } from "@/app/preferences";
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
      void qc.invalidateQueries({ queryKey: ["registration-invites"] });
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
      </div>
    </AdminSection>
  );
}
