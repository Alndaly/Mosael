"""内置模板「连续剧 · 系列设定」的图:剧名、梗概、集数、角色、场景(都由用的人定)→ 系列设定(分集大纲、角色、场景、画风)
→ 每个角色画三视图、配嗓子,每个场景画设定图,全部存进资产库 → 设定文档存成笔记。

连续剧(漫剧)要的是**跨集一致**:同一个人每一集是同一张脸、同一把嗓子。所以先把人和地方建进资产库,再逐集 / 逐场用
「从主题到完整视频」去拍 —— 整片的视觉圣经沿用库里的名字,三视图、设定图直接拿来用,台词按说话的角色配音(ADR 0096)。

用的人定多少就是多少:集数照填的写;填了的角色、场景名字一字不差、写了的特征照办;没填的由模型按梗概补。
库里已经有的同名人物 / 地点不重画,只给还没有嗓子的人物配上嗓子。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.ai.providers import VoiceCatalogContext, engine_voices, speech_engines
from app.domain.voices.speech import EDGE_ENGINE
from app.domain.workflows.node_types import NODE_TYPES
from app.domain.workflows.normalization import normalize_graph
from app.domain.workflows.templates_full_video import LOCATION_ART_PROMPT, TURNAROUND_PROMPT
from app.domain.workflows.templates_models import ModelChoice, image_plan_for
from app.domain.workflows.templates_schemas import object_schema

SERIES_SETUP = "series_setup"

#: 一部剧最多几集、几个主要角色、几个常用场景:大纲一次对话写得完,三视图、设定图的花费心里有数。
MAX_EPISODES = 60
MAX_CHARACTERS = 8
MAX_LOCATIONS = 6

#: 角色的嗓子从这几把里挑:免费、不用登录、每台机器都念得了的那个引擎(Edge,不要钥匙的那一个,同 voices.speech 的
#: EDGE_ENGINE)。经公共接口问它的内置音色目录,只取简体中文的。想换克隆音色或别的引擎,建好之后在资产库里改。
_FREE_ENGINE = next(engine for engine in speech_engines() if not engine.needs_key)
SERIES_VOICES = tuple(voice for voice in engine_voices(_FREE_ENGINE.engine_id, VoiceCatalogContext())
                      if voice.id.startswith("zh-CN-"))

DEFAULT_STYLE = (
    "Chinese guofeng anime style, 2D cel-shaded illustration with soft ink-wash textures, cinematic lighting, "
    "delicate line art."
)


def _series_schema() -> dict[str, Any]:
    episode = {
        "number": {"type": "integer", "minimum": 1},
        "title": {"type": "string"},
        "synopsis": {"type": "string", "description": "这一集发生了什么:起因、冲突、结尾的钩子,150 字以内"},
    }
    character = {
        "name": {"type": "string"},
        "role": {"type": "string", "description": "在故事里是谁:年龄、身份、性格"},
        "appearance": {
            "type": "string",
            "description": "英文,交给图像模型画三视图:年龄、脸型发型、服装与配色、体型与身高、标志性道具",
        },
        "voice": {"type": "string", "enum": [voice.id for voice in SERIES_VOICES], "description": "这个角色的嗓子"},
    }
    location = {
        "name": {"type": "string"},
        "description": {"type": "string", "description": "英文,交给图像模型画设定图:空间、时代、材质、关键陈设、光源、大致尺寸"},
    }
    fields = {
        "title": {"type": "string"},
        "logline": {"type": "string", "description": "一句话故事"},
        "style_prompt": {"type": "string", "description": "英文一句话的全剧画风,每一集每张图都带上"},
        "narrator_voice": {"type": "string", "enum": [voice.id for voice in SERIES_VOICES], "description": "旁白的嗓子"},
        "episodes": {"type": "array", "minItems": 1, "maxItems": MAX_EPISODES, "items": object_schema(episode, list(episode))},
        "characters": {"type": "array", "minItems": 1, "maxItems": MAX_CHARACTERS,
                       "items": object_schema(character, list(character))},
        "locations": {"type": "array", "minItems": 1, "maxItems": MAX_LOCATIONS,
                      "items": object_schema(location, list(location))},
        "bible_markdown": {
            "type": "string",
            "description": "给人读的系列设定文档(Markdown):一句话故事、画风、角色表(名字/身份/嗓子)、场景表、分集大纲",
        },
    }
    return object_schema(fields, list(fields))


def series_setup_graph(*, chat: ModelChoice, image: ModelChoice, db: Session | None = None) -> dict[str, Any]:
    """剧名 / 梗概 / 集数 / 角色 / 场景 → 系列设定 → 角色三视图 + 嗓子、场景设定图进资产库 → 设定文档进笔记。"""
    image_plan = image_plan_for(db, image)
    sheet_parameters = {"size": image_plan.sheet_size} if image_plan.sheet_size else {}
    voice_menu = "\n".join(f"- {voice.id}:{voice.label}" for voice in SERIES_VOICES)

    bible_system = f"""你是连续剧的总编剧兼美术总监。按用户给的剧名、梗概和集数，定下整部剧的系列设定。

