"use client";

import {
  Toast,
  ToastClose,
  ToastDescription,
  ToastProvider,
  ToastTitle,
  ToastViewport,
} from "@/components/ui/toast";
import { useToast } from "@/components/ui/use-toast";

/**
 * 全站唯一的 toast 出口:表单里 `toast({ title })`,这里负责画出来。
 *
 * 它挂在 `[locale]/layout.tsx` —— `(site)` 与 `(auth)` 两组页面都从这一层继承,所以注册 / 登录 /
 * 账号页的成功提示和站内的「已保存」共用同一个 viewport,而不是每组、每页各挂一份。
 *
 * `label` / `closeLabel` 由布局按当前语言传进来(viewport 的 region 名、关闭按钮的读屏名),
 * 组件自己不写死任何一句文案。
 */
export function Toaster({ label, closeLabel }: { label: string; closeLabel: string }) {
  const { toasts, dismiss } = useToast();

  return (
    <ToastProvider label={label}>
      {toasts.map(({ id, title, description }) => (
        <Toast
          key={id}
          onOpenChange={(open) => {
            if (!open) dismiss(id);
          }}
        >
          <div className="grid min-w-0 gap-1">
            <ToastTitle>{title}</ToastTitle>
            {description ? <ToastDescription>{description}</ToastDescription> : null}
          </div>
          <ToastClose aria-label={closeLabel} />
        </Toast>
      ))}
      <ToastViewport />
    </ToastProvider>
  );
}
