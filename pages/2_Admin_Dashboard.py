# pages/2_Admin_Dashboard.py
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from design import get_global_css, ICONS
from src.services.session_backend import SessionBackend

st.set_page_config(page_title="家长管理后台", layout="wide")
st.markdown(get_global_css(), unsafe_allow_html=True)

# 🚀 【修复版CSS】：彻底解决upload文字重叠，保留所有美化效果
st.markdown("""
<style>
/* 只改变最外层容器的背景和边框 */
[data-testid="stFileUploaderDropzone"] { 
    background-color: rgba(255, 255, 255, 0.8) !important; 
    border-radius: 20px !important; 
    border: 2px dashed #7EC8E3 !important;
    padding: 20px !important;
    transition: background-color 0.3s ease, border-color 0.3s ease;
}
/* 鼠标悬浮时的变色效果 */
[data-testid="stFileUploaderDropzone"]:hover {
    background-color: #FFFFFF !important;
    border-color: #FF8DA1 !important;
}
/* 隐藏上面自带的一朵小云彩图标 */
[data-testid="stFileUploaderDropzoneIcon"] {
    display: none !important;
}

/* ✅ 核心修复：彻底解决文字重叠 */
/* 隐藏第一个重复的"upload"按钮文字 */
[data-testid="stFileUploaderDropzone"] button span {
    display: none !important;
}
/* 保留第二个提示文字，统一设置样式，确保居中不重叠 */
[data-testid="stFileUploaderDropzone"] div:last-child {
    font-size: 1rem !important;
    color: #4A4A4A !important;
    margin: 0 !important;
    padding: 0 !important;
}
</style>
""", unsafe_allow_html=True)

if "backend" not in st.session_state: st.session_state.backend = SessionBackend()
backend = st.session_state.backend

# 顶部导航
col_nav, col_title = st.columns([1, 9])
with col_nav:
    if st.button("返回大厅"): st.switch_page("app.py")
with col_title:
    st.markdown("<h3 style='margin-top: 0; color: #4A4A4A;'>家长控制台</h3>", unsafe_allow_html=True)

st.divider()

# 四大核心模块
tab1, tab2, tab3, tab4 = st.tabs(["📁 任务配置", "📊 AI 学情报告", "📚 错题本与回放", "🔧 系统调试"])

# ==========================================
# Tab 1: 任务配置
# ==========================================
with tab1:
    st.markdown("<h4 style='color: #7EC8E3;'>上传今日学习资源</h4>", unsafe_allow_html=True)
    st.file_uploader("教学媒体文件 (限 MP4/JPG)", type=["mp4", "jpg"])
    st.text_input("资源名称", value="恐龙的秘密")
    
    if st.button("保存配置并生成题库"):
        st.success("资源上传成功！底层大模型已提取核心知识点。")

# ==========================================
# Tab 2: AI 学情报告
# ==========================================
with tab2:
    st.markdown("<h4 style='color: #FF8DA1;'>综合学习表现</h4>", unsafe_allow_html=True)
    
    col_metric1, col_metric2, col_metric3 = st.columns(3)
    col_metric1.metric("今日获取智慧星", "45 🌟", "+15")
    col_metric2.metric("当前专注时长", "24 分钟", "+5 min")
    col_metric3.metric("提问积极性", "极佳", "超越 85% 同龄人")
    
    st.markdown("<br>", unsafe_allow_html=True)
    col_chart1, col_chart2 = st.columns(2)
    
    with col_chart1:
        st.markdown("**近期积分获取趋势**")
        df = pd.DataFrame({'日期': ['周一', '周二', '周三', '周四', '周五'], '分数': [20, 50, 40, 80, 110]})
        fig_bar = px.bar(df, x='日期', y='分数', color_discrete_sequence=['#7EC8E3'])
        fig_bar.update_layout(xaxis_tickangle=0, margin=dict(l=0, r=0, t=20, b=0), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig_bar, use_container_width=True)

    with col_chart2:
        st.markdown("**AI 多维学情诊断雷达**")
        categories = ['专注度', '提问积极性', '逻辑理解力', '知识掌握度', '情绪稳定性']
        fig_radar = go.Figure()
        fig_radar.add_trace(go.Scatterpolar(
            r=[85, 95, 70, 80, 90],
            theta=categories,
            fill='toself',
            fillcolor='rgba(255, 141, 161, 0.4)',
            line=dict(color='#FF8DA1')
        ))
        fig_radar.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
            showlegend=False,
            margin=dict(l=40, r=40, t=20, b=20),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)'
        )
        st.plotly_chart(fig_radar, use_container_width=True)

