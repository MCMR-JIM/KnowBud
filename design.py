import streamlit as st

COLORS = {
    "primary": "#FF8DA1",       
    "secondary": "#FFE066",     
    "success": "#75D9A5",       
    "blue": "#7EC8E3",          
    "text_dark": "#4A4A4A",     
    "bg_gradient": "linear-gradient(135deg, #E6E9FF 0%, #F5E6FF 100%)" 
}

# 恢复完整的 SVG 图标库（包含了主页、儿童端、家长端需要的所有图标）
ICONS = {
    "rocket": '<svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="m12 15-3-3a22 22 0 0 1 3.82-13.01 1 1 0 0 1 1.41 0 1 1 0 0 1 0 1.41 22.01 22.01 0 0 0 13.01-3.82z"/><path d="M5.32 12.84 2.5 15.66"/><path d="M11.16 18.68 8.34 21.5"/><path d="m15 9 6-6"/></svg>',
    "parent": '<svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    "warning": '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="#EF4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    "log": '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>',
    "star": '<svg viewBox="0 0 24 24" width="24" height="24" fill="#FFE066" stroke="#FFB020" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>'
}

# 伴学宠物的三个阶段（0分、50分、150分满级）
# 伴学宠物的三个阶段（0分、50分、150分满级）
# 注意：Streamlit 严格要求 avatar 必须是单个 Emoji，绝不能用两个 Emoji 组合！
COMPANIONS = {
    "星空兔": {"stages": { 0: "🐇", 50: "🐰", 150: "🦄" }},  # 将超人兔改为了星空独角兽 🦄
    "小智龙": {"stages": { 0: "🦎", 50: "🦕", 150: "🦖" }}
}

def get_companion_avatar(companion_name, score):
    stages = COMPANIONS[companion_name]["stages"]
    thresholds = sorted(stages.keys())
    current = stages[thresholds[0]]
    for t in thresholds:
        if score >= t: current = stages[t]
        else: break
    return current

def get_global_css():
    return f"""
    <style>
    html, body, [class*="st-"] {{
        color: {COLORS['text_dark']};
        font-family: 'Nunito', 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }}
    .stApp {{ background: {COLORS['bg_gradient']}; }}
    [data-testid="stSidebar"], [data-testid="collapsedControl"] {{ display: none !important; }}

    /* 卡片与图标样式 */
    .cute-card {{
        background: rgba(255, 255, 255, 0.6);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border-radius: 30px;
        padding: 40px 20px;
        text-align: center;
        box-shadow: 0 8px 30px rgba(0,0,0,0.05);
        border-top: 8px solid;
        border-bottom: 1px solid rgba(255,255,255,0.8);
        transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
    }}
    .cute-card:hover {{ transform: translateY(-8px) scale(1.02); }}

    .icon-box {{
        width: 80px; height: 80px; margin: 0 auto 20px auto;
        border-radius: 50%; display: flex; align-items: center; justify-content: center;
        background: rgba(255,255,255,0.9); box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }}

    /* 统一交互组件为现代化圆角风格 */
    .stButton > button, div[data-baseweb="select"] > div, .stTextInput > div > div > input {{
        background: rgba(255, 255, 255, 0.9) !important;
        border: 2px solid {COLORS['blue']} !important;
        border-radius: 20px !important;
        color: {COLORS['text_dark']} !important;
        box-shadow: 0 4px 10px rgba(0,0,0,0.02);
    }}
    .stButton > button {{ color: {COLORS['blue']} !important; font-weight: bold !important; transition: all 0.2s; }}
    .stButton > button:hover {{ background: {COLORS['blue']} !important; color: #fff !important; transform: scale(1.05); }}

    /* =======================================
       1. 聊天气泡：纯白底色 + 淡淡的弥散阴影
       ======================================= */
    [data-testid="stChatMessage"] {{
        background-color: #FFFFFF !important; 
        border-radius: 18px !important; 
        padding: 15px !important; 
        margin-bottom: 15px !important;
        box-shadow: 0 4px 15px rgba(0,0,0,0.05) !important; 
        border: none !important;
    }}
    
    /* =======================================
       2. 具象化的经验进度条 (Gamification)
       ======================================= */
    .exp-bar-bg {{
        width: 100%;
        background-color: rgba(255, 255, 255, 0.6);
        border-radius: 20px;
        height: 18px;
        margin-top: 10px;
        box-shadow: inset 0 2px 4px rgba(0,0,0,0.05);
        border: 2px solid #FFFFFF;
        overflow: hidden;
    }}
    .exp-bar-fill {{
        height: 100%;
        background: linear-gradient(90deg, #FFD700 0%, #FF8DA1 100%);
        border-radius: 20px;
        transition: width 0.8s cubic-bezier(0.175, 0.885, 0.32, 1.275);
    }}

    /* =======================================
       3. 家长端 Danger Zone 样式
       ======================================= */
    .danger-zone {{
        background: #FFF0F0; border-left: 6px solid #EF4444; border-radius: 12px; padding: 20px; margin-top: 20px;
    }}
    .danger-zone-title {{ color: #EF4444; font-weight: bold; font-size: 1.2rem; display: flex; align-items: center; gap: 10px; margin-bottom: 5px; }}
    .danger-zone-text {{ color: #7F1D1D; font-size: 0.9rem; margin: 0; }}
    </style>
    """