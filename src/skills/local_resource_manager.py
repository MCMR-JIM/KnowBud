import json
import os
from pathlib import Path

# 导入我们的基础包
from src.skills.base_skill import BaseSkill, SkillContext
from src.core.enums import MediaKind

class LocalResourceManager(BaseSkill):
    """本地资源管理技能：负责查找和索引教学媒体文件"""
    
    name = "LocalResourceManager"
    version = "1.0.0"

    def __init__(self, ctx: SkillContext) -> None:
        self.ctx = ctx
        # 读取 .env 里配置的索引文件保存路径，如果没有就用默认的
        index_path_str = os.getenv("RESOURCE_INDEX_FILE", "./data/resource_index.json")
        self.index_file = Path(index_path_str)

    def rebuild_index(self) -> Path:
        """扫描本地目录，重建资源索引 JSON，并返回索引文件路径"""
        index_data = {}
        # 按照规格书约定的目录结构：{DATA_ROOT}/topics/
        topics_dir = self.ctx.data_root / "topics"
        
        if topics_dir.exists():
            for topic_path in topics_dir.iterdir():
                if topic_path.is_dir():
                    topic_id = topic_path.name
                    learn_dir = topic_path / "learn"
                    review_dir = topic_path / "review"
                    
                    # 收集 learn 和 review 目录下的视频和 PDF
                    learn_videos = [p.name for p in learn_dir.glob("*.mp4")] if learn_dir.exists() else []
                    review_pdfs = [p.name for p in review_dir.glob("*.pdf")] if review_dir.exists() else []
                    
                    index_data[topic_id] = {
                        "topic_id": topic_id,
                        "learn_videos": learn_videos,
                        "review_pdfs": review_pdfs
                    }
        
        # 确保存放 json 的 data 文件夹存在
        self.index_file.parent.mkdir(parents=True, exist_ok=True)
        
        # 把找出来的目录树写入 JSON
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(index_data, f, ensure_ascii=False, indent=2)
            
        return self.index_file

    def resolve(
        self,
        topic_id: str,
        media: MediaKind,
        *,
        prefer_review: bool,
    ) -> Path | None:
        """
        根据条件返回第一个匹配的文件路径。如果没找到返回 None。
        """
        base_dir = self.ctx.data_root / "topics" / topic_id
        
        # 如果要求优先复习，就先去 review 文件夹找，找不到再去 learn 文件夹
        sub_dirs = ["review", "learn"] if prefer_review else ["learn"]
        
        # 根据媒体类型决定要找什么后缀的文件
        ext = "*.mp4" if media == MediaKind.VIDEO else "*.pdf"
        if media == MediaKind.AUDIO:
            ext = "*.mp3"
            
        for sub in sub_dirs:
            target_dir = base_dir / sub
            if target_dir.exists():
                # glob 找出来的通常是一个列表，我们拿第一个匹配的就行
                for file_path in target_dir.glob(ext):
                    
                    # === 安全铁律：防止路径穿越攻击 (Path Traversal) ===
                    try:
                        resolved_path = file_path.resolve()
                        root_path = self.ctx.data_root.resolve()
                        # 确保最终找到的文件，真的是在 data_root 这个安全的沙箱里面
                        if resolved_path.is_relative_to(root_path):
                            return file_path
                    except ValueError:
                        continue
                        
        return None