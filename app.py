# app.py - 儿童AI学习伴侣 (修复版)
import streamlit as st
import time
import pandas as pd 
import altair as alt  # 引入图表库以控制横坐标旋转
from design import COLORS, COMPANIONS, get_global_css

from src.services.session_backend import SessionBackend
from src.core.enums import UserIntent, LearningPhase

st.set_page_config(page_title="AI星梦乐园", page_icon="✨", layout="wide")
st.markdown(get_global_css(), unsafe_allow_html=True)

def init_session_state():
    if "current_mode" not in st.session_state:
        st.session_state.current_mode = "👶 儿童学习"
    if "companion" not in st.session_state:
        st.session_state.companion = "星空兔 🐰"
    if "progress" not in st.session_state:
        st.session_state.progress = 20
    if "tasks" not in st.session_state:
        st.session_state.tasks = ["听读拼音 a o e", "认识数字 1-5"]
init_session_state()

if "backend" not in st.session_state:
    st.session_state.backend = SessionBackend()
backend: SessionBackend = st.session_state.backend
app_state = backend.load_app_state()  # 读取真实的硬盘进度

with st.sidebar:
    st.markdown("<h1 style='text-align:center; color:#2C3E50;'>✨星梦乐园</h1>", unsafe_allow_html=True)
    
    st.session_state.current_mode = st.radio(
        "魔法通道",
        ["👶 儿童学习", "🧑‍🏫 家长管理"],
        label_visibility="collapsed"
    )
    
    st.markdown("---")
    if st.session_state.current_mode == "👶 儿童学习":
        st.markdown("### 🏆 我的百宝箱")
        # ✅ 接入你大脑的真进度（这里写个简单的映射把阶段转成进度百分比）
        phase_mapping = {
            LearningPhase.NOT_STARTED: 0,
            LearningPhase.LEARNING: 30,
            LearningPhase.PRACTICING: 60,
            LearningPhase.REVIEWING: 40,
            LearningPhase.MASTERED: 100
        }
        real_progress = phase_mapping.get(app_state.learning.current_phase, 0)
        st.markdown(f"**当前阶段：{app_state.learning.current_phase}，能量：{real_progress}%**")
        st.markdown(f"""
            <div style='background:rgba(255,255,255,0.6); padding:15px; border-radius:15px; border:2px solid white;'>
                <p style='margin:0; font-size:18px;'>🌟 智慧星: {st.session_state.progress // 20} 颗</p>
                <p style='margin:0; font-size:18px;'>🏅 专注徽章: 1 枚</p>
            </div>
        """, unsafe_allow_html=True)

if st.session_state.current_mode == "🧑‍🏫 家长管理":
    st.markdown("## 📊 家长数据舱 & 设置中心")
    
    metric_cols = st.columns(4)
    metric_cols[0].metric(label="本周学习总时长", value="4.5 小时", delta="+1.2 小时")
    metric_cols[1].metric(label="任务完成率", value="85%", delta="↑ 提升")
    metric_cols[2].metric(label="口语评测均分", value="92 分", delta="A+")
    metric_cols[3].metric(label="获得智慧星", value=f"{st.session_state.progress // 20} 颗")

    st.markdown("<br>", unsafe_allow_html=True)

    col1, col2 = st.columns([1, 1])
    with col1:
        st.markdown("### 📈 专注力变化趋势")
        
        # ✨ 新增：使用 Altair 画图，强制 labelAngle=0 (顺时针放平汉字)
        chart_data = pd.DataFrame({
            "星期": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"],
            "专注力": [60, 75, 80, 85, 90, 85, 95]
        })
        
        c = alt.Chart(chart_data).mark_line(
            color="#FF9A9E", 
            strokeWidth=4, 
            point=alt.OverlayMarkDef(color="#A18CD1", size=100) # 加上圆润的折点
        ).encode(
            x=alt.X("星期", sort=None, axis=alt.Axis(labelAngle=0, labelFontSize=14)), # 强制 0 度不旋转
            y=alt.Y("专注力", scale=alt.Scale(domain=[0, 100]), axis=alt.Axis(labelFontSize=14)),
            tooltip=["星期", "专注力"]
        ).properties(height=300)
        
        st.altair_chart(c, use_container_width=True)
        
        st.markdown("### 🧩 伴学配置")
        new_companion = st.selectbox("当前选择的伴学角色", list(COMPANIONS.keys()), 
                                     index=list(COMPANIONS.keys()).index(st.session_state.companion))
        if new_companion != st.session_state.companion:
            st.session_state.companion = new_companion
            st.rerun()

    with col2:
        st.markdown("### 📁 离线资料库更新")
        uploaded_files = st.file_uploader("导入本地互动课件/视频", accept_multiple_files=True)
        if uploaded_files:
            st.success(f"✅ {len(uploaded_files)} 个本地文件已就绪！")
        
        st.markdown("### 📝 今日任务规划")
        new_task = st.text_input("新增探索任务")
        if st.button("➕ 发送任务给孩子"):
            if new_task:
                st.session_state.tasks.append(new_task)
                st.toast("已同步至儿童端", icon="🚀")

else:
    comp_info = COMPANIONS[st.session_state.companion]
    
    st.markdown(f"""
<div class="floating-avatar">{comp_info['avatar']}</div>
<div class="speech-bubble">{comp_info['greeting']}</div>
    """, unsafe_allow_html=True)

    col_main, col_action = st.columns([7, 3], gap="large")

    with col_main:
        current_task = st.session_state.tasks[0] if st.session_state.tasks else "自由玩耍时间！"
        
        # ✨ 修复乱码：移除了这段 HTML 前面的所有空格缩进
        html_content = f"""
<div class="learning-cabin">
    <h3 style='color: #2C3E50; margin-top:0; text-align:center;'>🚀 {current_task}</h3>
    <div style="height: 320px; background: rgba(0,0,0,0.8); border-radius: 20px; display: flex; align-items: center; justify-content: center; box-shadow: inset 0 0 30px rgba(0,0,0,0.5);">
        <h2 style="color: white; text-shadow: 0 0 10px #A18CD1;">📺 本地动画 / 课件播放区</h2>
    </div>
    <br>
    <p style="color: #666; font-weight:bold; margin-bottom: 5px;">🔥 当前能量值</p>
    <div class="energy-container">
        <div class="energy-fill" style="width: {st.session_state.progress}%;">⭐</div>
    </div>
</div>
        """
        st.markdown(html_content, unsafe_allow_html=True)

    with col_action:
        st.markdown(f"### 🪄 魔法按钮")
        
        if st.button("🎙️ 我要说话", use_container_width=True):
            st.toast("麦克风已开启", icon="🎤")
            with st.spinner("竖起耳朵听..."):
                time.sleep(1)
            st.success("你说得太棒了！")

        st.write("") 
        
        if st.button("🌟 我学会啦！", use_container_width=True):
            backend.handle_text_event(intent=UserIntent.MARK_LEARNING_DONE)
            st.rerun() # 强制刷新网页，让后端的新状态生效
            if st.session_state.progress < 100:
                st.session_state.progress += 20
                if len(st.session_state.tasks) > 0:
                    st.session_state.tasks.pop(0)
                st.balloons()
                st.success("太厉害啦！获得一颗智慧星星！⭐")
            else:
                st.info("今天的能量池已经满啦，明天再来哦！")
                
        st.write("") 
        
        if st.button("🎮 玩个小游戏", use_container_width=True):
            st.snow()
            st.info("加载本地互动游戏中...")