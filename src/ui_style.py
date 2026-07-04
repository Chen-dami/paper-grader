"""
极简 CSS
"""
import streamlit as st


def inject():
	st.markdown("""
	<style>
	/* ===== Material Icons ===== */
	.material-icons, .material-symbols-outlined,
	.material-symbols-sharp, .material-symbols-rounded {
		font: 0/0 a !important;
		color: transparent !important;
		text-shadow: none !important;
		overflow: hidden !important;
	}
	button[data-testid="stSidebarCollapseButton"] {
		position: relative !important;
		min-width: 32px !important; min-height: 32px !important;
	}
	button[data-testid="stSidebarCollapseButton"]::before {
		content: "";
		position: absolute; top: 50%; left: 50%;
		transform: translate(-50%, -50%);
		width: 0; height: 0;
		border-top: 5px solid transparent;
		border-bottom: 5px solid transparent;
		border-right: 7px solid #666;
	}
	[data-testid="stDeployButton"] { display: none !important; }
	#MainMenu { visibility: hidden !important; }
	footer { visibility: hidden !important; }

	/* ===== 全局 ===== */
	.stApp { background-color: #F7F5F0; }
	.stTextInput input, .stTextArea textarea,
	[data-baseweb="select"] [class*="select"], [data-baseweb="input"],
	[data-baseweb="select"] > div {
		border: 1px solid #D1CCC3 !important;
		border-radius: 6px !important;
		background-color: #fff !important;
	}
	.stTextInput input:focus, .stTextArea textarea:focus {
		border-color: #4A7C59 !important;
		box-shadow: 0 0 0 2px #E8F0EA !important;
	}
	.stNumberInput input, [data-baseweb="number-input"] input {
		border: 1px solid #D1CCC3 !important;
		border-radius: 6px !important;
		background-color: #fff !important;
	}
	[data-baseweb="popover"] { background-color: #fff !important; }
	[data-baseweb="menu"] { background-color: #fff !important; }
	ul[data-baseweb="menu"] li {
		background-color: #fff !important;
		border-bottom: 1px solid #F2EFE9 !important;
	}
	ul[data-baseweb="menu"] li:hover { background-color: #E8F0EA !important; }
	.stContainer, [data-testid="stExpander"], [data-testid="stForm"],
	[data-testid="stExpander"] details {
		border: 1px solid #D1CCC3 !important;
		border-radius: 8px !important;
	}
	hr, .stDivider { border-color: #D1CCC3 !important; }

	/* ===== 侧边栏 ===== */
	section[data-testid="stSidebar"] {
		border-right: 1px solid #D1CCC3 !important;
		background: linear-gradient(180deg, #FAF8F5 0%, #F7F5F0 100%) !important;
		width: 17rem !important;
		min-width: 180px !important;
		padding-top: 12px !important;
		padding-bottom: 12px !important;
	}
	section[data-testid="stSidebar"] .stExpander {
		border: none !important;
		margin-bottom: 2px !important;
	}
	section[data-testid="stSidebar"] .stExpander details {
		border: 1px solid #E8E4DA !important;
		border-radius: 8px !important;
		background: #FFFFFFFA !important;
	}
	section[data-testid="stSidebar"] .stSelectbox label {
		font-size: 0.85rem !important;
	}
	section[data-testid="stSidebar"] .stButton > button {
		font-size: 0.85rem !important;
		border-radius: 6px !important;
		transition: all 0.15s ease !important;
	}
	section[data-testid="stSidebar"] .stButton > button:hover {
		transform: translateY(-1px) !important;
		box-shadow: 0 2px 6px rgba(74,124,89,0.2);
	}
	[data-testid="stSidebarNavLink"][aria-current="page"] {
		background-color: #E8F0EA !important;
		border-left: 3px solid #4A7C59 !important;
		font-weight: 600 !important;
	}
	[data-testid="stSidebarNavLink"] {
		border-radius: 6px !important;
		transition: background-color 0.15s !important;
		margin-top: 2px !important;
		margin-bottom: 2px !important;
	}
	/* 侧边栏收起后不占宽 */
	section[data-testid="stSidebar"][aria-expanded="false"] {
		width: 3rem !important;
		min-width: 3rem !important;
	}

	/* ===== 按钮 ===== */
	.stButton > button {
		background-color: #4A7C59 !important; color: #fff !important;
		border: none !important; border-radius: 6px !important;
		transition: all 0.15s ease !important;
	}
	.stButton > button:hover {
		background-color: #3D6B4A !important;
		transform: translateY(-1px);
		box-shadow: 0 2px 8px rgba(74,124,89,0.25);
	}
	.stButton > button[kind="secondary"] {
		background-color: #fff !important; color: #4A7C59 !important;
		border: 1px solid #4A7C59 !important;
	}
	.stButton > button[kind="secondary"]:hover {
		background-color: #E8F0EA !important;
		transform: none; box-shadow: none;
	}
	.stProgress > div > div { background-color: #4A7C59 !important; }

	/* ===== 状态 ===== */
	.stSuccess { background-color: #E8F0EA !important; color: #4A7C59 !important;
		border-left: 3px solid #4A7C59 !important; border-radius: 6px !important; }
	.stWarning { background-color: #FBF5E8 !important; color: #8B6914 !important;
		border-left: 3px solid #D4A017 !important; border-radius: 6px !important; }
	.stError  { background-color: #FDF0ED !important; color: #C0392B !important;
		border-left: 3px solid #C0392B !important; border-radius: 6px !important; }
	.stInfo   { background-color: #EDF4F7 !important; color: #2C5282 !important;
		border-left: 3px solid #2C5282 !important; border-radius: 6px !important; }

	/* ===== 聊天 ===== */
	[data-testid="stChatMessage"] {
		border-radius: 10px !important;
		border: 1px solid #E8E4DA !important;
		margin-bottom: 8px !important;
		background: #fff !important;
	}

	/* ===== 指标卡片 ===== */
	[data-testid="stMetric"] {
		background: #fff !important;
		border: 1px solid #E8E4DA !important;
		border-radius: 10px !important;
		padding: 12px !important;
		box-shadow: 0 1px 3px rgba(0,0,0,0.04) !important;
	}
	[data-testid="stMetric"] label {
		color: #6B6355 !important; font-size: 0.8rem !important;
		font-weight: 500 !important;
	}
	[data-testid="stMetric"] [data-testid="stMetricValue"] {
		font-size: 1.6rem !important; font-weight: 700 !important;
		color: #2C2416 !important;
	}

	/* ===== 表格 / Tabs / 代码 ===== */
	[data-testid="stDataFrame"] {
		border: 1px solid #E8E4DA !important;
		border-radius: 8px !important;
	}
	.stTabs [data-baseweb="tab"] {
		font-size: 0.95rem !important;
		padding: 8px 16px !important;
	}
	.stTabs [data-baseweb="tab"][aria-selected="true"] {
		color: #4A7C59 !important;
		border-bottom-color: #4A7C59 !important;
	}
	code {
		font-size: 0.85rem !important;
		background: #F2EFE9 !important;
		padding: 2px 6px !important;
		border-radius: 4px !important;
	}
	pre {
		border: 1px solid #E8E4DA !important;
		border-radius: 8px !important;
		background: #FAF8F5 !important;
	}
	</style>
	""", unsafe_allow_html=True)
