from pathlib import Path

class SkillContext:
    """
    技能上下文：当系统启动时，会把一些全局配置（比如数据存在哪个文件夹）
    打包在这个对象里，然后发给每一个技能插件。
    """
    def __init__(self, data_root: Path):
        self.data_root = data_root

class BaseSkill:
    """
    所有技能插件的“老祖宗”（基类）。
    规格书铁律：这里绝对不能 import streamlit！
    """
    name: str = "BaseSkill"
    version: str = "1.0.0"

    def healthcheck(self) -> dict[str, object]:
        """健康检查接口，用来告诉系统这个技能现在是不是正常的"""
        return {"ok": True, "detail": "基础技能模板已就绪"}