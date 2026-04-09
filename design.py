# design.py - 界面规范与全局样式引擎 (修复版)

COLORS = {
    "primary": "#FF9A9E",       
    "secondary": "#FECFEF",     
    "success": "#A8E063",       
    "text_dark": "#2C3E50",     
    "bg_gradient": "linear-gradient(120deg, #e0c3fc 0%, #8ec5fc 100%)", 
    "cabin_border": "#FFD700"   
}

COMPANIONS = {
    "星空兔 🐰": {
        "greeting": "叮咚！我是星空兔，今天我们要一起收集好多智慧星星哦！",
        "avatar": "🐰",
        "theme_color": "#FF9A9E"
    },
    "小智龙 🦖": {
        "greeting": "嗷呜～小智龙来啦！快坐进我们的魔法学习舱，准备起飞！",
        "avatar": "🦖",
        "theme_color": "#A8E063"
    }
}

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

    /* 主背景 */
    .stApp {{
        background: {COLORS['bg_gradient']};
    }}

    /* =========================================
       ✨ 新增：侧边栏玻璃拟态与童趣化字体
       ========================================= */
    [data-testid="stSidebar"] {{
        background: rgba(255, 255, 255, 0.2) !important; /* 让侧边栏透出主背景的渐变色 */
        backdrop-filter: blur(15px) !important;
        -webkit-backdrop-filter: blur(15px) !important;
        border-right: 3px dashed rgba(255, 255, 255, 0.5) !important; /* 可爱的虚线边框 */
    }}
    
    /* 放大侧边栏所有文字，增加圆润感 */
    [data-testid="stSidebar"] .stMarkdown p, 
    [data-testid="stSidebar"] .stMarkdown h1, 
    [data-testid="stSidebar"] .stMarkdown h3,
    [data-testid="stSidebar"] .stRadio label {{
        font-size: 20px !important;
        font-weight: 800 !important;
        color: {COLORS['text_dark']} !important;
    }}
    
    /* 放大单选按钮的小圆圈 */
    [data-testid="stSidebar"] div[role="radiogroup"] > label > div:first-child {{
        transform: scale(1.4);
        margin-right: 8px;
    }}

    /* 角色浮动动画 */
    .floating-avatar {{
        font-size: 80px;
        animation: float 3s ease-in-out infinite;
        text-align: center;
        margin-bottom: 10px;
        text-shadow: 0 10px 20px rgba(0,0,0,0.15);
    }}
    @keyframes float {{
        0% {{ transform: translateY(0px); }}
        50% {{ transform: translateY(-15px); }}
        100% {{ transform: translateY(0px); }}
    }}

    /* 漫画对话气泡 */
    .speech-bubble {{
        position: relative;
        background: rgba(255, 255, 255, 0.9);
        border-radius: 20px;
        padding: 15px 25px;
        color: {COLORS['text_dark']};
        font-weight: bold;
        font-size: 20px;
        text-align: center;
        box-shadow: 0 8px 20px rgba(0,0,0,0.1);
        margin: 0 auto 30px auto;
        max-width: 600px;
        border: 3px solid white;
    }}
    .speech-bubble::after {{
        content: '';
        position: absolute;
        top: -15px;
        left: 50%;
        margin-left: -15px;
        border-width: 0 15px 15px 15px;
        border-style: solid;
        border-color: transparent transparent rgba(255, 255, 255, 0.9) transparent;
    }}

    /* 沉浸式魔法学习舱 */
    .learning-cabin {{
        background: rgba(255, 255, 255, 0.6);
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        border: 6px solid {COLORS['cabin_border']};
        border-radius: 40px;
        box-shadow: inset 0 0 20px rgba(255, 215, 0, 0.3), 0 15px 35px rgba(0,0,0,0.1);
        padding: 30px;
        position: relative;
    }}
    .learning-cabin::before {{
        content: '🔴 🟡 🟢';
        position: absolute;
        top: 10px;
        left: 20px;
        font-size: 14px;
        letter-spacing: 5px;
    }}

    /* 能量条 */
    .energy-container {{
        width: 100%;
        background-color: rgba(255,255,255,0.5);
        border-radius: 20px;
        padding: 4px;
        box-shadow: inset 0 2px 5px rgba(0,0,0,0.1);
    }}
    .energy-fill {{
        height: 28px;
        border-radius: 16px;
        background: linear-gradient(90deg, #FAD961 0%, #F76B1C 100%);
        transition: width 0.8s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        display: flex;
        align-items: center;
        justify-content: flex-end;
        padding-right: 10px;
        color: white;
        font-weight: bold;
        font-size: 16px;
    }}

    /* 按钮动效 */
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
    .stButton > button:active {{
        transform: translateY(2px) scale(0.95) !important;
    }}

    header, footer, [data-testid="stSidebarNav"] {{ visibility: hidden; }}
    </style>
    """