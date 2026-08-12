import React from "react";

/**
 * 多选:选择模式 + 已选集合。**全项目只有这一份。**
 *
 * 素材页先有了一套(选择模式 / 已选 N 项 / 全选切换 / 批量动作 / 取消),发布记录与工作流
 * 照它做。抄第二遍、第三遍必然分叉,而分叉的地方恰好都不显眼:
 *
 *   - 退出选择模式**要清空已选** —— 漏了的话下次进来上一批还勾着,而批量删除照那批执行;
 *   - 「全选」作用于**当前可见**的那些(筛选/搜索之后),不是全库;
 *   - 选中的东西被删掉/被筛掉之后要自动不算数,否则批量动作会带着一批幽灵 id 发出去。
 *
 * 所以状态机收在这里,页面只负责自己的那几个批量按钮 —— 那部分本来就各不相同
 * (素材是对比/打标签/删除,工作流和发布是删除)。
 */
export function useMultiSelect<T>(items: readonly T[], idOf: (item: T) => string) {
  const [selectMode, setSelectMode] = React.useState(false);
  const [selectedIds, setSelectedIds] = React.useState<Set<string>>(new Set());

  // 列表变了(别人删了一条、筛选换了)就把已经不在的剔掉 —— 留着会让批量动作带上幽灵 id。
  const presentIds = React.useMemo(() => new Set(items.map(idOf)), [items, idOf]);
  React.useEffect(() => {
    setSelectedIds((current) => {
      const next = new Set([...current].filter((id) => presentIds.has(id)));
      return next.size === current.size ? current : next;
    });
  }, [presentIds]);

  const toggle = React.useCallback((id: string) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  /** 当前可见的这些是否已全选。**空列表不算全选** —— 否则按钮会写着「取消全选」。 */
  const allSelected = React.useCallback(
    (visible: readonly T[]) => visible.length > 0 && visible.every((item) => selectedIds.has(idOf(item))),
    [selectedIds, idOf],
  );

  /** 全选/取消全选当前可见的那些。 */
  const selectAll = React.useCallback(
    (visible: readonly T[]) => {
      setSelectedIds((current) => {
        const every = visible.length > 0 && visible.every((item) => current.has(idOf(item)));
        return every ? new Set() : new Set(visible.map(idOf));
      });
    },
    [idOf],
  );

  const clear = React.useCallback(() => setSelectedIds(new Set()), []);

  /** 退出选择模式:**顺带清空**。 */
  const exit = React.useCallback(() => {
    setSelectMode(false);
    setSelectedIds(new Set());
  }, []);

  return { selectMode, setSelectMode, selectedIds, toggle, selectAll, allSelected, clear, exit };
}
