"""
评分配置页
"""
import streamlit as st
import os, sys, json, yaml
from copy import deepcopy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.ui_style import inject; inject()

if not st.session_state.get("authenticated", False):
    st.warning("请先在首页登录")
    st.stop()

st.title("评分配置")

rubric_path = st.session_state.get("rubric_path", "data/rubric.json")
config_path = st.session_state.get("config_path", "config.yaml")

if not os.path.exists(rubric_path):
    st.error("未找到评分标准。请先在「阅卷」页上传。")
    st.stop()

from src.utils import load_rubric, load_config
rubric = load_rubric(rubric_path)
if rubric is None:
    st.error("评分标准加载失败")
    st.stop()
st.session_state.rubric = rubric

config = load_config(config_path)
if "grading_mode" not in st.session_state:
    st.session_state.grading_mode = config.get("grading", {}).get("mode", "relaxed")

# ============================================================
#  预置模式 + 自定义预设
# ============================================================
builtin_tiers = {
    "relaxed": {"切题": (0.90, 1.0), "切题_截图": (0.70, 0.80), "切题_无视频": (0.70, 0.80),
                 "切题_无链接": (0.70, 0.80), "跑题": (0.45, 0.55), "敷衍": (0.40, 0.50),
                 "空": (0, 0), "desc": "鼓励为主，有做就给高分"},
    "normal":  {"切题": (0.80, 1.0), "切题_截图": (0.60, 0.75), "切题_无视频": (0.60, 0.75),
                 "切题_无链接": (0.60, 0.75), "跑题": (0.35, 0.50), "敷衍": (0.30, 0.45),
                 "空": (0, 0), "desc": "平衡鼓励与要求"},
    "strict":  {"切题": (0.75, 1.0), "切题_截图": (0.50, 0.70), "切题_无视频": (0.50, 0.70),
                 "切题_无链接": (0.50, 0.70), "跑题": (0.25, 0.40), "敷衍": (0.20, 0.35),
                 "空": (0, 0), "desc": "有错必扣，高分只给优秀"},
}
mode_names = {"relaxed": "宽松", "normal": "标准", "strict": "严格", "custom": "自定义"}

# 加载自定义预设
custom_presets = config.get("custom_presets") or {}

# ============================================================
#  Tab 1: 评分模式 & 档位
# ============================================================
tab1, tab2, tab3 = st.tabs(["评分模式 & 档位", "题目 & 权重", "数据检查"])

