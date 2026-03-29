import streamlit as st

# 导入我们刚刚写的后端管家，以及各种“暗号”
from src.services.session_backend import SessionBackend
from src.core.enums import UserIntent, LearningPhase

# ==========================================
# 1. 页面配置 (必须在第一行)
# ==========================================
st.set_page_config(page_title="LTA 循环导师", layout="wide")

# ==========================================
# 2. 初始化大管家 (利用 Streamlit 的缓存机制)
# ==========================================
# 这样保证每次刷新网页时，管家还是同一个，不会失忆
if "backend" not in st.session_state:
    st.session_state.backend = SessionBackend()

backend: SessionBackend = st.session_state.backend

# ==========================================
# 3. 读取当前进度
# ==========================================
app_state = backend.load_app_state()
learning = app_state.learning

# ==========================================
# 4. 开始画网页 UI
# ==========================================
st.title("🤖 循环导师 (LoopTutor)")
st.write(f"**欢迎回来**: {app_state.profile.display_name} 同学")

# 画一个进度条，告诉小朋友现在到哪一步了
phase_mapping = {
    LearningPhase.NOT_STARTED: 0.0,
    LearningPhase.LEARNING: 0.3,
    LearningPhase.PRACTICING: 0.6,
    LearningPhase.REVIEWING: 0.4,  # 如果在复习，进度条稍微退回一点
    LearningPhase.MASTERED: 1.0,
}
st.progress(phase_mapping.get(learning.current_phase, 0.0), text=f"当前阶段: {learning.current_phase}")
st.divider()

# 把页面分成左右两半：左边给小朋友看，右边给大人/开发者调试看
col_left, col_right = st.columns([2, 1])

with col_left:
    st.subheader("📺 学习区")
    
    # 状态 1：还没开始学
    if learning.current_phase == LearningPhase.NOT_STARTED:
        st.info("准备好开始新的探索了吗？")
        if st.button("🚀 开始学习", type="primary"):
            # 告诉管家：分配初始任务
            backend.handle_text_event(intent=UserIntent.NONE)
            st.rerun() # 刷新网页，让新状态生效

    # 状态 2：正在学习 或 正在复习
    elif learning.current_phase in [LearningPhase.LEARNING, LearningPhase.REVIEWING]:
        # 临时放一个网上的占位小视频，证明界面能播视频
        st.video("https://www.w3schools.com/html/mov_bbb.mp4")
        st.success("请认真观看教学视频哦！")
        
        # 规格书要求的大按钮：“我学完了”
        if st.button("✅ 我学完了！", type="primary"):
            backend.handle_text_event(intent=UserIntent.MARK_LEARNING_DONE)
            st.rerun()

    # 状态 3：正在练习
    elif learning.current_phase == LearningPhase.PRACTICING:
        st.warning("📝 练习时间到！")
        # 临时占位的假题目
        st.write("请问：在计算机里，1 + 1 等于几？") 
        
        user_answer = st.text_input("请输入你的答案：")
        
        # 规格书要求的大按钮：“提交答案”
        if st.button("📤 提交答案", type="primary"):
            # 这里的业务逻辑（对错判断、连错计次）全在后端大脑里，前端只负责当传声筒
            backend.handle_text_event(intent=UserIntent.SUBMIT_ANSWER, text=user_answer)
            st.rerun()
            
    # 状态 4：完全掌握
    elif learning.current_phase == LearningPhase.MASTERED:
        st.balloons() # 放个气球特效庆祝一下
        st.success("🎉 太棒了！你已经完全掌握了这个知识点！")

with col_right:
    # 这一块是用来验证后端真的在干活的监控器
    st.subheader("🛠️ 后台调试信息 (临时)")
    with st.expander("点击查看 state.json 实时内容", expanded=True):
        st.json(app_state.model_dump())