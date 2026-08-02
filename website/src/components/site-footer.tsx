import type { Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { SITE } from "@/lib/site";

export function SiteFooter({ locale }: { locale: Locale }) {
  const t = getMessages(locale);
  const year = new Date().getFullYear();

  return (
    <footer className="mt-24 border-t border-border/60">
      <div className="mx-auto flex max-w-5xl flex-col gap-4 px-6 py-10 text-sm text-muted-foreground sm:flex-row sm:items-center sm:px-8">
        <p className="m-0">
          <span className="text-foreground">Open Studio</span>
          <span className="mx-2 opacity-40">·</span>
          {t.footer.tagline}
        </p>
        <nav className="flex gap-5 sm:ml-auto">
          <a className="transition-colors hover:text-foreground" href={SITE.releases} target="_blank" rel="noreferrer">
            {t.footer.download}
          </a>
          <a className="transition-colors hover:text-foreground" href={SITE.repo} target="_blank" rel="noreferrer">
            {t.footer.github}
          </a>
          <a className="transition-colors hover:text-foreground" href={SITE.email}>
            {t.footer.contact}
          </a>
        </nav>
      </div>
      <div className="mx-auto max-w-5xl px-6 pb-10 text-xs text-muted-foreground/70 sm:px-8">
        © {year} Open Studio. {t.footer.rights}
      </div>
    </footer>
  );
}