with tab1:
    # 模式选择
    cur_mode = st.session_state.get("grading_mode", "relaxed")
    builtin_keys = ["relaxed", "normal", "strict"]
    custom_keys = list(custom_presets.keys())
    all_modes = builtin_keys + custom_keys + ["custom"]

    idx = all_modes.index(cur_mode) if cur_mode in all_modes else 0
    sel = st.selectbox(
        "评分模式",
        all_modes,
        index=idx,
        format_func=lambda x: custom_presets[x].get("desc", x) if x in custom_keys else mode_names.get(x, x),
    )

    tiers = config.get("grading", {}).get("tiers", {})
    if not tiers:
        tiers = {}
        config.setdefault("grading", {})["tiers"] = tiers
    penalties = config.get("grading", {}).get("material_penalties", {})

    # 内置预设定义
    builtin_tiers = {
        "relaxed": {
            "贴合主题": (0.90, 1.0), "跑题": (0.45, 0.55), "敷衍": (0.40, 0.50), "空": (0, 0),
            "desc": "鼓励为主，有做就给高分",
        },
        "normal": {
            "贴合主题": (0.80, 1.0), "跑题": (0.35, 0.50), "敷衍": (0.30, 0.45), "空": (0, 0),
            "desc": "平衡鼓励与要求",
        },
        "strict": {
            "贴合主题": (0.75, 1.0), "跑题": (0.25, 0.40), "敷衍": (0.20, 0.35), "空": (0, 0),
            "desc": "有错必扣，高分只给优秀",
        },
    }
    builtin_penalties = {
        "relaxed": {"仅截图": 0.10, "无视频": 0.10, "无图像": 0.10, "无表格": 0.10, "无链接": 0.05},
        "normal":  {"仅截图": 0.15, "无视频": 0.15, "无图像": 0.15, "无表格": 0.15, "无链接": 0.10},
        "strict":  {"仅截图": 0.20, "无视频": 0.20, "无图像": 0.20, "无表格": 0.20, "无链接": 0.15},
    }

    tier_keys = ["贴合主题", "跑题", "敷衍", "空"]
    penalty_keys = ["仅截图", "无视频", "无图像", "无表格", "无链接"]

    # 确定当前编辑的档位值
    if sel in builtin_keys:
        st.session_state.grading_mode = sel
        current_tiers = {}
        for tk in tier_keys:
            rmin, rmax = builtin_tiers[sel].get(tk, (0.5, 1.0))
            current_tiers[tk] = {"ratio_min": rmin, "ratio_max": rmax, "desc": ""}
        current_penalties = dict(builtin_penalties.get(sel, builtin_penalties["normal"]))
        is_editable = False
    elif sel in custom_keys:
        st.session_state.grading_mode = sel
        preset = custom_presets[sel]
        current_tiers = deepcopy(preset.get("tiers", {}))
        current_penalties = deepcopy(preset.get("material_penalties", {}))
        is_editable = True
    else:  # "custom"
        st.session_state.grading_mode = "custom"
        current_tiers = deepcopy(tiers)
        current_penalties = deepcopy(penalties)
        for tk in tier_keys:
            if tk not in current_tiers:
                current_tiers[tk] = {"ratio_min": 0.7, "ratio_max": 0.9, "desc": ""}
        for pk in penalty_keys:
            if pk not in current_penalties:
                current_penalties[pk] = 0.15
        is_editable = True

    mode_label = custom_presets[sel].get("desc", sel) if sel in custom_keys else mode_names.get(sel, sel)
    st.caption(f"当前模式：{mode_label}" + ("（预设，仅供查看）" if not is_editable else "（可编辑）"))

    st.divider()

    # ===== 主题档位区 =====
    st.subheader("📊 主题档位")
    st.caption("判定规则：贴合主题（关键词≥2匹配）→ 跑题（关键词不足）→ 敷衍（内容过少）→ 空（无内容）")

    edited_tiers = {}
    tcols = st.columns(4)
    for i, tk in enumerate(tier_keys):
        with tcols[i]:
            with st.container(border=True):
                st.caption(tk)
                td = current_tiers.get(tk, {"ratio_min": 0.7, "ratio_max": 0.9})
                rmin = st.slider("最低", 0.0, 1.0, float(td.get("ratio_min", 0.7)),
                                 step=0.05, key=f"tmin_{tk}", disabled=not is_editable)
                rmax = st.slider("最高", 0.0, 1.0, float(td.get("ratio_max", 0.9)),
                                 step=0.05, key=f"tmax_{tk}", disabled=not is_editable)
                edited_tiers[tk] = {"ratio_min": rmin, "ratio_max": rmax, "desc": ""}

    st.divider()

    # ===== 素材扣分区 =====
    st.subheader("📎 素材扣分")
    st.caption("每个缺失标记从基础分中扣除对应比例，可多个叠加。空提交不参与素材扣分。")

    edited_penalties = {}
    pcols = st.columns(5)
    for i, pk in enumerate(penalty_keys):
        with pcols[i]:
            with st.container(border=True):
                st.caption(pk)
                cp = current_penalties.get(pk, 0.15)
                val = st.slider("扣分比例", 0.0, 0.4, float(cp),
                                step=0.05, key=f"pen_{pk}", disabled=not is_editable)
                edited_penalties[pk] = val

    # 分数示例
    with st.expander("💡 分数预览（满分20分的题）", expanded=False):
        st.caption("主题档位 × 素材扣分组合效果：")
        ec = st.columns(4)
        for ei, tk in enumerate(tier_keys):
            td = edited_tiers.get(tk, {"ratio_min": 0.5, "ratio_max": 1.0})
            with ec[ei % 4]:
                base = f"{int(20 * td['ratio_min'])}-{int(20 * td['ratio_max'])}"
                st.metric(f"【{tk}】", f"{base}分")
        st.caption("— 叠加素材扣分后（以 贴合主题 为例）—")
        fc = st.columns(5)
        for fi, pk in enumerate(penalty_keys):
            pp = edited_penalties.get(pk, 0)
            ti = edited_tiers.get("贴合主题", {"ratio_min": 0.9})
            lo = max(0, int(20 * (ti["ratio_min"] - pp)))
            hi = max(1, int(20 * (1.0 - pp)))
            with fc[fi % 5]:
                st.metric(f"+{pk}", f"{lo}-{hi}分", delta=f"-{int(pp*100)}%")

    # 保存按钮
    st.divider()
    cs1, cs2, cs3 = st.columns([1.2, 1.2, 2])
    with cs1:
        if st.button("💾 保存当前配置", type="primary", use_container_width=True,
                     disabled=not is_editable):
            config.setdefault("grading", {})["mode"] = "custom" if sel == "custom" else sel
            config["grading"]["tiers"] = edited_tiers
            config["grading"]["material_penalties"] = edited_penalties
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            st.session_state.grading_mode = "custom" if sel == "custom" else sel
            st.success("已保存！")
            st.rerun()
    with cs2:
        if is_editable:
            preset_name = st.text_input("预设名称", placeholder="例如：我的评分方案", key="preset_name")
            if st.button("💾 另存为新预设", use_container_width=True,
                         disabled=not preset_name):
                config.setdefault("custom_presets", {})[preset_name] = {
                    "desc": preset_name,
                    "tiers": edited_tiers,
                    "material_penalties": edited_penalties,
                }
                config["grading"]["mode"] = preset_name
                with open(config_path, "w", encoding="utf-8") as f:
                    yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
                st.session_state.grading_mode = preset_name
                st.success(f"预设「{preset_name}」已保存！")
                st.rerun()
    with cs3:
        if sel in custom_keys:
            if st.button("🗑 删除此预设", use_container_width=True):
                config.setdefault("custom_presets", {}).pop(sel, None)
                config["grading"]["mode"] = "relaxed"
                with open(config_path, "w", encoding="utf-8") as f:
                    yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
                st.session_state.grading_mode = "relaxed"
                st.success(f"已删除「{sel}」")
                st.rerun()

