# pages/1_Admin_Dashboard.py - 儿童AI学习伴侣 管理端 (真实数据版)
import streamlit as st
import os
from pathlib import Path

# 🔴 关键：引入大管家
from src.services.session_backend import SessionBackend

st.set_page_config(page_title="学习管理后台", page_icon="⚙️", layout="wide")

# 唤醒管家，读取真实数据
if "backend" not in st.session_state:
    st.session_state.backend = SessionBackend()
backend: SessionBackend = st.session_state.backend
app_state = backend.load_app_state()
learning = app_state.learning

st.markdown("<h2 style='color:#FF9A9E; margin-bottom: 20px;'>⚙️ 儿童AI学习伴侣 - 管理后台</h2>", unsafe_allow_html=True)
st.divider()

res_col, progress_col = st.columns([6, 4], gap="large")

with res_col:
    st.markdown("<h3 style='color:#FF9A9E;'>📁 核心学习数据监控</h3>", unsafe_allow_html=True)
    st.info("这些数据直接来自于你电脑本地的 data/state.json 存档，绝不上传云端。")
    
    st.markdown("#### 1. 儿童当前档案与课程")
    # 直接展示 Pydantic 模型的数据
    st.json(app_state.profile.model_dump())
    st.json(app_state.curriculum.model_dump())

with progress_col:
    st.markdown("<h3 style='color:#FF9A9E;'>📊 真实学习进度与连错统计</h3>", unsafe_allow_html=True)
    
    # 这里的进度直接受你写的 DecisionEngine 规则控制
    st.metric(label="当前所处系统阶段", value=learning.current_phase)
    
    col1, col2 = st.columns(2)
    col1.metric(label="✅ 连续答对次数", value=learning.consecutive_correct)
    col2.metric(label="❌ 连续答错次数", value=learning.consecutive_wrong)
    
    st.metric(label="📈 近期总体错误率", value=f"{learning.error_rate * 100}%")

st.divider()

# 🔴 日志查看区：直接读取引擎输出的 trace
st.markdown("<h3 style='color:#FF9A9E;'>📋 系统底层决策日志 (供开发者调试)</h3>", unsafe_allow_html=True)
log_path = Path("./logs/decision_trace.jsonl")

if log_path.exists():
    with open(log_path, "r", encoding="utf-8") as f:
        logs = f.readlines()
    # 取最后 15 条记录展示
    log_text = "".join(logs[-15:])
    st.text_area("实时读取 logs/decision_trace.jsonl：", value=log_text, height=300)
else:
    st.warning("暂无决策日志记录，请让儿童端点击按钮后刷新此页面。")