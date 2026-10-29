import React from "react";
import QRCode from "qrcode";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createCloudOrder,
  getCloudOrder,
  listCloudPlans,
  type CloudOrder,
  type CloudPlan,
  type PaymentChannelName,
} from "@/api/domains/cloud";
import { errorText } from "@/api/errorMessage";
import { cloudKeys } from "@/api/queryKeys";
import { useI18n, usePreferences } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { RadioGroup } from "@/components/ui/radio-group";
import { Segmented } from "@/components/ui/segmented";
import { FailureCard } from "@/components/failure/FailureCard";
import { FallbackImage } from "@/components/ui/fallback-image";
import { formatMoney } from "@/lib/money";
import { parseServerTime } from "@/lib/time";

/** 扫码之后多久问一次订单。Cloud 那边还没到账时会顺手问一次支付渠道,所以回调丢了也等得到。 */
const POLL_MS = 2_000;

/**
 * 「订阅 / 续费」(ADR 0088 第 3 步,国内二维码预付):选套餐和支付方式 → 下单拿二维码 → 扫码 → 轮询订单直到到账。
 *
 * 到账之后由 Cloud 发放:新开的套餐当场发第一批积分,续费是把有效期往后顺延(积分照旧每月发)—— 所以到账那句说的是
 * 「有效期到哪天」,不是「积分到了」。这里把余额那一份缓存作废,供应商列表那一行就会显示新余额。二维码过期(没付)就说没扣款、
 * 给「重新下单」。续费规则(同一套餐顺延、换套餐重新开始)在 Cloud 那边定,这里只说一句让人心里有数。
 */
export function CloudPurchaseDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const t = useI18n();
  const [order, setOrder] = React.useState<CloudOrder | null>(null);
  const close = () => {
    onOpenChange(false);
    setOrder(null);
  };
  return (
    <ModalShell
      open={open}
      onOpenChange={(next) => (next ? onOpenChange(true) : close())}
      title={t("cloudBuyTitle")}
    >
      {order ? (
        <PayStep order={order} onAgain={() => setOrder(null)} onDone={close} />
      ) : (
        <PickStep enabled={open} onOrdered={setOrder} onCancel={close} />
      )}
    </ModalShell>
  );
}