# ============================================================
#  Tab 2: 题目 & 权重
# ============================================================
with tab2:
    st.subheader("题目 & 评分项权重")
    questions = rubric.get("questions", [])

    for qi, q in enumerate(questions):
        with st.expander(f"Q{q['id']} {q['name']} — {q['max_score']}分 [{q.get('grading_type','text')}]",
                         expanded=(qi == 0)):
            with st.container(border=True):
                c1, c2, c3 = st.columns(3)
                with c1:
                    q["name"] = st.text_input("名称", value=q.get("name", ""), key=f"qn_{qi}")
                with c2:
                    gtypes = ["text", "vision", "code", "hybrid"]
                    gn = {"text": "文字生成", "vision": "图像/视频", "code": "纯代码(零token)", "hybrid": "智能体"}
                    cur = q.get("grading_type", "text")
                    gi = gtypes.index(cur) if cur in gtypes else 0
                    q["grading_type"] = st.selectbox("评分类型", gtypes, index=gi,
                                                      format_func=lambda x: gn.get(x, x), key=f"qtype_{qi}")
                with c3:
                    q["max_score"] = st.number_input("满分", value=int(q.get("max_score", 20)),
                                                      min_value=1, max_value=100, key=f"qmax_{qi}")

                kws = st.text_input("切题关键词（逗号分隔）",
                                     value=", ".join(q.get("topic_keywords", [])),
                                     key=f"qkws_{qi}", placeholder="例如：茶艺, 茶文化, 茶道")
                q["topic_keywords"] = [k.strip() for k in kws.split(",") if k.strip()]

            st.caption("评分项")
            criteria = q.get("criteria", [])
            for ci, c in enumerate(criteria):
                cc1, cc2, cc3, cc4 = st.columns([3, 1.2, 1.2, 2.5])
                with cc1:
                    c["name"] = st.text_input("名称", value=c.get("name", ""),
                                              key=f"cn_{qi}_{ci}", label_visibility="collapsed")
                with cc2:
                    c["id"] = st.text_input("ID", value=c.get("id", f"{q['id']}-{ci+1}"),
                                            key=f"cid_{qi}_{ci}", label_visibility="collapsed")
                with cc3:
                    c["max"] = st.number_input("满分", value=int(c.get("max", 1)),
                                               min_value=1, max_value=q["max_score"],
                                               key=f"cm_{qi}_{ci}", label_visibility="collapsed")
                with cc4:
                    c["desc"] = st.text_input("说明", value=c.get("desc", ""),
                                              key=f"cd_{qi}_{ci}", label_visibility="collapsed")

            bc1, bc2, bc3 = st.columns(3)
            with bc1:
                if st.button("➕ 加评分项", key=f"addc_{qi}", use_container_width=True):
                    criteria.append({"id": f"{q['id']}-{len(criteria)+1}", "name": "新评分项", "max": 5, "desc": ""})
                    st.rerun()
            with bc2:
                if len(criteria) > 1 and st.button("➖ 删最后一项", key=f"delc_{qi}", use_container_width=True):
                    criteria.pop()
                    st.rerun()
            with bc3:
                st.caption(f"共 {len(criteria)} 项 · 满分合计 {sum(c['max'] for c in criteria)}")

    st.divider()
    bc3, bc4, bc5 = st.columns(3)
    with bc3:
        if st.button("➕ 添加题目", use_container_width=True):
            nid = len(questions) + 1
            questions.append({
                "id": nid, "name": "新题目", "max_score": 20,
                "grading_type": "text", "description": "",
                "topic_keywords": [], "submission_labels": [],
                "data_checks": None,
                "criteria": [{"id": f"{nid}-1", "name": "得分项1", "max": 10, "desc": ""}],
            })
            st.rerun()
    with bc4:
        if len(questions) > 1 and st.button("➖ 删除最后一题", use_container_width=True):
            questions.pop()
            st.rerun()
    with bc5:
        if st.button("💾 保存题目配置", type="primary", use_container_width=True):
            rubric["exam"]["total_score"] = sum(q["max_score"] for q in questions)
            with open(rubric_path, "w", encoding="utf-8") as f:
                json.dump(rubric, f, ensure_ascii=False, indent=2)
            st.session_state.rubric = rubric
            st.success("题目配置已保存！")
            st.rerun()

