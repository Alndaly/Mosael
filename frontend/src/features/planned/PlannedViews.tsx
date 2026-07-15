import { BookOpen, Layers, Rocket } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { EmptyState } from "@/components/layout/EmptyState";

export function BatchView() {
  const t = useI18n();
  return (
    <div className="feature-view">
      <header className="feature-head">
        <div>
          <h1>{t("batchTitle")}</h1>
          <p>{t("batchDescription")}</p>
        </div>
      </header>
      <EmptyState icon={<Layers size={22} />} badge={t("plannedBadge")} title={t("batchEmptyTitle")} body={t("batchEmptyBody")} />
    </div>
  );
}

export function PublishView() {
  const t = useI18n();
  return (
    <div className="feature-view">
      <header className="feature-head">
        <div>
          <h1>{t("publishTitle")}</h1>
          <p>{t("publishDescription")}</p>
        </div>
      </header>
      <EmptyState icon={<Rocket size={22} />} badge={t("plannedBadge")} title={t("publishEmptyTitle")} body={t("publishEmptyBody")} />
    </div>
  );
}

export function KbView() {
  const t = useI18n();
  return (
    <div className="feature-view">
      <header className="feature-head">
        <div>
          <h1>{t("kbTitle")}</h1>
          <p>{t("kbDescription")}</p>
        </div>
      </header>
      <EmptyState icon={<BookOpen size={22} />} badge={t("plannedBadge")} title={t("kbEmptyTitle")} body={t("kbEmptyBody")} />
    </div>
  );
}
