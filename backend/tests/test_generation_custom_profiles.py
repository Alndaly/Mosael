"""用户自己写下的参数组。

内置目录装的是我们查证过的东西,而中转端点的组合装不完 —— 同一个 gemini 经两家中转,一家
支持尺寸和多张、另一家只支持尺寸。指向内置那份会**过度承诺**:界面摆出一个「张数」旋钮,
发出去被拒。这一层是让用户把只有他知道的那份写下来。

**代价也要说清**:这不是我们查证过的事实,是用户的断言。填错了不会当场报错,而是等到生成请求
被供应商拒掉。所以能在保存这一刻拦下的都要拦 —— 下面第一组测的就是这个。
"""
from __future__ import annotations

import pytest

from app.domain.generation.custom_profiles import (
    CapabilityProfileError,
    _KNOWN_KEYS,
    canonical_parameters,
    validate_capabilities,
)


class Test保存时拦得住的那些:
    """拦的是**形状**,不是**事实**。判得出 sizes 必须是一串字符串;判不出这个端点真的支持
    4 张 —— 后者只有端点自己知道。"""

    def test_合法的原样收下(self) -> None:
        raw = {
            "parameter_keys": ["size", "num_images"],
            "sizes": ["1024x1024", "1024x1536"],
            "default_size": "1024x1024",
            "max_num_images": 4,
        }
        assert validate_capabilities(raw, "image") == raw

    def test_不认得的键要点名说是哪个(self) -> None:
        """白名单而不是黑名单:`sizes` 写成 `size` 不会报错,只会安静地什么都不生效 ——
        那正是这个仓库一直在消灭的那种沉默。而且要说出是哪个键:对着三十几个字段的表单,
        「格式不对」这种话毫无用处。"""
        with pytest.raises(CapabilityProfileError, match="size"):
            validate_capabilities({"parameter_keys": ["size"], "size": ["1024x1024"]}, "image")

    def test_一个参数都不声明等于没设(self) -> None:
        """空的参数组和兜底是一回事 —— 指它和不指一样,却让人以为设过了。"""
        with pytest.raises(CapabilityProfileError, match="parameter_keys"):
            validate_capabilities({"parameter_keys": [], "sizes": ["1024x1024"]}, "image")

    def test_默认值必须在自己那份清单里(self) -> None:
        """界面拿它当初值;不在清单里就是一个选不回来的值。"""
        with pytest.raises(CapabilityProfileError, match="default_size"):
            validate_capabilities(
                {"parameter_keys": ["size"], "sizes": ["1024x1024"], "default_size": "2048x2048"}, "image"
            )

    @pytest.mark.parametrize(
        "raw",
        [
            {"parameter_keys": ["size"], "max_num_images": 0},
            {"parameter_keys": ["size"], "max_num_images": True},
            {"parameter_keys": ["size"], "source_limits": {"reference_image": "很多"}},
            {"parameter_keys": ["size"], "sizes": "1024x1024"},
            {"parameter_keys": ["size"], "duration_seconds": ["4"]},
        ],
    )
    def test_形状不对的值(self, raw: dict) -> None:
        with pytest.raises(CapabilityProfileError):
            validate_capabilities(raw, "image")

    def test_kind只能是那两种(self) -> None:
        with pytest.raises(CapabilityProfileError):
            validate_capabilities({"parameter_keys": ["size"]}, "audio")


