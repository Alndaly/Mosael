import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Info } from "lucide-react";
import { toast } from "sonner";

import { makeAssetMask, type Asset } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { assetKeys } from "@/api/queryKeys";
import { useI18n } from "@/app/preferences";
import { DIALOG_FIELD, ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";

/** 扩张 / 羽化的上下限,和后端 `MaskAssetRequest` 的两条 Field 是同一组数(再大的半径后端也会按长边封顶)。 */
const GROW_LIMIT = 256;
const FEATHER_LIMIT = 256;

const percent = (value: number) => `${Math.round(value * 100)}%`;

/** 数字格里的字符串落成一个范围内的数:空着 / 打歪了都当作 0,越界就夹回去。 */
function clamped(text: string, min: number, max: number, round = false): number {
  const parsed = Number(text);
  const value = Number.isFinite(parsed) ? (round ? Math.round(parsed) : parsed) : 0;
  return Math.min(max, Math.max(min, value));
}

/**
 * 「生成蒙版」:对素材库里**已有的一张图**,一步得到一张存下来的蒙版素材(ADR 0056 决定 6)。
 *
 * 和 MaskEditor 那条「按亮度 / 按 alpha 起手」不是同一件事,也**不做成重复的**:编辑器那条在浏览器
 * canvas 上取像素、只做阈值二值化;**扩张 / 羽化只有后端算得对**(形态学 + 盒式模糊,后端 media/masks
 * 有一份和前端逐位一致的实现)。所以这条路的价值是「不用先开编辑器、也不用先画」——挑一张图、调好参数、
 * 落成一张新素材。画刷子那一套仍然只在编辑器里。
 *
 * 五个旋钮就是后端那只 request 的五个字段;形状四步的先后(阈值 → 反选 → 扩张 → 羽化)由后端定,
 * 界面只摆旋钮,不自己算。产出的名字(「蒙版 · <原图名>」)、不打标签、原图不动,都是后端的事。
 */
export function MaskFromAssetDialog({
  asset,
  onMade,
  onClose,
}: {
  /** 拿哪一份素材算蒙版;`null` = 关着。 */
  asset: { id: string; name: string } | null;
  /** 成了:新素材交回调用方(素材库拿它开详情 —— 蒙版是给人看一眼、接着用的东西)。 */
  onMade?: (made: Asset) => void;
  onClose: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const open = asset !== null;
  const [source, setSource] = React.useState<"luminance" | "alpha">("luminance");
  const [threshold, setThreshold] = React.useState(0.5);
  const [invert, setInvert] = React.useState(false);
  //: 两个数字格存的是**打进去的那个字符串**(空着是合法的中间态,不许立刻变成 0),提交时才夹进范围。
  const [grow, setGrow] = React.useState("0");
  const [feather, setFeather] = React.useState("0");

  // 换一份素材就是新的一次:上一份调过的参数不该跟过来。
  React.useEffect(() => {
    if (open) return;
    setSource("luminance");
    setThreshold(0.5);
    setInvert(false);
    setGrow("0");
    setFeather("0");
  }, [open]);

  const run = useMutation({
    mutationFn: (assetId: string) =>
      makeAssetMask(assetId, {
        source,
        threshold,
        invert,
        grow: clamped(grow, -GROW_LIMIT, GROW_LIMIT, true),
        feather: clamped(feather, 0, FEATHER_LIMIT),
      }),
    onSuccess: (made) => {
      //: 新素材要自己出现在素材库里,不刷就得切走再切回来才看得见。
      void qc.invalidateQueries({ queryKey: assetKeys.everywhere() });
      toast.success(t("assetMaskDone").replace("{name}", made.name));
      onMade?.(made);
      onClose();
    },
    //: 失败照实说后端那一句(「这不是一张图片」「源文件不在了」),弹窗**留着** —— 参数还能改。
    onError: (error) => toast.error(errorText(error)),
  });

  return (
    <ModalShell
      open={open}
      onOpenChange={(next) => !next && onClose()}
      title={t("assetMaskTitle")}
      className="sm:max-w-lg"
      footer={
        <>
          <Button size="sm" variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button
            size="sm"
            loading={run.isPending}
            disabled={asset === null}
            onClick={() => asset && run.mutate(asset.id)}
          >
            {t("assetMaskStart")}
          </Button>
        </>
      }
    >
      <div className="grid gap-5">
        <p className="m-0 text-ui-sm leading-[1.5] text-muted-foreground">
          {t("assetMaskHint").replace("{name}", asset?.name ?? "")}
        </p>

        {/*: 来源是二选一、选项短、换了立刻生效 —— 分段。 */}
        <div className={DIALOG_FIELD}>
          <span>{t("assetMaskSource")}</span>
          <Segmented
            aria-label={t("assetMaskSource")}
            value={source}
            onValueChange={setSource}
            fill
            options={[
              { value: "luminance", label: t("assetMaskSourceLuminance") },
              { value: "alpha", label: t("assetMaskSourceAlpha") },
            ]}
          />
          <small>{t("assetMaskSourceHint")}</small>
        </div>

        {/*: 阈值 + 当前值:滑杆上那个数不写出来,人只能凭位置猜。 */}
        <div className={DIALOG_FIELD}>
          <span>
            {t("maskThreshold")}
            <span className="ml-auto tabular-nums text-muted-foreground">{percent(threshold)}</span>
          </span>
          <Slider
            aria-label={t("maskThreshold")}
            value={[threshold]}
            min={0}
            max={1}
            step={0.01}
            onValueChange={([next]) => setThreshold(next)}
          />
          <small>{t("assetMaskThresholdHint")}</small>
        </div>

        <label className="flex items-center gap-2 text-ui-sm font-medium text-foreground">
          <Switch checked={invert} onCheckedChange={setInvert} />
          <span>{t("maskInvert")}</span>
        </label>

        <div className={DIALOG_FIELD}>
          <span>{t("assetMaskGrow")}</span>
          <Input
            type="number"
            aria-label={t("assetMaskGrow")}
            min={-GROW_LIMIT}
            max={GROW_LIMIT}
            step={1}
            value={grow}
            onChange={(event) => setGrow(event.target.value)}
          />
          <small>{t("assetMaskGrowHint")}</small>
        </div>

        <div className={DIALOG_FIELD}>
          <span>{t("maskFeatherRadius")}</span>
          <Input
            type="number"
            aria-label={t("maskFeatherRadius")}
            min={0}
            max={FEATHER_LIMIT}
            step={1}
            value={feather}
            onChange={(event) => setFeather(event.target.value)}
          />
          <small>{t("assetMaskFeatherHint")}</small>
        </div>

        {/*: 结果落在哪儿、白是哪一半:不是设置项,是一句交代,做成一条安静的提示。 */}
        <p className="m-0 flex items-start gap-2 rounded-md bg-panel-subtle px-3 py-2.5 text-ui-xs leading-[1.5] text-muted-foreground">
          <Info size={14} className="mt-px shrink-0" aria-hidden />
          {t("assetMaskNote")}
        </p>
      </div>
    </ModalShell>
  );
}
