import React from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Download, Info } from "lucide-react";
import { toast } from "sonner";

import { denoiseAsset, listDenoiseEngines, type DenoiseStrength } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { SEGMENTED_LIST, segmentedTriggerClass } from "@/components/ui/tabs";
import { gotoJob, gotoSettings } from "@/lib/deepLink";
import { cn } from "@/lib/utils";

//: 分组小标题比选项本身轻一档 —— 和选项同号同色时,「方式」「强度」读起来像又一个选项。
const SECTION_LABEL = "text-ui-xs font-medium text-muted-foreground";

const STRENGTH_LABELS: Record<DenoiseStrength, MessageKey> = {
  light: "denoiseStrengthLight",
  medium: "denoiseStrengthMedium",
  strong: "denoiseStrengthStrong",
};

/**
 * 给一份素材降噪(ADR-0017)。素材库的两个菜单、剪辑台片段的右键菜单共用这一个。
 *
 * 选的只有两件事:**下手多重**、**用哪种方式**。引擎清单来自后端注册表 —— 这里不认识任何
 * 引擎名,只读每个引擎自己说的「有没有档位」「会不会去掉音乐」「现在能不能用」。
 */
export function DenoiseDialog({ assetId, onClose }: { assetId: string | null; onClose: () => void }) {
  const t = useI18n();
  const open = assetId !== null;
  const engines = useQuery({ queryKey: ["denoise-engines"], queryFn: listDenoiseEngines, enabled: open, staleTime: 30_000 });
  const [engine, setEngine] = React.useState("");
  const [strength, setStrength] = React.useState<DenoiseStrength>("medium");
  // 空 = 内置的那个(后端 auto 挑的就是它)。显示时落到清单里第一个不去音乐的。
  const list = engines.data ?? [];
  const chosen = list.find((one) => one.engine === engine) ?? list.find((one) => !one.removes_music);
  const strengths = (chosen?.strengths ?? []) as DenoiseStrength[];

  React.useEffect(() => {
    if (!open) {
      setEngine("");
      setStrength("medium");
    }
  }, [open]);

  const run = useMutation({
    mutationFn: () => denoiseAsset(assetId as string, { engine: chosen?.engine ?? "", strength }),
    onSuccess: (job) => {
      toast.success(t("denoiseQueued"), { action: { label: t("denoiseViewTask"), onClick: () => gotoJob(job.id) } });
      onClose();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <ModalShell
      open={open}
      onOpenChange={(next) => !next && onClose()}
      title={t("denoiseTitle")}
      className="sm:max-w-lg"
      footer={
        <>
          <Button size="sm" variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button size="sm" disabled={!chosen?.ready} loading={run.isPending} onClick={() => run.mutate()}>
            {t("denoiseStart")}
          </Button>
        </>
      }
    >
      <div className="grid gap-6">
        <div className="grid gap-2.5">
          <span className={SECTION_LABEL}>{t("denoiseMethod")}</span>
          <div className="grid gap-2" role="radiogroup" aria-label={t("denoiseMethod")}>
            {list.map((one) => {
              const selected = one.engine === chosen?.engine;
              const hintId = `denoise-hint-${one.engine}`;
              const needsSetup = !one.ready && Boolean(one.setup_hint);
              //: 能下载的引擎,入口就是卡片右上角一个「去下载」—— 按钮本身说清了要做什么,引擎给的
              //: 「去设置里哪儿下载」只作悬停提示和读屏说明;另起一行写出来会和说明文字抢,还和按钮说同一件事。
              //: 不能下载的(比如缺系统组件)没有按钮可点,这句话才照常写在说明下面。
              const downloadable = !one.ready && one.installable;
              return (
                <div
                  key={one.engine}
                  className={cn(
                    //: 键盘焦点画在整张卡外面、隔开一点。画在里面的单选按钮上(ring-inset)的话,选中卡的主色
                    //: 边框里又套一圈焦点环,弹窗一打开焦点落在第一项上,看着就是两道边。
                    "flex items-start overflow-hidden rounded-lg border ring-offset-2 ring-offset-background transition-colors has-[button[role=radio]:focus-visible]:ring-2 has-[button[role=radio]:focus-visible]:ring-ring",
                    selected ? "border-primary bg-[color-mix(in_oklab,var(--primary)_8%,transparent)]" : "border-border",
                  )}
                >
                  <button
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    aria-describedby={needsSetup ? hintId : undefined}
                    disabled={!one.ready}
                    onClick={() => setEngine(one.engine)}
                    className="flex min-w-0 flex-1 cursor-pointer items-start gap-3 self-stretch px-3.5 py-3 text-left transition-colors enabled:hover:bg-secondary/60 focus-visible:outline-none disabled:cursor-not-allowed"
                  >
                    {/* 单选圆点:选中的那一张一眼能认出来,不只靠边框颜色。 */}
                    <span
                      aria-hidden
                      className={cn(
                        "mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border",
                        selected ? "border-primary" : "border-muted-foreground/50",
                        !one.ready && "opacity-60",
                      )}
                    >
                      {selected && <span className="size-2 rounded-full bg-primary" />}
                    </span>
                    <span className="grid min-w-0 gap-1">
                      <span className={cn("flex flex-wrap items-center gap-2 text-ui-sm font-medium leading-5", !one.ready && "opacity-60")}>
                        {one.label}
                        {/* 会去掉音乐的**单独标出来** —— 用户说"降噪"时没想把配乐也拿掉,而说明文字
                            是会被略读的。 */}
                        {one.removes_music && (
                          <span className="rounded-sm bg-[color-mix(in_oklab,var(--warning)_16%,transparent)] px-1.5 py-px text-ui-2xs font-medium text-foreground">
                            {t("denoiseRemovesMusicBadge")}
                          </span>
                        )}
                      </span>
                      <span className={cn("text-ui-xs leading-[1.5] text-muted-foreground", !one.ready && "opacity-60")}>{one.description}</span>
                      {/* 没准备好时说去哪儿准备 —— 这句话由引擎自己给,这里不认识任何引擎。 */}
                      {needsSetup && (
                        <span id={hintId} className={cn("text-ui-xs leading-[1.5] text-muted-foreground", downloadable && "sr-only")}>
                          {one.setup_hint}
                        </span>
                      )}
                    </span>
                  </button>
                  {/* 放在单选按钮外面:禁用的按钮里不能再套按钮。 */}
                  {downloadable && (
                    <Button
                      variant="outline"
                      size="xs"
                      className="mr-3 mt-2.5 shrink-0"
                      title={one.setup_hint || undefined}
                      onClick={() => {
                        onClose();
                        gotoSettings("denoise");
                      }}
                    >
                      <Download size={12} /> {t("denoiseGoDownload")}
                    </Button>
                  )}
                </div>
              );
            })}
          </div>
        </div>
        {/* 没有档位的引擎不摆这个旋钮 —— 拨了也没用。 */}
        {strengths.length > 0 && (
          <div className="grid gap-2.5">
            <span className={SECTION_LABEL}>{t("denoiseStrength")}</span>
            {/* 三档等分整行 —— 挤在左边、右边空一大截时,看着像没排完。 */}
            <div className={cn(SEGMENTED_LIST, "grid w-full auto-cols-fr grid-flow-col")} role="radiogroup" aria-label={t("denoiseStrength")}>
              {strengths.map((one) => (
                <button
                  key={one}
                  type="button"
                  role="radio"
                  aria-checked={strength === one}
                  className={segmentedTriggerClass(strength === one)}
                  onClick={() => setStrength(one)}
                >
                  {t(STRENGTH_LABELS[one])}
                </button>
              ))}
            </div>
            <p className="m-0 text-ui-xs leading-[1.5] text-muted-foreground">{t("denoiseStrengthHint")}</p>
          </div>
        )}
        {/* 结果会落在哪儿:不是设置项,是一句交代,做成一条安静的提示,别和上面的说明文字混成一片。 */}
        <p className="m-0 flex items-start gap-2 rounded-md bg-panel-subtle px-3 py-2.5 text-ui-xs leading-[1.5] text-muted-foreground">
          <Info size={14} className="mt-px shrink-0" aria-hidden />
          {t("denoiseOutputNote")}
        </p>
      </div>
    </ModalShell>
  );
}
