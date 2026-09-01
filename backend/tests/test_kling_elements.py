"""可灵的多图参考走「主体库」,不是把几张图挂在生成请求上。

别家的多图参考是一次性的:请求里挂几张图,这次用完就完了。可灵要你先用 2～4 张图**建一个
主体**(有名字、进主体库、能复用),拿到 element_id,生成时引用它。把它硬塞进"挂几张图"的
模型里,要么丢掉复用(每次重建、白扣积分),要么丢掉多图(只发第一张)。

这里钉的是那条翻译链上每一处**错了不会报错、只会安静地做错事**的地方。

**注意:可灵没有密钥可核。** 下面这些对着的是官方文档的形状,不是真机回话 —— 和火山/万相/
海螺那几家不一样。等有密钥了要按 test_capabilities_match_reality 的法子重核一遍。
"""

from __future__ import annotations

import pytest

from app.ai.providers.contracts.generation import GenerationRequest, ProviderError
from app.ai.providers.adapters.kuaishou import elements as kling_elements, kling


class Test建主体的请求体:
    def test_第一张是正面图_其余是其他角度(self) -> None:
        """文档要的是 frontal_image + refer_images 两个字段,不是一个平铺数组。
        拍平了发过去不会报错 —— 可灵只会当成没给正面图。"""
        payload = kling_elements.build_create_payload(["a.png", "b.png", "c.png"])
        assert payload["element_image_list"]["frontal_image"] == "a.png"
        assert payload["element_image_list"]["refer_images"] == [
            {"image_url": "b.png"},
            {"image_url": "c.png"},
        ]

    def test_少于两张建不起来(self) -> None:
        with pytest.raises(ProviderError, match="2～4 张"):
            kling_elements.build_create_payload(["only.png"])

    def test_多于四张也建不起来(self) -> None:
        with pytest.raises(ProviderError, match="2～4 张"):
            kling_elements.build_create_payload([f"{i}.png" for i in range(5)])

    def test_描述是必填的_空了要有兜底(self) -> None:
        """空字符串会被拒,而那时候图已经传上去了。"""
        assert kling_elements.build_create_payload(["a.png", "b.png"])["element_description"]

    def test_名字和描述都不能超长(self) -> None:
        payload = kling_elements.build_create_payload(["a.png", "b.png"], description="很长" * 200)
        assert len(payload["element_name"]) <= 20
        assert len(payload["element_description"]) <= 100


class Test同一组图复用同一个主体:
    def test_同样的图算出同样的名字(self) -> None:
        assert kling_elements.element_name_for(["a", "b"]) == kling_elements.element_name_for(["a", "b"])

    def test_换了顺序就是另一个主体(self) -> None:
        """第一张是正面图 —— 换个顺序,主体的正脸就换了,不能复用。"""
        assert kling_elements.element_name_for(["a", "b"]) != kling_elements.element_name_for(["b", "a"])

    def test_已删掉的主体不算数(self) -> None:
        """被删的主体照样留在列表里(status 是 deleted)。翻出它的 id 去生成会被拒,
        而错误信息说的是「主体不存在」—— 用户完全不知道那是我们自己翻出来的旧记录。"""
        name = kling_elements.element_name_for(["a", "b"])
        listing = {
            "data": [
                {"task_result": {"elements": [{"element_name": name, "element_id": 7, "status": "deleted"}]}}
            ]
        }
        assert kling_elements.find_element_id(listing, name) is None

    def test_还在的主体找得到(self) -> None:
        name = kling_elements.element_name_for(["a", "b"])
        listing = {
            "data": [
                {"task_result": {"elements": [{"element_name": name, "element_id": 7, "status": "succeed"}]}}
            ]
        }
        assert kling_elements.find_element_id(listing, name) == "7"


class Test建主体的轮询:
    def test_终态词是_succeed_不是_succeeded(self) -> None:
        """和生成任务那边差一个字母。照抄那份判断的话会一直轮询到超时,而主体其实早就建好了。"""
        assert kling_elements.extract_element_id({"data": {"task_status": "processing"}}) is None
        done = {"data": {"task_status": "succeed", "task_result": {"elements": [{"element_id": 42}]}}}
        assert kling_elements.extract_element_id(done) == "42"

    def test_失败直接抛_不要等超时(self) -> None:
        with pytest.raises(ProviderError):
            kling_elements.extract_element_id({"data": {"task_status": "failed", "task_status_msg": "风控"}})


class Test引用主体:
    def test_每个主体拿到一个任务内的索引名(self) -> None:
        """提示词里用 @名字 点它,文档要求同一任务里 id 不能重复。"""
        assert kling_elements.build_element_contents(["1", "2"]) == [
            {"type": "element", "element_id": "1", "id": "element_1"},
            {"type": "element", "element_id": "2", "id": "element_2"},
        ]

    def test_一次最多引三个(self) -> None:
        with pytest.raises(ProviderError, match="最多引用 3"):
            kling_elements.build_element_contents(["1", "2", "3", "4"])


