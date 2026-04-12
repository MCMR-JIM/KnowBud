# app.py
import streamlit as st
import os
from design import get_global_css

st.set_page_config(page_title="星梦乐园", page_icon="✨", layout="centered")
st.markdown(get_global_css(), unsafe_allow_html=True)

st.markdown("<h1 style='text-align:center; color: #2C3E50; font-size: 3rem;'>✨ 欢迎来到星梦乐园</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align:center; color: #666; font-size: 1.2rem; margin-bottom: 3rem;'>请选择你的身份，开始今天的奇妙旅程吧！</p>", unsafe_allow_html=True)

col1, col_gap, col2 = st.columns([4, 1, 4])

with col1: 
    st.markdown("""
    <div class="cute-card">
        <h1 style='font-size: 4rem; margin:0;'>👶</h1>
        <h2 style='color:#2C3E50;'>我是小朋友</h2>
        <p style='color:#666;'>看动画，和AI伙伴一起闯关收集星星！</p>
    </div>
    <br>
    """, unsafe_allow_html=True)
    
    if st.button("🚀 启动魔法学习舱", use_container_width=True):
        # 增加容错检查，防止报错页面崩溃
        if os.path.exists("pages/1_Kids_Learning.py"):
            st.switch_page("pages/1_Kids_Learning.py")
        else:
            st.error("找不到页面文件！请确保文件保存在 pages/1_Kids_Learning.py")

with col2:
    st.markdown("""
    <div class="cute-card" style="border-color: #8ec5fc;">
        <h1 style='font-size: 4rem; margin:0;'>🧑‍🏫</h1>
        <h2 style='color:#2C3E50;'>我是家长/老师</h2>
        <p style='color:#666;'>查看学习报告，配置课程内容与难度。</p>
    </div>
    <br>
    """, unsafe_allow_html=True)
    
    if st.button("⚙️ 进入管理后台", use_container_width=True):
        if os.path.exists("pages/2_Admin_Dashboard.py"):
            st.switch_page("pages/2_Admin_Dashboard.py")
        else:
            st.error("找不到页面文件！请确保文件保存在 pages/2_Admin_Dashboard.py")