import { notFound } from "next/navigation";

import { NavProgress } from "@/components/nav-progress";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { isLocale } from "@/i18n/config";

/**
 * 站内页面共用的外壳。
 *
 * 浮在内容之上的站头、站尾都只属于这一组 —— 账号页(登录 / 注册 / 账号)在隔壁 `(auth)`,
 * 顶部没有整站导航。分组名带括号,不进入 URL:`/zh`、`/zh/docs/...`、`/en/plugins/...` 一个都没变。
 *
 * `pt-20` 是给悬浮站头留的呼吸位:站头是 `fixed` 的,不占文档流。首页再用负 margin 把品牌渐变
 * 从这 5rem 后面一直延伸到视口顶。这个留白跟着站头一起搬进来,根布局不再关心它。
 */
export default async function SiteLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  // 动态段什么字符串都收得下,`/fr/docs/...` 不该渲染出一个中文页来。
  if (!isLocale(locale)) notFound();

  return (
    <>
      <NavProgress />
      <SiteHeader locale={locale} />
      <main id="main" className="pt-20">
        {children}
      </main>
      <SiteFooter locale={locale} />
    </>
  );
}
