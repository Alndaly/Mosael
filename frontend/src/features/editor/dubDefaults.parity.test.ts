/**
 * 配音默认值的前端一侧和后端是同一个。
 *
 * 此前剪辑台「压进原字幕长度」默认关,智能体、工作流、MCP 默认开:同一条时间线从两个入口配,一个对得上画面、
 * 一个一路念过下一句。默认值归后端领域层(subtitle_dub.DEFAULT_MATCH_DURATION),它经接口模型的默认值
 * 进 openapi.json;前端这份常量对着它比。
 */
import { describe, expect, it } from "vitest";

import openapi from "../../../../backend/openapi.json";
import { DEFAULT_MATCH_DURATION } from "@/api/domains/speech";

describe("字幕配音的默认值", () => {
  it("压进原字幕长度:剪辑台和后端领域层是同一个默认", () => {
    const schema = (openapi as { components: { schemas: Record<string, { properties: Record<string, { default?: unknown }> }> } })
      .components.schemas.SubtitleDubRequest;
    expect(schema.properties.match_duration.default).toBe(DEFAULT_MATCH_DURATION);
  });
});