class Test表单结构描述端点:
    """可视表单的结构由后端这一份描述驱动 —— 它要是和保存校验的白名单分家,
    表单放行的字段保存时被拒,或者能保存的字段表单里根本没有。"""

    def test_字段集就是保存校验的白名单(self) -> None:
        from tests.util import fresh_client

        client = fresh_client()
        body = client.get("/api/generation/capability-profile-schema").json()

        assert {field["key"] for field in body["fields"]} == set(_KNOWN_KEYS)
        assert {field["shape"] for field in body["fields"]} == set(_KNOWN_KEYS.values())
        #: 每个字段都得有分组 —— 漏了的话表单里它会掉出所有区块,谁都看不见。
        assert all(field["group"] for field in body["fields"])

    def test_参数与角色按kind分(self) -> None:
        """image 的表单不该摆出 video 的参数:声明一个这个 kind 没人会发的参数,
        只会让用户以为界面会多一个旋钮。保存校验用同一份 —— 表单和校验不分家。"""
        from tests.util import fresh_client

        client = fresh_client()
        image = client.get("/api/generation/capability-profile-schema?kind=image").json()
        video = client.get("/api/generation/capability-profile-schema?kind=video").json()

        assert image["parameters"] == canonical_parameters("image")
        assert video["parameters"] == canonical_parameters("video")
        assert "size" in image["parameters"]
        assert "duration_seconds" not in image["parameters"]
        assert "duration_seconds" in video["parameters"]
        assert "reference_video" not in image["source_roles"]
        assert "reference_video" in video["source_roles"]
        #: 有枚举值的参数单列 —— 「参数可选值」那一组只在选了它们时才该出现。
        assert "quality" in image["enum_parameters"]

    def test_每一格默认值都说得出自己是谁的(self) -> None:
        """界面据此决定"这个旋钮要不要配一格默认值"。

        此前这份知识抄在前端:一张写死的名单,上面只有 size / resolution / aspect_ratio /
        duration 和两个开关 —— 于是用户声明完 quality 的可选值之后,没有任何地方可以设
        default_quality,而保存校验一直收这个键。抄一份就会漏,这是漏掉的那几个。
        """
        from tests.util import fresh_client

        body = fresh_client().get("/api/generation/capability-profile-schema?kind=image").json()
        defaults = [field for field in body["fields"] if field["group"] == "defaults"]
        assert defaults, "defaults 组空了"
        for field in defaults:
            assert field["defaults_for"], f"{field['key']} 说不出自己是谁的默认值"
            assert field["key"] == f"default_{field['defaults_for']}"
        #: 那几个此前被名单漏掉的,现在在册。
        named = {field["defaults_for"] for field in defaults}
        assert {"quality", "background", "output_format", "moderation"} <= named

    def test_别的组不冒充默认值(self) -> None:
        """defaults_for 只有 defaults 组有 —— 别的组带上它,界面会把它当成一格默认值摆出来。"""
        from tests.util import fresh_client

        body = fresh_client().get("/api/generation/capability-profile-schema").json()
        for field in body["fields"]:
            if field["group"] != "defaults":
                assert field["defaults_for"] is None, field["key"]
                #: 名字本身就是那层关系,所以反过来也得成立 —— `default_` 开头的键必须在
                #: defaults 组里。破了这一条,那个键要么被当成默认值摆错地方,要么静默消失。
                assert not field["key"].startswith("default_"), field["key"]

    def test_可选值装在哪个键里由这里说(self) -> None:
        """界面此前也抄了一份 {size: "sizes", …}。它和 _KNOWN_KEYS 分家的后果是静默的:
        指向一个不存在的键,那一格可选值编辑器就永远是空的。"""
        from tests.util import fresh_client

        client = fresh_client()
        for kind in ("image", "video"):
            body = client.get(f"/api/generation/capability-profile-schema?kind={kind}").json()
            mapping = body["choices_key"]
            assert mapping["size"] == "sizes" and mapping["duration_seconds"] == "duration_seconds"
            for parameter, key in mapping.items():
                assert key in _KNOWN_KEYS, f"{parameter} 指向的 {key} 不是认得的键"
            #: 有专属清单的和走 parameter_choices 的**两个 kind 都**不能重叠 —— 同一个参数
            #: 两个取值来源必然对不上,而 quality 只在 image 那边是枚举参数。
            assert not (set(mapping) & set(body["enum_parameters"])), kind

    def test_别种kind的参数在保存时拦下(self) -> None:
        """video 专属的 duration_seconds 塞进 image 参数组,此前靠全 kind 并集漏过。"""
        with pytest.raises(CapabilityProfileError, match="duration_seconds"):
            validate_capabilities({"parameter_keys": ["duration_seconds"]}, "image")


class Test自定义档案参与解析:
    def test_自定义与内置在同一个命名空间里各自解析(self) -> None:
        from app.domain.generation import resolve_capability_ref

        custom = {"abc": {"parameter_keys": ["size"]}}
        assert resolve_capability_ref("profile:abc", "image", custom=custom) == {"parameter_keys": ["size"]}
        assert resolve_capability_ref("profile:openai-image", "image", custom=custom) is not None

    def test_没带自定义名册时解析不到(self) -> None:
        """一份参数组只在它所属的那条连接里有意义。别的连接指过来解析不到,于是落回兜底并
        在界面上显示"还没认出来" —— 比悄悄套用另一条连接的断言要好。"""
        from app.domain.generation import resolve_capability_ref

        assert resolve_capability_ref("profile:abc", "image") is None


class Test参数组跟着连接走:
    """归属这件事跟着连接走就够了,不必再发明一层。

    连接本来就是按人的(ProviderProfile.owner_user_id),而参数组描述的正是「这条连接后面那个
    端点接受什么」—— 两者同生共死。这条钉的是那个决定的两个后果:删连接一起清、跨连接指不到。
    """

    @staticmethod
    def _connection(db, name: str):
        from app.db.models import ProviderProfile

        row = ProviderProfile(name=name, vendor="openai-compatible", owner_user_id="someone")
        db.add(row)
        db.commit()
        return row

    @staticmethod
    def _profile(db, connection_id: str, name: str, kind: str = "image"):
        from app.db.models import GenerationCapabilityProfile

        row = GenerationCapabilityProfile(
            provider_profile_id=connection_id, name=name, kind=kind,
            capabilities={"parameter_keys": ["size"]},
        )
        db.add(row)
        db.commit()
        return row

    def test_删连接时一起清掉(self) -> None:
        """FK + ondelete CASCADE。不清的话会留下指向虚空的孤儿 —— 它们永远不会再被任何界面
        列出来,只是占着位置。"""
        from sqlalchemy import select

        from app.core.db import SessionLocal
        from app.db.models import GenerationCapabilityProfile
        from tests.util import fresh_client

        fresh_client()
        with SessionLocal() as db:
            connection = self._connection(db, "一次性连接")
            row_id = self._profile(db, connection.id, "一次性参数组").id
            db.delete(connection)
            db.commit()
            assert db.scalar(
                select(GenerationCapabilityProfile).where(GenerationCapabilityProfile.id == row_id)
            ) is None

    def test_按连接取而不是全局取(self) -> None:
        """别的连接指过来的 id 解析不到 —— 于是落回兜底并在界面上显示"还没认出来",
        比悄悄套用另一条连接的断言要好。"""
        from app.core.db import SessionLocal
        from app.domain.generation.custom_profiles import custom_capabilities_map
        from tests.util import fresh_client

        fresh_client()
        with SessionLocal() as db:
            a = self._connection(db, "连接甲")
            b = self._connection(db, "连接乙")
            row = self._profile(db, a.id, "甲的组")

            assert row.id in custom_capabilities_map(db, a.id, "image")
            assert row.id not in custom_capabilities_map(db, b.id, "image")
            #: kind 也分得开 —— 图片的尺寸清单套到视频上是另一套东西。
            assert row.id not in custom_capabilities_map(db, a.id, "video")
