"""「下载源」这一栏的每一项,都必须真的换一条路。

这条判据的由来值得记着,因为中间我下过一个错误的结论:

1. 最初 `HF_ENDPOINTS` 里三项,而 `modelscope` 指向 `https://huggingface.co` —— 和 `hf`
   一模一样。选它和选「HuggingFace」是同一件事,只是名字不同。用户按名字以为走的是国内源。
2. 我先给它挂长括号解释"它其实不是它",又改成按引擎条件渲染;而条件渲染的下拉项撞上
   Radix 的硬约束(当前值找不到对应 Item 时把值清空并回调),于是**每次刷新表单自己变脏**
   —— 用户报的「每次刷新页面下载源都会变动,导致要重新保存」。
3. 我于是删掉了这个选项,理由是"它什么都没做"。**这一步错了。** 那句话对当时的实现成立,
   但由它推出"这个选项没有意义"不成立 —— 用户机器上实测:

       huggingface.co   46 KB/s      hf-mirror.com   46 KB/s      modelscope.cn  ~9 MB/s

   同样 9 GB,一个是 55 小时,一个是 14 分钟。用户当初选它是对的,是实现没跟上,
   而我把界面上那个正确的选择删了。
4. 正确的做法是**让它真的走 ModelScope**(见 test_modelscope_is_a_real_source)。

留下来的不变量只有一条,但它把上面整段都挡住了:**这一栏里的两项不能落到同一个地方。**
落到同一个地方的那一项,不是选项,是装饰;而装饰会被用户当成决定。
"""

from __future__ import annotations

from app.ai.runtime import tts_models
from app.domain import tts_config


def test_every_endpoint_is_distinct() -> None:
    endpoints = list(tts_config.HF_ENDPOINTS.values())
    assert len(endpoints) == len(set(endpoints)), tts_config.HF_ENDPOINTS


def test_modelscope_is_not_an_hf_endpoint() -> None:
    """它不是"另一个 URL",是另一个客户端 —— 塞进这张表就等于什么都没做。"""
    assert "modelscope" not in tts_config.HF_ENDPOINTS


def test_but_it_is_still_offered_where_it_works() -> None:
    """删掉的是那张表里的假条目,不是这个选项本身。"""
    assert "modelscope" in tts_models.sources_for("fish-speech")


def test_no_source_is_silently_rewritten_anymore() -> None:
    """迁移表现在是空的:modelscope 成了真的,不该再被换成别的。

    「等价才迁」—— 一次不等价的迁移就是替用户改了设置,而这台机器上那正好是把一条
    9 MB/s 的路换成 46 KB/s 的路。
    """
    assert tts_config._LEGACY_SOURCES == {}
