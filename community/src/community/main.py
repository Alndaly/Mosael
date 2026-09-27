"""uvicorn 的入口:`uv run uvicorn community.main:app --port 8900`。配置全部来自环境变量(见 config.py)。"""

from community.app import create_app

app = create_app()
