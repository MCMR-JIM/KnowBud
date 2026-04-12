# design.py
import streamlit as st

COLORS = {
    "primary": "#FF9A9E",       
    "secondary": "#FECFEF",     
    "success": "#A8E063",       
    "text_dark": "#2C3E50",     
    "bg_gradient": "linear-gradient(120deg, #e0c3fc 0%, #8ec5fc 100%)", 
    "cabin_border": "#FFD700"   
}

# 保留进化的逻辑，但恢复使用可爱的 Emoji 形态
COMPANIONS = {
    "星空兔 🐰": {
        "greeting": "叮咚！我是星空兔，今天我们要一起收集好多智慧星星哦！",
        "stages": {
            0: "🐇",    # 0分: 小白兔
            50: "🐰",   # 50分: 大白兔
            150: "🦸‍♀️🐰"  # 150分: 超级兔
        },
        "theme_color": "#FF9A9E"
    },
    "小智龙 🦖": {
        "greeting": "嗷呜～小智龙来啦！快坐进我们的魔法学习舱，准备起飞！",
        "stages": {
            0: "🦎",    # 小蜥蜴
            50: "🦕",   # 梁龙
            150: "🦖"   # 霸王龙
        },
        "theme_color": "#A8E063"
    }
}

def get_companion_avatar(companion_name, score):
    stages = COMPANIONS[companion_name]["stages"]
    thresholds = sorted(stages.keys())
    current_avatar = stages[thresholds[0]]
    for t in thresholds:
        if score >= t:
            current_avatar = stages[t]
        else:
            break
    return current_avatar

def get_global_css():
    return f"""
    <style>
    /* 全局自定义魔法棒鼠标 */
    html, body, [class*="st-"] {{
        cursor: url('https://cdn-icons-png.flaticon.com/32/1864/1864470.png'), auto !important;
    }}
    a, button, input, select, .stButton>button {{
        cursor: url('https://cdn-icons-png.flaticon.com/32/1864/1864470.png'), pointer !important;
    }}

    .stApp {{
        background: {COLORS['bg_gradient']};
    }}

    [data-testid="stSidebar"], [data-testid="collapsedControl"] {{
        display: none !important;
    }}

    /* 恢复可爱的卡片样式 */
    .cute-card {{
        background: rgba(255,255,255,0.7);
        padding: 30px;
        border-radius: 25px;
        text-align: center;
        border: 4px dashed #FF9A9E;
        box-shadow: 0 10px 20px rgba(0,0,0,0.1);
        height: 280px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        transition: transform 0.3s;
    }}
    .cute-card:hover {{
        transform: translateY(-10px);
    }}

    /* 恢复圆润的果冻按钮 */
    .stButton > button {{
        background: rgba(255, 255, 255, 0.9) !important;
        border: 3px solid {COLORS['primary']} !important;
        color: {COLORS['text_dark']} !important;
        border-radius: 25px !important;
        font-weight: 800 !important;
        font-size: 20px !important;
        padding: 12px 24px !important;
        transition: all 0.5s cubic-bezier(0.175, 0.885, 0.32, 1.275) !important; 
        box-shadow: 0 6px 15px rgba(0,0,0,0.08);
    }}
    .stButton > button:hover {{
        transform: translateY(-6px) scale(1.05) !important;
        box-shadow: 0 12px 25px rgba(255, 154, 158, 0.5) !important;
    }}
    </style>
    """