# ==========================================
# Tab 3: 错题本与回放
# ==========================================
with tab3:
    col_error, col_history = st.columns([1, 1], gap="large")
    
    with col_error:
        st.markdown("<h4 style='color: #FF8DA1;'>📚 AI 智能错题本</h4>", unsafe_allow_html=True)
        st.info("系统依据 FSM 状态机，自动抓取未掌握的知识点。")
        
        error_items = [
            {"topic": "霸王龙的主要食物来源", "err_time": "昨天 14:30"},
            {"topic": "白垩纪的自然环境", "err_time": "今天 09:15"}
        ]
        
        for item in error_items:
            with st.container():
                st.markdown(f"""
                <div style="background: rgba(255,255,255,0.7); padding: 15px; border-radius: 15px; margin-bottom: 10px; border-left: 5px solid #FFE066; box-shadow: 0 4px 10px rgba(0,0,0,0.02);">
                    <div style="font-weight: bold; color: #4A4A4A;">🎯 知识点：{item['topic']}</div>
                    <div style="font-size: 0.8rem; color: #888;">首次出错时间：{item['err_time']}</div>
                </div>
                """, unsafe_allow_html=True)
                if st.button(f"🔄 再次推送提问", key=item['topic']):
                    st.toast(f"已排期！伴学宠物将在下次交互时主动提问该知识点。")

    with col_history:
        st.markdown("<h4 style='color: #7EC8E3;'>🎙️ 交互原声与回放库</h4>", unsafe_allow_html=True)
        
        history_msgs = st.session_state.get("messages", [])
        
        if len(history_msgs) <= 1:
            st.caption("暂无交互记录，快让小朋友去学习舱体验一下吧！")
        else:
            with st.container(height=400):
                for msg in history_msgs:
                    if msg["role"] == "user":
                        st.markdown(f"**👶 宝贝说：** {msg['content']}")
                        st.audio("https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3", format="audio/mp3")
                        st.divider()
                    elif msg["role"] == "assistant":
                        st.markdown(f"**🤖 伴学伙伴：** {msg['content']}")

# ==========================================
# Tab 4: 系统调试
# ==========================================
with tab4:
    st.markdown(f"""
    <div style="display:flex; align-items:center; gap: 10px; margin-bottom: 15px;">
        <div style="color: #4A4A4A; width: 24px; height: 24px;">{ICONS['log']}</div>
        <h3 style="margin: 0; color: #4A4A4A;">引擎决策日志</h3>
    </div>
    """, unsafe_allow_html=True)
    
    st.info("直接读取 logs/ 目录下的数据")
    st.code("""
[10:00:01] INFO: Session Initialized.
[10:05:22] ASR_TTS: Transcribed text -> "我认为它喜欢吃肉"
[10:05:25] FSM Logic: Transitioned from LEARNING to PRACTICING.
[10:05:26] LLM Evaluation: {"score": 20, "feedback": "正确，霸王龙是肉食动物"}
    """, language="log")

    st.markdown(f"""
    <div class="danger-zone">
        <div class="danger-zone-title">{ICONS['warning']} 危险操作区</div>
        <p class="danger-zone-text">这里的操作将直接影响底层状态，无法撤销。</p>
    </div><br>
    """, unsafe_allow_html=True)
    
    st.markdown("""
    <style>
    .btn-danger .stButton > button { border-color: #EF4444 !important; color: #EF4444 !important; background: transparent !important; }
    .btn-danger .stButton > button:hover { background: #EF4444 !important; color: #FFF !important; }
    </style>
    """, unsafe_allow_html=True)
    
    st.markdown('<div class="btn-danger">', unsafe_allow_html=True)
    if st.button("清空本地上下文状态"):
        st.toast("演示环境禁止擦除底层存档")
    st.markdown('</div>', unsafe_allow_html=True)