# app.py - 儿童AI学习伴侣 (完全对接后台版)
import streamlit as st
import time
from design import COMPANIONS, get_global_css
from src.services.session_backend import SessionBackend
from src.core.enums import UserIntent, LearningPhase

st.set_page_config(page_title="AI星梦乐园", page_icon="✨", layout="wide")
st.markdown(get_global_css(), unsafe_allow_html=True)

# ==========================================
# 1. 唤醒大管家，读取真实记忆
# ==========================================
if "backend" not in st.session_state:
    st.session_state.backend = SessionBackend()
backend: SessionBackend = st.session_state.backend

app_state = backend.load_app_state()
learning = app_state.learning
# 动态获取当前的知识点名称
current_topic = app_state.curriculum.topics[0].title if app_state.curriculum.topics else "自由探索"

if "companion" not in st.session_state:
    st.session_state.companion = "小智龙 🦖" # 默认小智龙

# ==========================================
# 2. 侧边栏：干掉假路由，只留伴学配置和真进度
# ==========================================
with st.sidebar:
    st.markdown("<h1 style='text-align:center; color:#2C3E50;'>✨星梦乐园</h1>", unsafe_allow_html=True)
    st.markdown("---")
    
    st.markdown("### 🏆 我的百宝箱")
    phase_mapping = {
        LearningPhase.NOT_STARTED: 0,
        LearningPhase.LEARNING: 30,
        LearningPhase.PRACTICING: 60,
        LearningPhase.REVIEWING: 40,
        LearningPhase.MASTERED: 100
    }
    real_progress = phase_mapping.get(learning.current_phase, 0)
    
    st.markdown(f"**当前阶段: {learning.current_phase}**")
    st.markdown(f"""
        <div style='background:rgba(255,255,255,0.6); padding:15px; border-radius:15px; border:2px solid white;'>
            <p style='margin:0; font-size:18px;'>🌟 智慧星: {real_progress // 20} 颗</p>
            <p style='margin:0; font-size:18px;'>🏅 能量值: {real_progress}%</p>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("### 🧩 伴学配置")
    st.session_state.companion = st.selectbox(
        "选择你的好朋友", 
        list(COMPANIONS.keys()), 
        index=list(COMPANIONS.keys()).index(st.session_state.companion)
    )
    st.info("🧑‍🏫 家长管理请点击左侧栏上方的 '1 Admin Dashboard'")

# ==========================================
# 3. 主界面：人物问候与沉浸式学习舱
# ==========================================
comp_info = COMPANIONS[st.session_state.companion]
st.markdown(f"""
<div class="floating-avatar">{comp_info['avatar']}</div>
<div class="speech-bubble">{comp_info['greeting']}</div>
""", unsafe_allow_html=True)

col_main, col_action = st.columns([7, 3], gap="large")

with col_main:
    html_content = f"""
    <div class="learning-cabin">
        <h3 style='color: #2C3E50; margin-top:0; text-align:center;'>🚀 {current_topic}</h3>
        <div style="height: 320px; background: rgba(0,0,0,0.8); border-radius: 20px; display: flex; flex-direction: column; align-items: center; justify-content: center; box-shadow: inset 0 0 30px rgba(0,0,0,0.5);">
            <h2 style="color: white; text-shadow: 0 0 10px #A18CD1;">📺 本地动画 / 课件播放区</h2>
            <p style="color: #FF9A9E; margin-top: 10px;">(系统内部状态: {learning.current_phase})</p>
        </div>
        <br>
        <p style="color: #666; font-weight:bold; margin-bottom: 5px;">🔥 当前能量值</p>
        <div class="energy-container">
            <div class="energy-fill" style="width: {real_progress}%;">⭐</div>
        </div>
    </div>
    """
    st.markdown(html_content, unsafe_allow_html=True)

# ==========================================
# 4. 核心对接：千变万化的魔法按钮
# ==========================================
with col_action:
    st.markdown(f"### 🪄 魔法按钮")
    
    # 状态 1：还没开始
    if learning.current_phase == LearningPhase.NOT_STARTED:
        st.info("准备好起飞了吗？")
        if st.button("🚀 开始学习", use_container_width=True):
            backend.handle_text_event(intent=UserIntent.NONE)
            st.rerun()

    # 状态 2：学习或复习中
    elif learning.current_phase in [LearningPhase.LEARNING, LearningPhase.REVIEWING]:
        st.warning("👀 请认真看视频哦！")
        if st.button("✅ 视频我看完了！", use_container_width=True):
            backend.handle_text_event(intent=UserIntent.MARK_LEARNING_DONE)
            st.rerun()

    # 状态 3：练习阶段
    elif learning.current_phase == LearningPhase.PRACTICING:
        st.warning("📝 现在是闯关答题时间！")
        
        st.write("老师提问：**恐龙为什么会灭绝？** (提示: 答案里包含陨石或火山)")
        
        # 文字输入方式
        user_answer = st.text_input("方式1：在这里输入文字答案：")
        if st.button("📤 提交文字", use_container_width=True):
            backend.handle_text_event(intent=UserIntent.SUBMIT_ANSWER, text=user_answer)
            st.rerun()

        st.markdown("---")
        
        # ⚠️ 语音输入方式 (对接后端 handle_audio_upload)
        st.write("方式2：或者直接用语音回答！")
        audio_bytes = st.audio_input("点击麦克风开始录音 🎙️", label_visibility="collapsed")
        
        if audio_bytes:
            with st.spinner("系统正在拼命听和思考..."):
                # 把录音文件直接交给后端管家！
                backend.handle_audio_upload(audio_bytes.getvalue())
            st.rerun()

    # 状态 4：完全掌握
    elif learning.current_phase == LearningPhase.MASTERED:
        st.balloons()
        st.success("🎉 太棒了！你已经完全掌握了这个知识点！")
        if st.button("🔄 重新体验 (重置进度)", use_container_width=True):
            # 临时加个重置按钮方便测试
            import os
            os.remove("./data/state.json") if os.path.exists("./data/state.json") else None
            st.rerun()