# pages/1_Kids_Learning.py
import streamlit as st
from design import COMPANIONS, get_global_css, get_companion_avatar

from src.services.session_backend import SessionBackend

st.set_page_config(page_title="魔法学习舱", page_icon="🛸", layout="wide")
st.markdown(get_global_css(), unsafe_allow_html=True)

if "backend" not in st.session_state:
    st.session_state.backend = SessionBackend()
backend: SessionBackend = st.session_state.backend

# 读取数据
app_state = backend.load_app_state()
learning = app_state.learning
current_topic = app_state.curriculum.topics[0].title if app_state.curriculum.topics else "恐龙世界的秘密"
current_score = getattr(learning, 'total_score', 0)

if "companion" not in st.session_state:
    st.session_state.companion = "小智龙 🦖"

if "messages" not in st.session_state:
    init_msg = backend.generate_proactive_question()
    st.session_state.messages = [{"role": "assistant", "content": init_msg}]

# 顶部导航
col_nav, col_status, col_settings = st.columns([2, 6, 2])
with col_nav:
    if st.button("🏠 返回大厅"):
        st.switch_page("app.py")
with col_status:
    current_avatar = get_companion_avatar(st.session_state.companion, current_score)
    st.markdown(f"<h3 style='text-align:center; color:#2C3E50;'>🌟 智慧星: {current_score} 颗 | 我的伙伴: {current_avatar}</h3>", unsafe_allow_html=True)
with col_settings:
    st.session_state.companion = st.selectbox("换个好朋友", list(COMPANIONS.keys()), label_visibility="collapsed")

st.divider()

col_media, col_chat = st.columns([6, 4], gap="large")

with col_media:
    st.markdown(f"### 📺 今日探索: {current_topic}")
    st.video("https://www.w3schools.com/html/mov_bbb.mp4")
    st.info("💡 提示：认真看视频哦，右边的好朋友一会要考你的！")

with col_chat:
    st.markdown("### 💬 伙伴连线")
    
    chat_container = st.container(height=450)
    with chat_container:
        for msg in st.session_state.messages:
            avatar_icon = current_avatar if msg["role"] == "assistant" else "👦"
            with st.chat_message(msg["role"], avatar=avatar_icon):
                st.markdown(msg["content"])
    
    user_text = None
    
    audio_bytes = st.audio_input("按住麦克风说话 🎙️", label_visibility="collapsed")
    if audio_bytes:
        with st.spinner("正在竖起耳朵听..."):
            try:
                user_text = backend.transcribe_audio(audio_bytes.getvalue())
            except Exception as e:
                st.error("哎呀，没听清，能再说一遍吗？")
            
    if prompt := st.chat_input("或者在这里打字告诉我..."):
        user_text = prompt

    if user_text:
        st.session_state.messages.append({"role": "user", "content": user_text})
        with chat_container:
            with st.chat_message("user", avatar="👦"):
                st.markdown(user_text)
                
            with st.chat_message("assistant", avatar=current_avatar):
                with st.spinner("小脑筋转动中..."):
                    try:
                        response_text, earned_points = backend.evaluate_student_answer(user_text)
                        st.markdown(response_text)
                        if earned_points > 0:
                            st.success(f"🎉 太棒啦！星星 +{earned_points}")
                            st.balloons()
                        st.session_state.messages.append({"role": "assistant", "content": response_text})
                    except Exception as e:
                        error_msg = "哎呀，我的魔法大脑短路了，我们等会再试好吗？"
                        st.markdown(error_msg)
                        st.session_state.messages.append({"role": "assistant", "content": error_msg})
                        
        st.rerun()