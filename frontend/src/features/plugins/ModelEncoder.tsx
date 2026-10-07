import React from "react";

import type { ModelEncoder, ModelFile, NodeEncoders } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { CatalogBadge } from "@/components/app/CatalogDialog";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { ActiveFamiliesContext } from "@/features/plugins/activeFamilies";
import { pairsFirst } from "@/features/plugins/modelLibraryView";
import { encoderFit } from "@/features/plugins/workbench/workbenchLogic";
import { cn } from "@/lib/utils";

/**
 * 模型库里的文本编码器(ADR 0034 §2 的 2026-10-07 补记):一个编码器给好几种底模用,所以不贴底模,而是写它是哪一种
 * (`T5-XXL`)、常配哪几种底模(`常配 Flux、SD 3、HiDream`)。是哪一种、常配什么都是插件给的,这里只管摆。
 */

/** 卡片、列表上「常配」最多写出几种,其余写「等 N 种」(悬停看全部)。 */
const PAIRS_SHOWN = 3;

/** 那一枚徽章悬停时说的:是文本编码器,凭的是什么。 */
function sourceHint(encoder: ModelEncoder): MessageKey {
  if (!encoder.kind) return "modelEncoderUnknownHint";
  return encoder.source === "filename" ? "modelEncoderSourceFilename" : "modelEncoderSourceWeights";
}

/** 详情里那一行的说明:凭的是什么,再说「常配」是什么意思。 */
export function useEncoderNote(encoder: ModelEncoder | null | undefined): string | undefined {
  const t = useI18n();
  if (!encoder) return undefined;
  if ((encoder.pairs ?? []).length === 0) return t(sourceHint(encoder));
  return t("modelEncoderNote").replace("{source}", t(sourceHint(encoder))).replace("{pairs}", t("modelEncoderPairsNote"));
}

/**
 * 文本编码器的那一枚徽章:是哪一种(认不出就写「文本编码器」);从权重认出的实色,按文件名猜的、认不出的淡色,和底模徽章
 * 一样。`pairs`:徽章下面再写一行「常配 ……」(列表里那一格窄,并排放不下)。
 */
export function EncoderBadge({ encoder, pairs = false }: { encoder: ModelEncoder; pairs?: boolean }) {
  const t = useI18n();
  const badge = (
    <Hint label={t(sourceHint(encoder))}>
      <span className="inline-flex shrink-0">
        <CatalogBadge tone={encoder.kind && encoder.source === "weights" ? "primary" : "muted"}>
          {encoder.kind ? encoder.label : t("modelEncoderRole")}
        </CatalogBadge>
      </span>
    </Hint>
  );
  if (!pairs || (encoder.pairs ?? []).length === 0) return badge;
  return (
    <span className="grid min-w-0 flex-1 justify-items-start gap-0.5">
      {badge}
      <EncoderPairs encoder={encoder} className="w-full min-w-0" />
    </span>
  );
}

/**
 * 「常配 Flux、SD 3、HiDream 等 6 种」:勾着的底模排前面、写成正文色;放不下时截断,悬停看全部。没有常配的:写它是文本编码器
 * (认不出是哪一种时徽章已经写着「文本编码器」,这一行写「认不出是哪一种」)。卡片上徽章下面那一行。
 */
export function EncoderPairs({ encoder, className }: { encoder: ModelEncoder; className?: string }) {
  const t = useI18n();
  const active = React.useContext(ActiveFamiliesContext);
  const pairs = pairsFirst(encoder.pairs ?? [], active);
  if (pairs.length === 0) {
    return (
      <span className={cn("text-ui-xs text-muted-foreground", className)}>
        <Truncate>{t(encoder.kind ? "modelEncoderRole" : "modelEncoderUnknown")}</Truncate>
      </span>
    );
  }
  const shown = pairs.slice(0, PAIRS_SHOWN);
  const template = pairs.length > PAIRS_SHOWN ? t("modelEncoderPairsMore") : t("modelEncoderPairs");
  const filled = template.replace("{n}", String(pairs.length)).replace("{more}", String(pairs.length - shown.length));
  const [before, after = ""] = filled.split("{families}");
  const separator = t("modelEncoderListSep");
  const full = t("modelEncoderPairs").replace("{families}", pairs.join(separator));
  return (
    <span data-encoder-pairs="" className={cn("block text-ui-xs text-muted-foreground", className)}>
      {/* 写不全(「等 N 种」)时悬停总给全部;都写出来了的,截断了才出说明 */}
      <Truncate hint={pairs.length > shown.length ? full : undefined}>
        {before}
        {shown.map((family, index) => (
          <React.Fragment key={family}>
            {index > 0 && separator}
            <span className={cn(active.includes(family) && "font-medium text-foreground")}>{family}</span>
          </React.Fragment>
        ))}
        {after}
      </Truncate>
    </span>
  );
}

/** 详情里「底模」那一行:「文本编码器 · T5-XXL」,下面一排常配的底模(勾着的那几种实色、排前面)。 */
export function EncoderOverview({ encoder }: { encoder: ModelEncoder }) {
  const t = useI18n();
  const active = React.useContext(ActiveFamiliesContext);
  const pairs = pairsFirst(encoder.pairs ?? [], active);
  return (
    <>
      <span className="flex">
        <CatalogBadge tone={encoder.kind && encoder.source === "weights" ? "primary" : "muted"}>
          {`${t("modelEncoderRole")} · ${encoder.kind ? encoder.label : t("modelEncoderUnknown")}`}
        </CatalogBadge>
      </span>
      {pairs.length > 0 && (
        <span className="flex min-w-0 flex-wrap items-center gap-1.5" aria-label={t("modelEncoderPairs").replace("{families}", pairs.join(t("modelEncoderListSep")))}>
          <span className="text-ui-xs text-muted-foreground">{t("modelEncoderPairsLabel")}</span>
          {pairs.map((family) => (
            <CatalogBadge key={family} tone={active.includes(family) ? "primary" : "muted"}>{family}</CatalogBadge>
          ))}
        </span>
      )}
    </>
  );
}

/**
 * 工作台里选文本编码器的那一格:这个文件不在节点现在那个 type 的配方里时标一枚「不在 wan 的配方里」(悬停说为什么)。合用的、
 * ComfyUI 不看 type 的、认不出是哪一种的不标。
 */
export function EncoderRecipeMark({ model, recipe }: { model: Pick<ModelFile, "encoder">; recipe: NodeEncoders | null }) {
  const t = useI18n();
  if (encoderFit(model, recipe) !== "misfit" || !recipe || !model.encoder) return null;
  const why = t("workbenchModelsNotInRecipeHint").replaceAll("{type}", recipe.type).replace("{kind}", model.encoder.label);
  return (
    <Hint label={why}>
      <span data-recipe-misfit="" className="inline-flex shrink-0">
        <CatalogBadge tone="warning">{t("workbenchModelsNotInRecipe").replace("{type}", recipe.type)}</CatalogBadge>
      </span>
    </Hint>
  );
}
