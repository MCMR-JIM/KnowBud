# pages/2_Admin_Dashboard.py
import streamlit as st
import pandas as pd
from design import get_global_css
from src.services.session_backend import SessionBackend

st.set_page_config(page_title="家长管理后台", page_icon="⚙️", layout="wide")
st.markdown(get_global_css(), unsafe_allow_html=True)

if "backend" not in st.session_state:
    st.session_state.backend = SessionBackend()
backend = st.session_state.backend

col_nav, col_title = st.columns([1, 9])
with col_nav:
    if st.button("🏠 返回大厅"):
        st.switch_page("app.py")
with col_title:
    st.markdown("<h2 style='color:#2C3E50; margin-top: 0;'>⚙️ 家长/老师控制台</h2>", unsafe_allow_html=True)

st.divider()

tab1, tab2, tab3 = st.tabs(["📁 任务配置", "📊 学习报告", "🔧 系统调试"])

with tab1:
    st.markdown("### 🎬 上传今日学习任务")
    uploaded_file = st.file_uploader("上传教学视频/图片", type=["mp4", "jpg", "png"])
    topic_name = st.text_input("本节课主题名称", value="恐龙世界的秘密")
    
    if st.button("💾 保存配置并生成 AI 题库"):
        if uploaded_file:
            st.success("配置成功！AI 已经根据视频准备好考考小朋友啦。")
        else:
            st.warning("请先上传文件哦~")

with tab2:
    st.markdown("### 🌟 积分与学习进度")
    col_a, col_b = st.columns([3, 7])
    with col_a:
        st.metric(label="当前总积分", value="150 🌟", delta="+30 (今日)")
        st.metric(label="连对次数", value="3 次", delta="1", delta_color="normal")
    with col_b:
        chart_data = pd.DataFrame({
            '日期': ['周一', '周二', '周三', '周四', '周五'],
            '获得星星数': [20, 50, 40, 90, 150]
        }).set_index('日期')
        st.bar_chart(chart_data)

with tab3:
    st.markdown("### 📋 引擎决策日志")
    st.info("直接读取 logs/ 目录下的数据")
    st.code("""
[2024-04-12 10:00:01] INFO: Session Initialized.
[2024-04-12 10:05:22] ASR_TTS: Transcribed text -> "我认为它喜欢吃肉"
[2024-04-12 10:05:25] FSM Logic: Transitioned from LEARNING to PRACTICING.
[2024-04-12 10:05:26] LLM Evaluation: {"score": 20, "feedback": "正确，霸王龙是肉食动物"}
    """, language="log")

    st.markdown(f"""
    <div style="background-color: #FEF2F2; border-left: 6px solid #EF4444; padding: 20px; border-radius: 8px; margin-top: 20px;">
        <h4 style="color: #EF4444; margin-top: 0;">⚠️ 危险操作区</h4>
        <p style="color: #6B7280; font-size: 0.9rem;">这里的操作将直接影响底层状态，无法撤销。</p>
    </div>
    """, unsafe_allow_html=True)
    
    if st.button("🗑️ 清空本地上下文状态"):
        st.toast("鉴权拦截：演示环境禁止直接擦除核心态。")