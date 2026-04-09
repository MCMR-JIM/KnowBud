import json
from pydantic import ValidationError
from openai import OpenAI

from src.skills.base_skill import BaseSkill, SkillContext
from src.core.models import PendingQuestion, EvaluationResult

class LLMTutorSkill(BaseSkill):
    """大模型导师技能：负责根据知识点出题，以及批改儿童的答案"""
    
    name = "LLMTutorSkill"
    version = "1.0.0"

    def __init__(self, ctx: SkillContext, *, api_key: str, base_url: str, model: str) -> None:
        self.ctx = ctx
        self.model_name = model
        # 接入 OpenAI 兼容的 HTTP API (也支持改了 base_url 后的 DeepSeek/Ollama 等)
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def generate_question(self, *, topic_id: str, topic_title: str, difficulty: int) -> PendingQuestion:
        """根据知识点生成题目"""
        system_prompt = (
            "你是一个优秀的儿童家庭教师。请根据指定的知识点出一道练习题。\n"
            "【严禁废话】必须且只能输出合法的 JSON 格式，不要用 ```json 包裹。\n"
            "JSON 结构必须符合以下形式：\n"
            "{\n"
            '  "question_id": "随便生成一个唯一ID",\n'
            '  "stem": "题干内容，要通俗易懂",\n'
            '  "choices": ["选项A", "选项B"] (如果是选择题) 或者 null (如果开放问答),\n'
            '  "expected_format": "open" 或 "single_choice" 或 "multi_choice"\n'
            "}"
        )
        user_prompt = f"请出题。知识点：{topic_title} (ID:{topic_id}), 难度：{difficulty}。"

        return self._call_and_parse(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_class=PendingQuestion,
            fallback_obj=None # 出题失败直接抛出，由上层处理
        )

    def evaluate_answer(self, *, question: PendingQuestion, user_answer: str) -> EvaluationResult:
        """根据题目和孩子的回答，进行批改"""
        system_prompt = (
            "你是一个富有耐心的儿童老师。请批改学生的答案。\n"
            "【严禁废话】必须且只能输出合法的 JSON 格式，不要用 ```json 包裹。\n"
            "JSON 结构必须包含以下字段：\n"
            "{\n"
            '  "is_correct": true 或 false,\n'
            '  "error_type": "错误类型，比如 concept(概念错误) 或 null",\n'
            '  "feedback_text": "用温柔、鼓励的语气给儿童看的简短评语"\n'
            "}"
        )
        user_prompt = f"题目：{question.stem}\n学生回答：{user_answer}\n请批改。"
        
        # 规格书要求的保守降级对象：就算天塌下来，也要返回这个兜底结果
        fallback = EvaluationResult(
            is_correct=False,
            error_type="expression",
            feedback_text="系统繁忙，请重试"
        )

        return self._call_and_parse(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_class=EvaluationResult,
            fallback_obj=fallback
        )

    def _call_and_parse(self, system_prompt: str, user_prompt: str, model_class, fallback_obj):
        """内部通用的：发请求 -> 清理数据 -> Pydantic 校验 -> 失败重试 1 次逻辑"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # 循环 2 次：第 1 次是正常请求，第 2 次是重试请求
        for attempt in range(2):
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=0.3 # 降低温度，让它输出 JSON 更稳定
                )
                raw_content = response.choices[0].message.content.strip()
                
                # 暴力清理大模型有时候手贱加的 markdown 标记
                if raw_content.startswith("```json"):
                    raw_content = raw_content[7:]
                if raw_content.startswith("```"):
                    raw_content = raw_content[3:]
                if raw_content.endswith("```"):
                    raw_content = raw_content[:-3]
                    
                # 关键：用我们在 T2 定义的 Pydantic 模型去校验它！
                return model_class.model_validate_json(raw_content.strip())
                
            except (ValidationError, json.JSONDecodeError) as e:
                if attempt == 0:
                    # 第一次失败了，把脏数据发给它，命令它修好
                    messages.append({"role": "assistant", "content": raw_content if 'raw_content' in locals() else "无输出"})
                    messages.append({"role": "user", "content": f"解析失败：{e}。请修复为合法 JSON。"})
                else:
                    # 第二次还失败，记录日志，并启动兜底降级
                    print(f"[LLMTutorSkill] 连续两次解析失败，触发降级: {e}")
                    if fallback_obj is not None:
                        return fallback_obj
                    raise e