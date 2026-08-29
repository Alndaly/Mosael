import React from "react";

/**
 * 「点下去到这件事有下文」之间的那段。
 *
 * 两头都容易漏,而漏了都不报错:
 *
 *  · **点下去要立刻转圈**,不等服务端回来 —— 一次往返几百毫秒,这期间按钮毫无变化,
 *    用户会以为没点上,再点一次(于是发两遍)。
 *  · **失败了要停下来。** 只在开头 setTrue、指望面板自己消失的话,一旦失败面板还在,
 *    那个圈就永远转下去 —— 用户既不知道失败了,也再点不动第二次。
 *
 * 画板上四张表单(图片/视频、文案、音频、剪辑)都要这一段,所以只写一遍。
 */
export function useSubmitting(): {
  submitting: boolean;
  /** 跑一次;不管成功还是失败都会停下来。回调返回 Promise 时等它落地。 */
  run: (task: () => unknown) => void;
} {
  const [submitting, setSubmitting] = React.useState(false);
  //: 卸载之后别再 setState —— 成功那一路面板通常已经收起来了。
  const alive = React.useRef(true);
  React.useEffect(() => () => void (alive.current = false), []);

  const run = React.useCallback((task: () => unknown) => {
    setSubmitting(true);
    let result: unknown;
    try {
      result = task();
    } catch {
      setSubmitting(false);
      return;
    }
    //: 用 then(done, done) 而不是 finally —— finally 会把这个 rejection 继续往外抛,
    //: 变成一条没人接的 unhandled rejection。失败本身由调用方自己弹提示,这里只负责停下来。
    const done = () => {
      if (alive.current) setSubmitting(false);
    };
    void Promise.resolve(result).then(done, done);
  }, []);

  return { submitting, run };
}
