import streamlit as st
import os
from design import get_global_css, ICONS

st.set_page_config(page_title="星梦乐园", layout="centered")
st.markdown(get_global_css(), unsafe_allow_html=True)

st.markdown("<h1 style='text-align:center; margin-bottom: 10px;'>欢迎来到星梦乐园</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align:center; color: #888; margin-bottom: 40px;'>请选择你的身份，开启奇妙旅程</p>", unsafe_allow_html=True)

col1, col_gap, col2 = st.columns([4, 1, 4])

with col1:
    st.markdown(f"""
    <div class="cute-card" style="border-top-color: #FF8DA1;">
        <div class="icon-box" style="color: #FF8DA1;">{ICONS['rocket']}</div>
        <h2 style='margin:0;'>我是小朋友</h2>
        <p style='color:#888; font-size:0.9rem;'>进入魔法学习舱，看动画闯关</p>
    </div><br>
    """, unsafe_allow_html=True)
    if st.button("启动学习舱", use_container_width=True):
        if os.path.exists("pages/1_Kids_Learning.py"): st.switch_page("pages/1_Kids_Learning.py")

with col2:
    st.markdown(f"""
    <div class="cute-card" style="border-top-color: #7EC8E3;">
        <div class="icon-box" style="color: #7EC8E3;">{ICONS['parent']}</div>
        <h2 style='margin:0;'>我是家长</h2>
        <p style='color:#888; font-size:0.9rem;'>查看学习报告，配置课程内容</p>
    </div><br>
    """, unsafe_allow_html=True)
    if st.button("进入控制台", use_container_width=True):
        if os.path.exists("pages/2_Admin_Dashboard.py"): st.switch_page("pages/2_Admin_Dashboard.py")