- **集数照用户填的写**，episodes 恰好那么多集，number 从 1 连续编号；每集有自己的冲突，结尾留钩子，整部剧有完整的弧线。
- **角色、场景以用户填的为准**：用户列了的，name 一字不差、写了的特征照办，appearance / description 补成英文的画图描述；
  用户没列或没列全时，按梗概补上故事必需的主要角色(最多 {MAX_CHARACTERS} 个)、常用场景(最多 {MAX_LOCATIONS} 个)。
- 资产库里已经有的人物、地点会一并给你：故事里的就是其中某一个时，name 一字不差地沿用(它的图直接拿来用，不再重画)，
  appearance / description 照它的描述写；只是相像的不要硬套。
- 每个角色挑一把嗓子(voice)，按年龄、性别、性格挑，主要角色尽量不重样；用户写了想要哪把的照办。旁白另挑一把。
  可选的嗓子：
{voice_menu}
- style_prompt 用户写了画风就照它写成一句英文；没写就按题材定。
只输出符合 JSON Schema 的对象。"""

    def reuse_or_draw(kind: str, drawer: dict[str, Any], save: dict[str, Any]) -> dict[str, Any]:
        """库里按名字认:有图就不画。**存成资产每一项都跑**(不只新画的):库里已有的人物也要配上嗓子;它引用画图那一步,
        画图被跳过时照样等它落定、读到空串,只补嗓子不加图。"""
        return {
            "nodes": [
                {
                    "id": "find",
                    "type": "entity_get",
                    "name": {"zh": "在资产库里找", "en": "Look it up in the asset library"},
                    "position": {"x": 80, "y": 140},
                    "config": {"kind": kind, "name": "{{loop.item.name}}", "limit": 1},
                },
                {
                    "id": "has_art",
                    "type": "condition",
                    "name": {"zh": "库里有它的图吗", "en": "Does the library have its images?"},
                    "position": {"x": 380, "y": 140},
                    "config": {"left": "{{find.asset_ids.0}}", "op": "not_empty"},
                },
                {**drawer, "position": {"x": 680, "y": 240}},
                {**save, "position": {"x": 980, "y": 140}},
            ],
            "edges": [
                {"id": "find_check", "source": "find", "target": "has_art"},
                {"id": "missing_draw", "source": "has_art", "target": drawer["id"], "source_handle": "false"},
                {"id": "find_save", "source": "find", "target": "save"},
            ],
        }

    def drawer(node_id: str, zh: str, en: str, prompt: str) -> dict[str, Any]:
        return {
            "id": node_id,
            "type": "ai_generate",
            "name": {"zh": zh, "en": en},
            "config": {
                "provider": image.provider, "provider_profile_id": image.profile_id, "model": image.model,
                "kind": "image", "prompt": prompt, "parameters": sheet_parameters,
            },
        }

    character_body = reuse_or_draw(
        "character",
        drawer("sheet", "画这个角色的三视图", "Draw this character's turnaround", TURNAROUND_PROMPT),
        {
            "id": "save",
            "type": "entity_save",
            "name": {"zh": "存成人物资产,配上嗓子", "en": "Save as a character asset with its voice"},
            "config": {
                "kind": "character", "name": "{{loop.item.name}}", "prompt": "{{loop.item.appearance}}",
                "description": "{{loop.item.role}}", "asset_ids": "{{sheet.asset_id}}", "role": "turnaround",
                "engine": EDGE_ENGINE, "voice": "{{loop.item.voice}}", "tags": "{{input.title}}",
            },
        },
    )
    location_body = reuse_or_draw(
        "location",
        drawer("art", "画这个场景的设定图", "Paint this location's concept art", LOCATION_ART_PROMPT),
        {
            "id": "save",
            "type": "entity_save",
            "name": {"zh": "存成场景资产", "en": "Save as a location asset"},
            "config": {
                "kind": "location", "name": "{{loop.item.name}}", "prompt": "{{loop.item.description}}",
                "asset_ids": "{{art.asset_id}}", "tags": "{{input.title}}",
            },
        },
    )
    loop_inputs = {"style": "{{series_bible.json.style_prompt}}", "title": "{{series_bible.json.title}}"}

    nodes: list[dict[str, Any]] = [
        {
            "id": "start",
            "type": "start",
            "name": {"zh": "填写这部剧", "en": "Describe the series"},
            "position": {"x": 40, "y": 300},
            "config": {
                "params": {
                    "title": "",
                    "premise": "",
                    "episodes": 10,
                    #: 选填。一行一个,怎么写都行(「沈青禾:17 岁灯铺孤女,低辫子,嗓子要活泼的」);空着由模型按梗概定。
                    "characters": "",
                    "locations": "",
                    "style": DEFAULT_STYLE,
                    "language": "简体中文",
                },
                "required_params": ["title", "premise"],
            },
        },
        {
            "id": "library_characters",
            "type": "entity_list",
            "name": {"zh": "资产库里已有的人物", "en": "Characters already in the library"},
            "position": {"x": 340, "y": 120},
            "config": {"kind": "character", "limit": 30},
        },
        {
            "id": "library_locations",
            "type": "entity_list",
            "name": {"zh": "资产库里已有的地点", "en": "Locations already in the library"},
            "position": {"x": 340, "y": 480},
            "config": {"kind": "location", "limit": 30},
        },
        {
            "id": "series_bible",
            "type": "llm",
            "name": {"zh": "定下系列设定与分集大纲", "en": "Write the series bible and episode outline"},
            "position": {"x": 660, "y": 300},
            "config": {
                "profile_id": chat.profile_id,
                "model": chat.model,
                "preset": "creative",
                "system": bible_system,
                "prompt": """剧名：{{start.title}}
