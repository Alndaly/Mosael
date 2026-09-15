"""用户自己写下的参数组。

内置目录装的是我们查证过的东西,而中转端点的组合装不完 —— 同一个 gemini 经两家中转,一家
支持尺寸和多张、另一家只支持尺寸。指向内置那份会**过度承诺**:界面摆出一个「张数」旋钮,
发出去被拒。这一层是让用户把只有他知道的那份写下来。

**代价也要说清**:这不是我们查证过的事实,是用户的断言。填错了不会当场报错,而是等到生成请求
被供应商拒掉。所以能在保存这一刻拦下的都要拦 —— 下面第一组测的就是这个。
"""
from __future__ import annotations

import pytest

from app.domain.generation.custom_profiles import CapabilityProfileError, validate_capabilities


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
