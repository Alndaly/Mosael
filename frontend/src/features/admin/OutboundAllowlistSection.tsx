import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Network, Plus, X } from "lucide-react";
import { toast } from "sonner";

import { getOutboundAllowlist, setOutboundAllowlist } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { DIALOG_FIELD, ModalShell } from "@/components/app/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { isImeKeystroke } from "@/lib/shortcuts";
import { ADMIN_CARD, AdminRow, AdminSection } from "./adminLayout";

const QUERY_KEY = ["outbound-allowlist"] as const;

/**
 * 内网访问:用户、模板、智能体给的地址(HTTP 请求节点、http_request / fetch_url、从链接导入)**可以**去的内网地址。
 *
 * 默认只许公网(见后端 core/outbound_guard):本机回环、局域网、云服务器元数据一律拦下,报错里会说该把哪一项加到这里。
 * 每一项是主机名、IP 或 CIDR 网段,主机名和 IP 可以带端口。和共享文件夹一样是**这台部署**的决定,整份清单 PUT 回去,
 * 校验在后端(写不对的那一项后端点名,留在弹窗里)。
 */
export function OutboundAllowlistSection() {
  const t = useI18n();
  const qc = useQueryClient();
  const allowlist = useQuery({ queryKey: QUERY_KEY, queryFn: getOutboundAllowlist });
  const current = allowlist.data?.entries ?? [];
  const [adding, setAdding] = React.useState(false);
  const [removing, setRemoving] = React.useState<string | null>(null);
  const remove = useMutation({
    mutationFn: (next: string[]) => setOutboundAllowlist(next),
    onSuccess: (data) => qc.setQueryData(QUERY_KEY, data),
    onSettled: () => setRemoving(null),
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <AdminSection
      id="outbound-allowlist"
      title={t("deployOutboundTitle")}
      description={t("deployOutboundDesc")}
      actions={
        <Button size="sm" variant="outline" disabled={!allowlist.isSuccess} onClick={() => setAdding(true)}>
          <Plus size={13} /> {t("deployOutboundNew")}
        </Button>
      }
    >
      <div className={ADMIN_CARD}>
        {allowlist.isPending ? (
          <div className="px-4 py-3">
            <Skeleton className="h-8 w-full" />
          </div>
        ) : current.length === 0 ? (
          <EmptyState size="compact" icon={<Network size={15} />} title={t("deployOutboundEmpty")} body={t("deployOutboundEmptyBody")} />
        ) : (
          current.map((entry) => (
            <AdminRow
              key={entry}
              leading={<Network size={15} className="shrink-0 text-muted-foreground" />}
              label={
                <code className="timecode select-all font-normal" title={entry}>
                  {entry}
                </code>
              }
            >
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={t("deployOutboundRemove")}
                title={t("deployOutboundRemove")}
                loading={removing === entry}
                disabled={remove.isPending}
                onClick={() => {
                  setRemoving(entry);
                  remove.mutate(current.filter((one) => one !== entry));
                }}
              >
                <X />
              </Button>
            </AdminRow>
          ))
        )}
      </div>
      <AddEntryDialog open={adding} current={current} onClose={() => setAdding(false)} />
    </AdminSection>
  );
}

/** 加一项。后端挡下来的那句话(写不对的是哪一项、该怎么写)留在弹窗里,贴着输入框。 */
function AddEntryDialog({ open, current, onClose }: { open: boolean; current: string[]; onClose: () => void }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [draft, setDraft] = React.useState("");
  const save = useMutation({
    mutationFn: (next: string[]) => setOutboundAllowlist(next),
    onSuccess: (data) => {
      qc.setQueryData(QUERY_KEY, data);
      onClose();
    },
  });
  React.useEffect(() => {
    if (open) {
      setDraft("");
      save.reset();
    }
    // save.reset 每次渲染都是新引用;只在打开的那一下清空。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  const entry = draft.trim();
  const submit = () => {
    if (entry && !save.isPending) save.mutate([...current, entry]);
  };
  const errorId = React.useId();

  return (
    <ModalShell
      open={open}
      onOpenChange={(next) => !next && !save.isPending && onClose()}
      title={t("deployOutboundNew")}
      className="w-[440px]"
      footer={
        <>
          <Button variant="outline" disabled={save.isPending} onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button loading={save.isPending} disabled={!entry} onClick={submit}>
            {t("deployOutboundAdd")}
          </Button>
        </>
      }
    >
      <label className={DIALOG_FIELD}>
        <span>{t("deployOutboundEntry")}</span>
        <Input
          autoFocus
          value={draft}
          placeholder={t("deployOutboundPlaceholder")}
          aria-invalid={save.isError || undefined}
          aria-describedby={save.isError ? errorId : undefined}
          onChange={(event) => {
            setDraft(event.currentTarget.value);
            if (save.isError) save.reset();
          }}
          onKeyDown={(event) => {
            if (isImeKeystroke(event)) return;
            if (event.key === "Enter") {
              event.preventDefault();
              submit();
            }
          }}
        />
        {save.isError ? (
          <small id={errorId} role="alert" className="!text-destructive">
            {save.error.message}
          </small>
        ) : (
          <small>{t("deployOutboundNewDesc")}</small>
        )}
      </label>
    </ModalShell>
  );
}
