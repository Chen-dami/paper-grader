"""
评分配置页
"""
import streamlit as st
import os, sys, json, yaml
from copy import deepcopy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.ui_style import inject; inject()
from src import model_router as router

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
#  Tab 1: 评分模式 & 档位
# ============================================================
tab1, tab2, tab3, tab4 = st.tabs(["评分模式 & 档位", "题目 & 权重", "数据检查", "模型路由"])

mode_names = {"relaxed": "宽松", "normal": "标准", "strict": "严格", "custom": "自定义"}
custom_presets = config.get("custom_presets") or {}

with tab1:
    cur_mode = st.session_state.get("grading_mode", "relaxed")
    builtin_keys = ["relaxed", "normal", "strict"]
    custom_keys = list(custom_presets.keys())
    all_modes = builtin_keys + custom_keys + ["custom"]

    idx = all_modes.index(cur_mode) if cur_mode in all_modes else 0
    sel = st.selectbox("评分模式", all_modes, index=idx,
        format_func=lambda x: custom_presets[x].get("desc", x) if x in custom_keys else mode_names.get(x, x))

    tiers = config.get("grading", {}).get("tiers", {})
    if not tiers:
        tiers = {}
        config.setdefault("grading", {})["tiers"] = tiers

    builtin_tiers = {
        "relaxed": {"贴合主题": (1.0, 1.0), "跑题": (0.50, 0.80),
                    "有视频": (0.90, 1.0), "无视频": (0.30, 0.50),
                    "有截图": (0.90, 1.0), "无截图": (0.30, 0.50),
                    "有表格": (0.90, 1.0),
                    "有链接": (0.90, 1.0), "无链接": (0.30, 0.50),
                    "素材不足": (0.30, 0.70), "敷衍": (0.25, 0.50),
                    "空": (0, 0), "desc": "鼓励为主（底80）"},
        "normal":  {"贴合主题": (0.90, 1.0), "跑题": (0.30, 0.50),
                    "有视频": (0.70, 1.0), "无视频": (0.30, 0.40),
                    "有截图": (0.70, 1.0), "无截图": (0.30, 0.40),
                    "有表格": (0.70, 1.0),
                    "有链接": (0.70, 1.0), "无链接": (0.00, 0.15),
                    "素材不足": (0.20, 0.50), "敷衍": (0.25, 0.50),
                    "空": (0, 0), "desc": "标准（底50）"},
        "strict":  {"贴合主题": (0.80, 1.0), "跑题": (0.00, 0.20),
                    "有视频": (0.50, 1.0), "无视频": (0.00, 0.20),
                    "有截图": (0.50, 1.0), "无截图": (0.00, 0.20),
                    "有表格": (0.50, 1.0),
                    "有链接": (0.50, 1.0), "无链接": (0.00, 0.00),
                    "素材不足": (0.00, 0.30), "敷衍": (0.00, 0.10),
                    "空": (0, 0), "desc": "严格（底20）"},
    }

    # 模式切换时从源重新加载 working_tiers
    last_sel = st.session_state.get("_last_mode_sel", "")
    if sel != last_sel:
        st.session_state._last_mode_sel = sel
        if sel in builtin_keys:
            wt = {}
            for tk, v in builtin_tiers[sel].items():
                if tk == "desc": continue
                wt[tk] = {"ratio_min": v[0], "ratio_max": v[1], "desc": ""}
            st.session_state.working_tiers = wt
        elif sel in custom_keys:
            st.session_state.working_tiers = deepcopy(custom_presets[sel].get("tiers", {}))
        else:
            st.session_state.working_tiers = deepcopy(tiers)

    if "working_tiers" not in st.session_state:
        st.session_state.working_tiers = deepcopy(tiers)

    current_tiers = st.session_state.working_tiers
    is_editable = sel not in builtin_keys

    mode_label = custom_presets[sel].get("desc", sel) if sel in custom_keys else mode_names.get(sel, sel)
    st.caption(f"当前：{mode_label}" + ("（预设，仅查看）" if not is_editable else "（可编辑）"))

    st.divider()
    st.subheader("档位设置")

    # 添加按钮
    if is_editable:
        ac1, ac2 = st.columns([1, 3])
        with ac1:
            new_name = st.text_input("新档位名", placeholder="如：有表格", key="new_tier_name")
        with ac2:
            st.caption("")
            if st.button("➕ 添加", disabled=not new_name, key="add_tier_btn"):
                if new_name not in current_tiers:
                    current_tiers[new_name] = {"ratio_min": 0.5, "ratio_max": 0.75, "desc": ""}
                    st.session_state.working_tiers = current_tiers
                    st.rerun()

    # 档位列表 — 每行2个
    edited_tiers = {}
    del_keys = []
    tkeys = list(current_tiers.keys())
    for i in range(0, len(tkeys), 2):
        cols = st.columns(2)
        for j in range(2):
            if i + j >= len(tkeys):
                break
            tk = tkeys[i + j]
            with cols[j]:
                with st.container(border=True):
                    tc1, tc2 = st.columns([4, 1])
                    with tc1:
                        st.caption(tk)
                    with tc2:
                        if is_editable and tk not in ("空", "敷衍", "跑题", "贴合主题"):
                            if st.button("✕", key=f"del_{tk}"):
                                del current_tiers[tk]
                                st.session_state.working_tiers = current_tiers
                                st.rerun()

                    td = current_tiers.get(tk, {"ratio_min": 0.5, "ratio_max": 0.75})
                    rmin = st.slider("最低", 0.0, 1.0, float(td.get("ratio_min", 0.5)),
                                     step=0.05, key=f"tmin_{sel}_{tk}", disabled=not is_editable)
                    rmax = st.slider("最高", 0.0, 1.0, float(td.get("ratio_max", 0.75)),
                                     step=0.05, key=f"tmax_{sel}_{tk}", disabled=not is_editable)
                    edited_tiers[tk] = {"ratio_min": rmin, "ratio_max": rmax, "desc": ""}
                    current_tiers[tk] = edited_tiers[tk]
    st.session_state.working_tiers = current_tiers

    # 分数预览
    with st.expander("分数预览（20分题）", expanded=False):
        ec = st.columns(4)
        for ei, (tk, td) in enumerate(edited_tiers.items()):
            with ec[ei % 4]:
                lo = int(20 * td["ratio_min"])
                hi = int(20 * td["ratio_max"])
                st.metric(tk, f"{lo}-{hi}分")

    # 保存
    st.divider()
    cs1, cs2, cs3 = st.columns([1.2, 1.2, 2])
    with cs1:
        if st.button("💾 保存", type="primary", use_container_width=True, disabled=not is_editable):
            config.setdefault("grading", {})["mode"] = "custom" if sel == "custom" else sel
            config["grading"]["tiers"] = edited_tiers
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            st.session_state.grading_mode = "custom" if sel == "custom" else sel
            st.session_state.working_tiers = edited_tiers
            st.success("已保存")
            st.toast("✅ 档位配置已保存", icon="✅")
            st.rerun()
    with cs2:
        if is_editable:
            pn = st.text_input("预设名称", placeholder="如：我的方案", key="preset_name")
            if st.button("💾 另存为预设", use_container_width=True, disabled=not pn):
                config.setdefault("custom_presets", {})[pn] = {"desc": pn, "tiers": edited_tiers}
                config["grading"]["mode"] = pn
                with open(config_path, "w", encoding="utf-8") as f:
                    yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
                st.session_state.grading_mode = pn
                st.session_state.working_tiers = edited_tiers
                st.session_state._last_mode_sel = pn
                st.success(f"「{pn}」已保存")
                st.toast(f"✅ 预设「{pn}」已保存", icon="✅")
                st.rerun()
    with cs3:
        if sel in custom_keys:
            if st.button("🗑 删除预设", use_container_width=True):
                config.setdefault("custom_presets", {}).pop(sel, None)
                config["grading"]["mode"] = "relaxed"
                with open(config_path, "w", encoding="utf-8") as f:
                    yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
                st.session_state.grading_mode = "relaxed"
                st.session_state.working_tiers = {}
                st.session_state._last_mode_sel = ""
                st.success(f"已删除「{sel}」")
                st.toast(f"🗑 预设「{sel}」已删除", icon="🗑")
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
                    gtypes = ["multiple_choice", "true_false", "fill_blank", "short_answer", "text", "vision", "code", "hybrid"]
                    gn = {"multiple_choice": "选择题", "true_false": "判断题", "fill_blank": "填空题", "short_answer": "简答题", "text": "文字生成", "vision": "图像/视频", "code": "纯代码", "hybrid": "智能体"}
                    cur = q.get("grading_type", "text")
                    gi = gtypes.index(cur) if cur in gtypes else 0
                    q["grading_type"] = st.selectbox("评分类型", gtypes, index=gi,
                                                      format_func=lambda x: gn.get(x, x), key=f"qtype_{qi}")
                with c3:
                    q["max_score"] = st.number_input("满分", value=int(q.get("max_score", 20)),
                                                      min_value=1, max_value=100, key=f"qmax_{qi}")

                kws = st.text_input("切题关键词（逗号分隔）",
                                     value=", ".join(q.get("topic_keywords", [])),
                                     key=f"qkws_{qi}", placeholder="如：茶艺, 茶文化, 茶道")
                q["topic_keywords"] = [k.strip() for k in kws.split(",") if k.strip()]

            # 客观题配置
            gtype = q.get("grading_type", "text")
            if gtype in ("multiple_choice", "true_false"):
                ak = q.get("answer_key") or {}
                st.caption("答案设置")
                ac1, ac2 = st.columns(2)
                with ac1:
                    ak["正确答案"] = st.text_input("正确答案", value=ak.get("正确答案", ""),
                                                  key=f"ans_{qi}", placeholder="A / B / C / D / ABCD / 对 / 错")
                with ac2:
                    ak["分值"] = st.number_input("分值", value=int(ak.get("分值", q.get("max_score", 5))),
                                                min_value=1, max_value=q.get("max_score", 20), key=f"ans_s_{qi}")
                q["answer_key"] = ak
            elif gtype == "fill_blank":
                import json as _j
                ak = q.get("answer_key") or {}
                st.caption("填空答案（JSON格式）")
                fb = st.text_area("答案", value=_j.dumps(ak.get("答案", {}), ensure_ascii=False, indent=2),
                                 key=f"fb_{qi}", height=100, placeholder='{"1": "人工智能", "2": ["AI","人工智能"]}')
                try:
                    q["answer_key"] = {"答案": _j.loads(fb)}
                except:
                    st.caption("格式错误")
            elif gtype == "short_answer":
                kp = q.get("key_points") or []
                st.caption("知识点踩分点（每行：关键词=分值）")
                kt = st.text_area("知识点", value=chr(10).join(f"{p.get('keyword','')}={p.get('score',0)}" for p in kp),
                                 key=f"kp_{qi}", height=80, placeholder="去重=3\\n空值填充=3")
                new_kp = []
                for line in kt.strip().split(chr(10)):
                    if "=" in line:
                        kw, sc = line.split("=", 1)
                        new_kp.append({"keyword": kw.strip(), "score": int(sc.strip())})
                if new_kp:
                    q["key_points"] = new_kp

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
                if len(criteria) > 1 and st.button("➖ 删最后项", key=f"delc_{qi}", use_container_width=True):
                    criteria.pop()
                    st.rerun()
            with bc3:
                st.caption(f"{len(criteria)} 项 · 合计 {sum(c['max'] for c in criteria)}")

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
            st.success("已保存")
            st.toast("✅ 题目配置已保存", icon="✅")
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
            with st.expander(f"Q{q['id']} {q['name']}"):
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
            st.success("已保存")
            st.toast("检查规则已保存", icon="✅")

