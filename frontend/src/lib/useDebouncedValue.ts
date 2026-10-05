import React from "react";

/**
 * 停手 `delayMs` 之后才跟上的值。搜索框用它:输入框照常跟手,发给服务端的那个词等人停下来再换 ——
 * 否则敲「海边日落」是四次请求,前三次的结果回来就被扔掉。
 *
 * 清空(变成空串)不等:人删掉搜索词,是想马上看到全部。
 */
export function useDebouncedValue<T>(value: T, delayMs = 250): T {
  const [settled, setSettled] = React.useState(value);
  React.useEffect(() => {
    if (value === "" || Object.is(value, settled)) {
      setSettled(value);
      return;
    }
    const timer = window.setTimeout(() => setSettled(value), delayMs);
    return () => window.clearTimeout(timer);
    // settled 不进依赖:它变了不需要重新计时。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, delayMs]);
  return settled;
}