class Test两代接口:
    def test_按型号分路(self) -> None:
        """多图参考只在 3.0 上有 —— 旧接口里根本没有承载它的字段。"""
        assert kling.uses_contents_array("kling-v3-omni")
        assert kling.uses_contents_array("kling-3.0-turbo")
        assert not kling.uses_contents_array("kling-v2-6")
        assert not kling.uses_contents_array("kling-v1-6")

    def test_端点跟着生成模式走_型号写在路径里(self) -> None:
        text = GenerationRequest(kind="video", model="kling-3.0-turbo", prompt="x")
        image = GenerationRequest(
            kind="video", model="kling-v3", prompt="x", parameters={"first_frame_url": "https://x/a.png"}
        )
        omni = GenerationRequest(kind="video", model="kling-v3-omni", prompt="x")
        assert kling.v3_endpoint(text).endswith("/text-to-video/kling-3.0-turbo")
        assert kling.v3_endpoint(image).endswith("/image-to-video/kling-3.0")
        assert kling.v3_endpoint(omni, has_elements=True).endswith("/omni-video/kling-3.0-omni")

    def test_普通版不能靠挂主体偷偷换成_omni(self) -> None:
        request = GenerationRequest(kind="video", model="kling-v3", prompt="x")
        with pytest.raises(ProviderError, match="Omni"):
            kling.v3_endpoint(request, has_elements=True)

    def test_新接口的请求体是_contents_数组(self) -> None:
        request = GenerationRequest(
            kind="video",
            model="kling-v3",
            prompt="@girl 奔跑",
            parameters={"first_frame_url": "https://x/a.png", "duration_seconds": 10, "resolution": "4k"},
        )
        payload = kling.build_v3_payload(request, element_ids=["173"])
        assert [one["type"] for one in payload["contents"]] == ["prompt", "first_frame", "element"]
        assert payload["settings"] == {"duration": 10, "resolution": "4k"}

    def test_文生视频发送宽高比_图生视频跟随首帧(self) -> None:
        text = GenerationRequest(
            kind="video", model="kling-v3", prompt="x", parameters={"aspect_ratio": "9:16"}
        )
        assert kling.build_v3_payload(text)["settings"]["aspect_ratio"] == "9:16"
        image = GenerationRequest(
            kind="video",
            model="kling-v3",
            prompt="x",
            parameters={"aspect_ratio": "9:16", "first_frame_url": "https://x/a.png"},
        )
        assert "aspect_ratio" not in kling.build_v3_payload(image)["settings"]

    def test_不支持仅尾帧(self) -> None:
        """文档原话:支持仅首帧和首尾帧,不支持仅尾帧。没首帧时尾帧要丢掉,
        发过去的下场是一个说不清楚的 400。"""
        request = GenerationRequest(
            kind="video", model="kling-v3", prompt="x", parameters={"last_frame_url": "https://x/b.png"}
        )
        assert [one["type"] for one in kling.build_v3_payload(request)["contents"]] == ["prompt"]

    def test_有声要显式开_不替用户默认打开(self) -> None:
        """有声比无声贵。"""
        quiet = GenerationRequest(kind="video", model="kling-v3", prompt="x", parameters={})
        assert "audio" not in kling.build_v3_payload(quiet)["settings"]
        loud = GenerationRequest(kind="video", model="kling-v3", prompt="x", parameters={"generate_audio": True})
        assert kling.build_v3_payload(loud)["settings"]["audio"] == "native"


class Test新接口的结果解析:
    def test_data_是数组_终态词也换了(self) -> None:
        """新接口查任务走统一的 /tasks(支持批量),回的是数组;终态是 `succeeded`,
        旧接口是 `succeed`。照抄旧那份的话一切都像"处理中",一直轮到超时。"""
        assert kling.extract_video_url_v3({"code": 0, "data": [{"status": "processing"}]}) is None
        done = {"code": 0, "data": [{"status": "succeeded", "outputs": [{"type": "video", "url": "https://x/v.mp4"}]}]}
        assert kling.extract_video_url_v3(done) == "https://x/v.mp4"

    def test_只认_video_那一项(self) -> None:
        """outputs 里可能同时有 video / image / audio / element,拿错了会下载到一张图。"""
        payload = {
            "code": 0,
            "data": [
                {
                    "status": "succeeded",
                    "outputs": [
                        {"type": "image", "url": "https://x/cover.png"},
                        {"type": "video", "url": "https://x/v.mp4"},
                    ],
                }
            ],
        }
        assert kling.extract_video_url_v3(payload) == "https://x/v.mp4"

    def test_失败直接抛(self) -> None:
        with pytest.raises(ProviderError):
            kling.extract_video_url_v3({"code": 0, "data": [{"status": "failed", "message": "风控"}]})