# ============================================================
#  Tab 3: 数据检查
# ============================================================
with tab3:
    st.subheader("数据检查规则")
    st.caption("仅对评分类型为「纯代码(code)」的题目生效")

    cqs = [q for q in questions if q.get("grading_type") == "code"]
    if not cqs:
        st.info("当前没有 code 类型题目。在「题目 & 权重」中将题目评分类型改为「纯代码」即可。")
    else:
        for q in cqs:
            with st.expander(f"Q{q['id']} {q['name']} — 数据检查"):
                checks = q.get("data_checks") or {}
                if not checks:
                    checks = {}
                    q["data_checks"] = checks

                with st.container(border=True):
                    checks["dedup"] = st.checkbox("去重检查", value=checks.get("dedup", False), key=f"dc_{q['id']}")

                st.caption("缺失值检查")
                with st.container(border=True):
                    fillna = checks.get("fillna", {})
                    if not isinstance(fillna, dict): fillna = {}
                    fp = st.text_input("列名正则", value=fillna.get("column_pattern", ""),
                                       key=f"fn_{q['id']}", placeholder="金额|价|amount")
                    if fp: fillna["column_pattern"] = fp; checks["fillna"] = fillna
                    else: checks.pop("fillna", None)

                st.caption("日期格式检查")
                with st.container(border=True):
                    df_cfg = checks.get("date_format", {})
                    if not isinstance(df_cfg, dict): df_cfg = {}
                    dc1, dc2 = st.columns(2)
                    with dc1:
                        dp = st.text_input("日期列正则", value=df_cfg.get("column_pattern", ""),
                                           key=f"dt_{q['id']}", placeholder="日期|时间|date")
                    with dc2:
                        dft = st.text_input("格式", value=df_cfg.get("format", "YYYY-MM-DD"), key=f"dtf_{q['id']}")
                    if dp: df_cfg["column_pattern"] = dp; df_cfg["format"] = dft; checks["date_format"] = df_cfg
                    else: checks.pop("date_format", None)

                st.caption("排序检查")
                with st.container(border=True):
                    sc = checks.get("sort", {})
                    if not isinstance(sc, dict): sc = {}
                    sp = st.text_input("排序列正则", value=sc.get("column_pattern", ""),
                                       key=f"sort_{q['id']}", placeholder="日期|时间|date")
                    if sp: sc["column_pattern"] = sp; checks["sort"] = sc
                    else: checks.pop("sort", None)

        if st.button("💾 保存检查规则", type="primary"):
            with open(rubric_path, "w", encoding="utf-8") as f:
                json.dump(rubric, f, ensure_ascii=False, indent=2)
            st.session_state.rubric = rubric
            st.success("已保存！")
