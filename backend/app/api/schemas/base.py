"""Shared schema primitives; domain slices are assembled by ``app.api.schemas``."""

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """所有请求/响应体的基类。存在的理由只有一条:**拒收非有限的数**。

    `NaN` / `Infinity` 不是合法 JSON(RFC 8259 里没有它们),但 Python 的 json 认,而 pydantic
    对 float 字段默认也放行。于是每一个 float 字段都是一个入口 —— 全后端有七十个。

    进来之后的代价不对称,而且发作得很晚:

    · 存下的 NaN 序列化回去是 `{"x": NaN}`,浏览器 `JSON.parse` 直接抛 —— 那条时间线、
      那张画板从此打不开,而库里的数据其实是完好的;
    · `src_out = Infinity` 是一段无限长的片段,它会一路进到渲染计划里。

    **而且用比较去挡是挡不住的**:任何和 NaN 的比较都是 False,所以 `x < 0` / `x <= y`
    这类判据对 NaN 全部"满足"。挡它必须显式问一句是不是有限 —— 与其指望七十处各自记得,
    不如在进门这一层一次挡掉。
    """

    model_config = ConfigDict(allow_inf_nan=False)


class OrmModel(ApiModel):
    model_config = ConfigDict(from_attributes=True, allow_inf_nan=False)
