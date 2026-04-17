import streamlit as st
from design import COMPANIONS, get_global_css, get_companion_avatar, ICONS
from src.services.session_backend import SessionBackend

st.set_page_config(page_title="魔法学习舱", layout="wide")
st.markdown(get_global_css(), unsafe_allow_html=True)

# 专属 CSS 注入：给右侧聊天列加上半透明底板
st.markdown("""
<style>
div[data-testid="column"]:nth-of-type(2) {
    background-color: rgba(255, 255, 255, 0.4);
    border-radius: 25px;
    padding: 20px;
    box-shadow: 0 8px 30px rgba(0,0,0,0.02);
}
</style>
""", unsafe_allow_html=True)

# 1. 安全初始化后端与加载状态
if "backend" not in st.session_state: 
    st.session_state.backend = SessionBackend()
backend: SessionBackend = st.session_state.backend

try:
    app_state = backend.load_app_state()
    learning = app_state.learning
    current_topic = app_state.curriculum.topics[0].title if app_state.curriculum.topics else "自由探索"
    current_score = getattr(learning, 'total_score', 0)

    if "companion" not in st.session_state: 
        st.session_state.companion = "星空兔"
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": backend.generate_proactive_question()}]
except Exception as e:
    # 增加明确的异常暴露，方便排错
    st.error(f"❌ 系统核心数据加载失败，请检查 state.json 结构或后端依赖。\n\n**详细错误信息：** {str(e)}")
    st.stop()

# 提取宠物名字用于提示语
pet_name = st.session_state.companion

# 2. 顶部导航与状态渲染
col_nav, col_status, col_settings = st.columns([2, 6, 2])
with col_nav:
    # 兼容性保护：确保升级后可以使用 switch_page
    if st.button("返回大厅"): 
        st.switch_page("app.py")

with col_status:
    avatar = get_companion_avatar(st.session_state.companion, current_score)
    max_score = 150 # 进化满分值
    progress_pct = min((current_score / max_score) * 100, 100)
    
    st.markdown(f"""
        <div style='text-align:center; font-weight: bold; padding-top: 5px; color: #4A4A4A;'>
            <div style="font-size: 1.2rem; display: flex; justify-content: center; align-items: center; gap: 8px;">
                {ICONS['star']} 智慧星: {current_score} &nbsp;|&nbsp; 伙伴: <span style='font-size:1.6rem;'>{avatar}</span>
            </div>
            <div class='exp-bar-bg'>
                <div class='exp-bar-fill' style='width: {progress_pct}%;'></div>
            </div>
            <div style='font-size:0.8rem; color:#888; margin-top:4px;'>
                再收集 <span style="color:#FF8DA1;">{max(0, max_score - current_score)}</span> 颗星星，伙伴就能进化啦！
            </div>
        </div>
    """, unsafe_allow_html=True)

with col_settings:
    st.session_state.companion = st.selectbox("更换伙伴", list(COMPANIONS.keys()), label_visibility="collapsed")

st.divider()

# 3. 核心交互区
col_media, col_chat = st.columns([6, 4], gap="large")

with col_media:
    st.markdown(f"<h3 style='color: #7EC8E3; margin-top: 0;'>今日探索: {current_topic}</h3>", unsafe_allow_html=True)
    st.video("https://www.w3schools.com/html/mov_bbb.mp4")

with col_chat:
    st.markdown(f"<h3 style='color: #FF8DA1; margin-top: 0;'>伙伴连线</h3>", unsafe_allow_html=True)
    
    chat_container = st.container(height=420)
    with chat_container:
        for msg in st.session_state.messages:
            icon = avatar if msg["role"] == "assistant" else "👦"
            with st.chat_message(msg["role"], avatar=icon):
                st.markdown(msg["content"])
    
    user_text = None
    
    col_mic, col_help = st.columns([7, 3])
    with col_mic:
        # 注意：这里需要 Streamlit 1.38.0 及以上版本！
        audio_bytes = st.audio_input("语音输入", label_visibility="collapsed")
    with col_help:
        st.markdown("<div style='margin-top: 6px;'></div>", unsafe_allow_html=True)
        help_clicked = st.button("❓ 我没听懂", use_container_width=True)

    if audio_bytes:
        with st.spinner(f"🐇 {pet_name} 正在竖起耳朵听..."): 
            user_text = backend.transcribe_audio(audio_bytes.getvalue())
            
    if help_clicked:
        user_text = "我没听懂，能用更简单的话再给我讲一遍吗？"

    if prompt := st.chat_input("或者打字告诉我..."): 
        user_text = prompt

    # 4. 指令执行与积分更新
    if user_text:
        st.session_state.messages.append({"role": "user", "content": user_text})
        with chat_container:
            with st.chat_message("user", avatar="👦"): 
                st.markdown(user_text)
            
            with st.chat_message("assistant", avatar=avatar):
                with st.spinner(f"🧠 {pet_name} 正在转动小脑筋..."):
                    reply, pts = backend.evaluate_student_answer(user_text)
                    st.markdown(reply)
                    if pts > 0: 
                        st.caption(f"获得 {pts} 颗智慧星！")
                        st.balloons()
                    st.session_state.messages.append({"role": "assistant", "content": reply})
        st.rerun()