梗概：{{start.premise}}
集数：{{start.episodes}}
语言：{{start.language}}
画风：{{start.style}}

用户定的角色(可能为空)：
{{start.characters}}

用户定的场景(可能为空)：
{{start.locations}}

资产库里已有的人物：
{{library_characters.text}}

资产库里已有的地点：
{{library_locations.text}}""",
                "response_format": "json_schema",
                "json_schema_name": "series_bible",
                "json_schema": _series_schema(),
                "json_schema_strict": "true",
                "temperature": 0.8,
                "max_tokens": 16000,
            },
        },
        {
            "id": "character_assets",
            "type": "loop_foreach",
            "name": {"zh": "每个角色:库里没有就画三视图,存进资产库并配嗓子",
                     "en": "Every character: draw a turnaround if new, save it with its voice"},
            "position": {"x": 980, "y": 160},
            "config": {"items": "{{series_bible.json.characters}}", "inputs": loop_inputs, "body": character_body,
                       "output": "{{save.entity_id}}", "concurrency": 2},
        },
        {
            "id": "location_assets",
            "type": "loop_foreach",
            "name": {"zh": "每个场景:库里没有就画设定图,存进资产库",
                     "en": "Every location: paint concept art if new, save it"},
            "position": {"x": 980, "y": 440},
            "config": {"items": "{{series_bible.json.locations}}", "inputs": loop_inputs, "body": location_body,
                       "output": "{{save.entity_id}}", "concurrency": 2},
        },
        {
            "id": "bible_note",
            "type": "note_create",
            "name": {"zh": "设定文档存成笔记", "en": "Save the series bible as a note"},
            "position": {"x": 980, "y": 680},
            "config": {"title": "{{series_bible.json.title}} · 系列设定", "markdown": "{{series_bible.json.bible_markdown}}",
                       "tags": "{{series_bible.json.title}}"},
        },
        {
            "id": "output",
            "type": "output",
            "name": {"zh": "交付系列设定", "en": "Hand over the series bible"},
            "position": {"x": 1300, "y": 300},
            "config": {"values": {
                "title": "{{series_bible.json.title}}",
                "style_prompt": "{{series_bible.json.style_prompt}}",
                "narrator_voice": "{{series_bible.json.narrator_voice}}",
                "episodes": "{{series_bible.json.episodes}}",
                "characters": "{{character_assets.results}}",
                "locations": "{{location_assets.results}}",
                "note_id": "{{bible_note.note_id}}",
            }},
        },
    ]
    edges = [
        {"id": "start_library_characters", "source": "start", "target": "library_characters"},
        {"id": "start_library_locations", "source": "start", "target": "library_locations"},
        {"id": "start_bible", "source": "start", "target": "series_bible"},
        {"id": "library_characters_bible", "source": "library_characters", "target": "series_bible"},
        {"id": "library_locations_bible", "source": "library_locations", "target": "series_bible"},
        {"id": "bible_characters", "source": "series_bible", "target": "character_assets"},
        {"id": "bible_locations", "source": "series_bible", "target": "location_assets"},
        {"id": "bible_to_note", "source": "series_bible", "target": "bible_note"},
        {"id": "characters_output", "source": "character_assets", "target": "output"},
        {"id": "locations_output", "source": "location_assets", "target": "output"},
        {"id": "note_output", "source": "bible_note", "target": "output"},
    ]
    return normalize_graph(
        {"meta": {"template_id": SERIES_SETUP, "template_version": 1, "source": "official"}, "nodes": nodes, "edges": edges},
        node_types=NODE_TYPES,
    )


__all__ = ["MAX_CHARACTERS", "MAX_EPISODES", "MAX_LOCATIONS", "SERIES_SETUP", "SERIES_VOICES", "series_setup_graph"]
