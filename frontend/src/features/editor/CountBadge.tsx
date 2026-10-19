/**
 * 图标按钮右上角的小数字角标。
 *
 * 顶上的动作从「图标 + 文字」收成只有图标之后,「口癖 132」那个数字不能跟着文字一起消失 ——
 * 它是个有用的信号(这一下有 132 处会被选中),藏进悬停说明里就变成**常态看不见**。
 * 所以数字留在按钮上,占一格角标;按钮本身仍然只有图标,读屏名字照旧是 `aria-label`。
 *
 * `aria-hidden`:数字不是按钮的名字,名字由 `aria-label`(动作名)给;数量在 Hint 里也有一句。
 * `pointer-events-none`:点角标等于点按钮,不另起一块命中区。
 */
export function CountBadge({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <span
      aria-hidden
      data-count-badge=""
      className="pointer-events-none absolute -right-1 -top-1 h-[15px] min-w-[15px] rounded-full bg-primary px-1 text-center text-ui-2xs font-semibold leading-[15px] tabular-nums text-primary-foreground"
    >
      {count}
    </span>
  );
}
