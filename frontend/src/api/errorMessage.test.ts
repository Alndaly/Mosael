import { describe, expect, it } from "vitest";

import { humanError } from "@/api/errorMessage";

/**
 * 后端已经写好了一句给人看的话,别把它埋进 HTTP 噪音里。
 *
 * 用户看到的是这个:`422 Unprocessable Content: {"detail":"只有视频或音频素材可以转写"}`。
 * 唯一有用的是引号里那句,而它前面顶着状态码、状态短语、JSON 括号和 "detail" 这个键名 ——
 * 后三样对使用者没有任何意义,而它们占了大半屏。
 */
describe("接口报错", () => {
  it("拆出后端写的那句话", () => {
    expect(humanError(422, "Unprocessable Content", '{"detail":"只有视频或音频素材可以转写"}'))
      .toBe("只有视频或音频素材可以转写");
  });

  it("detail 是数组时(pydantic 校验)拼成人话", () => {
    const body = JSON.stringify({ detail: [{ loc: ["body", "name"], msg: "字段必填" }] });
    expect(humanError(422, "Unprocessable Content", body)).toContain("字段必填");
  });

  it("没有 detail 就退回状态码 —— 总比一句空话强", () => {
    expect(humanError(500, "Internal Server Error", "<html>oops</html>")).toContain("500");
  });

  it("完全没有 body 也不能是空串", () => {
    expect(humanError(503, "Service Unavailable", "")).toContain("503");
  });
});
