"""记账测试用的真实样本:从一台用户机器的用量表里只读取来,签名网址和提示词原文已去掉。

每一份都是**当时那次调用真实落库的形状** —— `units` 是请求侧计量叠上适配器读出来的那部分,
`raw` 是服务商的回包。记账规则改的是怎么读它们,所以测试要钉在真实形状上,而不是手写一个
「看起来差不多」的字典:真实回包里有 `input_tokens_details`、`usage.cost` 这种手写时想不起来的格。
"""

from __future__ import annotations

#: GPT Image 2(147ai 中转,OpenAI 兼容)纯文生图:19 个文字输入 token,196 个图像输出 token。
#: 当时只按请求侧估的 14 个输入 token 计了 $0.00007。
GPT_IMAGE_TEXT_ONLY = {
    "units": {
        "requests": 1,
        "input_characters": 16,
        "input_tokens": 14,
        "total_tokens": 14,
        "token_estimate": True,
        "images": 1,
        "source_images": 0,
        "size": "1024x1024",
    },
    "raw": {
        "created": 1784819690,
        "background": "opaque",
        "data": [{}],
        "output_format": "png",
        "quality": "low",
        "size": "1024x1024",
        "usage": {
            "input_tokens": 19,
            "input_tokens_details": {"image_tokens": 0, "text_tokens": 19},
            "output_tokens": 196,
            "output_tokens_details": {"image_tokens": 196, "text_tokens": 0},
            "total_tokens": 215,
        },
    },
}

#: gpt-image-2-client(147ai 自己的型号名)带两张参考图:1120 个图像输入 token、215 个文字输入、1756 个输出。
GPT_IMAGE_CLIENT_WITH_REFERENCES = {
    "units": {
        "requests": 1,
        "input_characters": 211,
        "input_tokens": 100,
        "total_tokens": 100,
        "token_estimate": True,
        "images": 1,
        "source_images": 2,
        "size": "1024x1024",
    },
    "raw": {
        "background": "auto",
        "created": 1788158534,
        "data": [{}],
        "moderation": "auto",
        "output_format": "png",
        "quality": "auto",
        "size": "1024x1024",
        "usage": {
            "input_tokens": 1335,
            "input_tokens_details": {"image_tokens": 1120, "text_tokens": 215},
            "output_tokens": 1756,
            "output_tokens_details": {"image_tokens": 1756, "text_tokens": 0},
            "total_tokens": 3091,
        },
    },
}

#: Evolink 上的 seedance-2.0-mini 图生视频,720p 5 秒。回包里有服务商自己报的扣费。
EVOLINK_SEEDANCE_MINI = {
    "units": {
        "requests": 1,
        "input_characters": 85,
        "input_tokens": 46,
        "total_tokens": 46,
        "token_estimate": True,
        "videos": 1,
        "video_seconds": 5.0,
        "resolution": "720p",
        "aspect_ratio": "1:1",
        "source_images": 1,
    },
    "raw": {
        "created": 1788194967,
        "duration": 206,
        "id": "task-unified-1788194967-nm4e99br",
        "model": "seedance-2.0-mini-image-to-video",
        "object": "video.generation.task",
        "progress": 100,
        "result_data": [{"url": "https://example.invalid/result.mp4"}],
        "results": ["https://example.invalid/result.mp4"],
        "status": "completed",
        "task_info": {"can_cancel": False},
        "type": "video",
        "usage": {"cost": {"credits": 13.5, "usd": 0.199, "cny": 1.35}, "credits_used": 13.5},
    },
}

#: 方舟 Seedance 2.0,480p 5 秒、带音频。当时适配器还没读 completion_tokens,账上是未定价。
SEEDANCE_480P_WITH_AUDIO = {
    "units": {
        "requests": 1,
        "input_characters": 145,
        "input_tokens": 112,
        "total_tokens": 112,
        "token_estimate": True,
        "videos": 1,
        "video_seconds": 5.0,
        "resolution": "480p",
        "aspect_ratio": "adaptive",
        "source_images": 0,
    },
    "raw": {
        "id": "cgt-20260923224745-bt5xs",
        "model": "doubao-seedance-2-0-260128",
        "status": "succeeded",
        "content": {"video_url": "https://example.invalid/result.mp4"},
        "usage": {"completion_tokens": 110902, "total_tokens": 110902},
        "created_at": 1790174871,
        "updated_at": 1790175102,
        "seed": 18707,
        "resolution": "480p",
        "ratio": "16:9",
        "duration": 5,
        "framespersecond": 24,
        "service_tier": "default",
        "execution_expires_after": 172800,
        "generate_audio": True,
        "draft": False,
        "priority": 0,
        "output_format": "mp4",
    },
}

#: 百炼 qwen-image 一次请求两张、当场被拒(2.4 秒):服务商什么都没回,当时按两张图计了 ¥0.5。
QWEN_IMAGE_REJECTED = {
    "units": {"requests": 1, "images": 2, "source_images": 0, "size": "1024x576"},
    "raw": {},
}
