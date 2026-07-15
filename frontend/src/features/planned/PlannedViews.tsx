import { BookOpen, Layers, Rocket } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { EmptyState } from "@/components/layout/EmptyState";

export function BatchView() {
  const t = useI18n();
  return (
    <div className="feature-view">
      <EmptyState icon={<Layers size={22} />} badge={t("plannedBadge")} title={t("batchEmptyTitle")} body={t("batchEmptyBody")} />
    </div>
  );
}

export function PublishView() {
  const t = useI18n();
  return (
    <div className="feature-view">
      <EmptyState icon={<Rocket size={22} />} badge={t("plannedBadge")} title={t("publishEmptyTitle")} body={t("publishEmptyBody")} />
    </div>
  );
}

export function KbView() {
  const t = useI18n();
  return (
    <div className="feature-view">
      <EmptyState icon={<BookOpen size={22} />} badge={t("plannedBadge")} title={t("kbEmptyTitle")} body={t("kbEmptyBody")} />
    </div>
  );
}