# ============================================================
#  Tab 4: 模型路由
# ============================================================
with tab4:
    st.subheader("多模型路由配置")
    st.caption("按任务类型分发模型：文本题用便宜模型，视觉题用视觉模型。修改后即时生效。")

    rc = config.get("model_router") or {}
    if not rc:
        rc = {}
        config["model_router"] = rc

    model_list = list(router.MODEL_REGISTRY.keys())

    def ms(label, key, default):
        val = rc.get(key, default)
        idx = model_list.index(val) if val in model_list else 0
        desc = router.MODEL_REGISTRY.get(val, {}).get('description', '')[:35]
        return st.selectbox(f"{label} [{val}]", model_list, index=idx,
                           format_func=lambda x: f"{x}", key=f"mr_{key}")

    st.markdown("**任务分配**")
    mc1, mc2 = st.columns(2)
    with mc1:
        rc["text_model"] = ms("文本题模型", "text_model", "deepseek-chat")
        rc["vision_model"] = ms("视觉题模型", "vision_model", "qwen-vl-max")
        rc["tier_model"] = ms("档位判定模型", "tier_model", "gpt-4o-mini")
    with mc2:
        rc["reasoning_model"] = ms("深度推理模型", "reasoning_model", "deepseek-reasoner")
        rc["high_value_model"] = ms("大分值模型", "high_value_model", "gpt-4o")
        rc["high_value_threshold"] = st.number_input("大分值阈值(分)", value=int(rc.get("high_value_threshold", 20)),
                                                      min_value=5, max_value=50, key="mr_thresh")

    st.divider()
    st.markdown("**Fallback 备用链**")
    fc1, fc2 = st.columns(2)
    with fc1:
        vf = st.text_input("视觉 Fallback", value=", ".join(rc.get("vision_fallback", ["gpt-4o", "qwen-vl-max", "glm-4v"])), key="mr_vf")
        rc["vision_fallback"] = [m.strip() for m in vf.split(",") if m.strip()]
    with fc2:
        tf = st.text_input("文本 Fallback", value=", ".join(rc.get("text_fallback", ["deepseek-chat"])), key="mr_tf")
        rc["text_fallback"] = [m.strip() for m in tf.split(",") if m.strip()]

    st.divider()
    st.markdown("**已注册模型**")
    md = []
    for name, info in router.MODEL_REGISTRY.items():
        has_key = bool(__import__('os').environ.get(info["env_key"], ""))
        md.append({
            "模型": name,
            "视觉": "Y" if info["vision"] else "N",
            "特长": info.get("strength", "-"),
            "费用": f"{info['cost_per_1M_input']}/{info['cost_per_1M_output']}",
            "状态": "可用" if has_key else "需配Key",
            "环境变量": info["env_key"],
        })
    import pandas as pd
    st.dataframe(pd.DataFrame(md), use_container_width=True, hide_index=True)

    if st.button("保存路由配置", type="primary"):
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        st.success("已保存，下次评分生效")