function PickStep({
  enabled,
  onOrdered,
  onCancel,
}: {
  enabled: boolean;
  onOrdered: (order: CloudOrder) => void;
  onCancel: () => void;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const catalog = useQuery({ queryKey: cloudKeys.plans(), queryFn: listCloudPlans, enabled, retry: false });
  const [plan, setPlan] = React.useState<string | null>(null);
  const [channel, setChannel] = React.useState<PaymentChannelName | null>(null);
  const plans = catalog.data?.plans ?? [];
  const channels = catalog.data?.channels ?? [];
  const chosenPlan = plan ?? plans[0]?.slug ?? null;
  const chosenChannel = channel ?? channels[0] ?? null;
  const order = useMutation({
    mutationFn: () => createCloudOrder(chosenPlan!, chosenChannel!),
    onSuccess: ({ order: created }) => onOrdered(created),
  });

  const priceOf = (one: CloudPlan) =>
    t("cloudBuyPrice")
      .replace("{price}", formatMoney(one.price_cents * 10_000, one.currency, locale))
      .replace("{period}", t(`cloudBuyPeriod_${one.period}`));
  const unavailable = catalog.isSuccess && (plans.length === 0 || channels.length === 0);

  return (
    <div className="grid gap-3">
      {catalog.isError && (
        <FailureCard size="inline" status="failed" title={t("cloudBuyTitle")} summary={errorText(catalog.error)} />
      )}
      {catalog.isSuccess && plans.length === 0 && <p className="m-0 text-ui-sm text-muted-foreground">{t("cloudBuyNoPlans")}</p>}
      {catalog.isSuccess && plans.length > 0 && channels.length === 0 && (
        <p className="m-0 text-ui-sm text-muted-foreground">{t("cloudBuyNoChannels")}</p>
      )}
      {plans.length > 0 && (
        <RadioGroup
          aria-label={t("cloudBuyPlan")}
          value={chosenPlan}
          onValueChange={setPlan}
          options={plans.map((one) => ({
            value: one.slug,
            label: `${one.name} · ${priceOf(one)}`,
            description: t("cloudBuyPlanCredits")
              .replace("{credits}", one.monthly_credits.toLocaleString(locale))
              .replace("{days}", String(one.credit_ttl_days)),
          }))}
        />
      )}
      {channels.length > 0 && (
        <Segmented
          aria-label={t("cloudBuyChannel")}
          value={chosenChannel ?? channels[0]}
          onValueChange={setChannel}
          options={channels.map((one) => ({ value: one, label: t(one === "alipay" ? "cloudBuyAlipay" : "cloudBuyWechat") }))}
        />
      )}
      {plans.length > 0 && <p className="m-0 text-ui-xs text-muted-foreground">{t("cloudBuyRenewHint")}</p>}
      {order.isError && (
        <FailureCard size="inline" status="failed" title={t("cloudBuyPay")} summary={errorText(order.error)} />
      )}
      <div className="flex justify-end gap-2">
        <Button variant="outline" size="sm" onClick={onCancel}>{t("cancel")}</Button>
        <Button
          size="sm"
          disabled={unavailable || !chosenPlan || !chosenChannel}
          loading={order.isPending}
          onClick={() => order.mutate()}
        >
          {t("cloudBuyPay")}
        </Button>
      </div>
    </div>
  );
}

function PayStep({ order: placed, onAgain, onDone }: { order: CloudOrder; onAgain: () => void; onDone: () => void }) {
  const t = useI18n();
  const { locale } = usePreferences();
  const qc = useQueryClient();
  const status = useQuery({
    queryKey: cloudKeys.order(placed.id),
    queryFn: () => getCloudOrder(placed.id).then(({ order }) => order),
    initialData: placed,
    //: 等付款时一直问;到账或过期就停。
    refetchInterval: (query) => (query.state.data?.status === "pending" ? POLL_MS : false),
  });
  const order = status.data ?? placed;
  const [qr, setQr] = React.useState("");
  React.useEffect(() => {
    if (placed.code_url) void QRCode.toDataURL(placed.code_url, { width: 200, margin: 1 }).then(setQr);
  }, [placed.code_url]);
  React.useEffect(() => {
    if (order.status === "paid") void qc.invalidateQueries({ queryKey: cloudKeys.account() });
  }, [order.status, qc]);

  const amount = formatMoney(order.amount_cents * 10_000, order.currency, locale);
  const channel = t(order.channel === "alipay" ? "cloudBuyAlipay" : "cloudBuyWechat");

  if (order.status === "paid") {
    return (
      <div className="grid gap-3" data-cloud-order="paid">
        <p className="m-0 text-ui-md">
          {t("cloudBuyPaid")
            .replace("{plan}", order.plan?.name ?? "")
            .replace("{date}", order.subscription_ends_at
              ? parseServerTime(order.subscription_ends_at).toLocaleDateString(locale)
              : "—")}
        </p>
        <div className="flex justify-end">
          <Button size="sm" onClick={onDone}>{t("cloudBuyDone")}</Button>
        </div>
      </div>
    );
  }
  if (order.status === "closed") {
    return (
      <div className="grid gap-3" data-cloud-order="closed">
        <p className="m-0 text-ui-md">{t("cloudBuyClosed")}</p>
        <div className="flex justify-end">
          <Button size="sm" onClick={onAgain}>{t("cloudBuyAgain")}</Button>
        </div>
      </div>
    );
  }
  return (
    <div className="grid justify-items-center gap-3" data-cloud-order="pending">
      <p className="m-0 text-ui-md font-medium">{t("cloudBuyScan").replace("{channel}", channel).replace("{amount}", amount)}</p>
      {qr ? <FallbackImage src={qr} alt="" className="size-[200px] rounded-md" /> : <div className="size-[200px]" />}
      <p className="m-0 text-ui-xs text-muted-foreground">
        {t("cloudBuyExpires").replace(
          "{time}",
          parseServerTime(order.expires_at).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" }),
        )}
        {" · "}
        {t("cloudBuyWaiting")}
      </p>
    </div>
  );
}
