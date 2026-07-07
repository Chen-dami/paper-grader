"""
评分配置页
"""
import streamlit as st
import os, sys, json, yaml, pandas as pd
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
        "relaxed": {"贴合主题": (1.0, 1.0), "跑题": (0.40, 0.70),
                    "有视频": (1.0, 1.0), "无视频": (0.20, 0.50),
                    "有图像": (1.0, 1.0), "无图像": (0.20, 0.50),
                    "有截图": (1.0, 1.0), "无截图": (0.20, 0.50),
                    "有表格": (1.0, 1.0),
                    "有链接": (1.0, 1.0), "无链接": (0.20, 0.50),
                    "素材不足": (0.25, 0.60), "敷衍": (0.15, 0.40),
                    "空": (0, 0), "desc": "正确即满分，材料齐全=100%"},
        "normal":  {"贴合主题": (1.0, 1.0), "跑题": (0.30, 0.50),
                    "有视频": (1.0, 1.0), "无视频": (0.20, 0.40),
                    "有图像": (1.0, 1.0), "无图像": (0.20, 0.40),
                    "有截图": (1.0, 1.0), "无截图": (0.20, 0.40),
                    "有表格": (1.0, 1.0),
                    "有链接": (1.0, 1.0), "无链接": (0.15, 0.35),
                    "素材不足": (0.20, 0.50), "敷衍": (0.15, 0.35),
                    "空": (0, 0), "desc": "材料全即满分"},
        "strict":  {"贴合主题": (0.80, 1.0), "跑题": (0.00, 0.20),
                    "有视频": (0.80, 1.0), "无视频": (0.00, 0.20),
                    "有图像": (0.80, 1.0), "无图像": (0.00, 0.20),
                    "有截图": (0.80, 1.0), "无截图": (0.00, 0.20),
                    "有表格": (0.80, 1.0),
                    "有链接": (0.80, 1.0), "无链接": (0.00, 0.00),
                    "素材不足": (0.00, 0.30), "敷衍": (0.00, 0.10),
                    "空": (0, 0), "desc": "答得好才满分"},
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

    # 档位 → 素材检测 → 得分的关联对照表
    with st.expander("评分逻辑说明", expanded=False):
        st.markdown("""
        **档位检测流程**：系统自动检查学生提交内容 → 按优先级判定档位 → 在档位范围内打分

        | 检测到的情况 | 判定档位 | 含义 |
        |------------|---------|------|
        | 有文字 + 有关键词 + 有截图 | 有截图 | 内容+素材都齐全 |
        | 有文字 + 有关键词 + 有视频 | 有视频 | 视频题专属 |
        | 有文字 + 有关键词 + 有发布链接 | 有链接 | 智能体题专属 |
        | 有文字 + 有关键词 + 所有素材 | 贴合主题 | 最高档位 |
        | 有关键词但没素材 | 无截图/无视频/无链接 | 缺少证明材料 |
        | 文字很短（text<50字） | 敷衍 | 基本没做 |
        | 关键词完全不匹配 | 跑题 | 答非所问 |
        | 文本<10字且无媒体 | 空 | 没提交 |

        **评分规则**：
        - 进入某个档位后，AI 在该档位的分数范围内精细评分
        - 比如"有截图"最低 95% → 20分题最少得 19分
        - "跑题"最高 80% → 20分题最多得 16分
        - 代码题无Excel文件：有截图最多30%，无截图0%
        """)

    # 各题型的素材需求一览
    with st.expander("各题型素材需求", expanded=False):
        qlist = rubric.get("questions", [])
        if qlist:
            rows = []
            for q in qlist:
                gtype = q.get("grading_type", "text")
                needs = []
                if gtype == "text":
                    needs = ["✅ 提示词文本", "✅ 生成结果截图"]
                elif gtype == "vision":
                    if "视频" in q.get("name", ""):
                        needs = ["✅ 图片提示词", "✅ 生成图片", "✅ 视频提示词", "✅ 视频文件", "✅ 截图"]
                    else:
                        needs = ["✅ 提示词", "✅ 设计图/海报", "✅ 截图"]
                elif gtype == "code":
                    needs = ["✅ 提示词", "✅ Excel文件(嵌入)", "✅ 截图"]
                elif gtype == "hybrid":
                    needs = ["✅ 人设/回复逻辑文本", "✅ 知识库截图", "✅ 全屏截图", "✅ 发布链接(需可访问)"]
                elif gtype in ("multiple_choice", "true_false", "fill_blank", "short_answer"):
                    needs = ["✅ 答案（精确匹配/关键词匹配）"]
                rows.append(f"**Q{q['id']} {q['name']}** ({gtype})：{' · '.join(needs)}")
            st.markdown("\n\n".join(rows))

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
                    raw_max = int(q.get("max_score", 0) or 0)
                    q["max_score"] = st.number_input("满分", value=max(raw_max, 1),
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
                    raw_c_max = int(c.get("max", 1) or 0)
                    c["max"] = st.number_input("满分", value=max(raw_c_max, 1),
                                               min_value=1, max_value=max(q.get("max_score", 20), 1),
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
                checks = q.get("data_checks")
                # 防御：LLM 可能把 data_checks 解析成 list 等非 dict 类型
                if not isinstance(checks, dict):
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
# ============================================================
#  Tab 4: 模型路由
# ============================================================
with tab4:
    st.subheader("多模型路由配置")

    # ---- 评分流水线说明 ----
    with st.expander("📖 评分流水线说明", expanded=False):
        st.markdown("""
        **两阶段评分流水线（省钱设计）**

        | 阶段 | 模型 | 任务 | 费用 |
        |------|------|------|------|
        | Stage 1 | 视觉模型（如 Qwen-VL-Plus） | 看图 → 输出文字描述 | 输入贵但输出极短 |
        | Stage 2 | DeepSeek-Chat | 根据描述评分 | 输入/输出都极便宜 |

        > 相比让视觉模型直接评分，**省了 70-90% 的 API 费用**。
        > 视觉模型只负责"看到了什么"，DeepSeek 负责"该打多少分"。
        """)

    # ---- 环境检测（用户主动点击，避免启动时被标记为危险应用） ----
    if "_keys_status" not in st.session_state:
        st.session_state._keys_status = {}
    if "_keys_checked" not in st.session_state:
        st.session_state._keys_checked = False

    det_col1, det_col2 = st.columns([1, 3])
    with det_col1:
        if st.button("🔍 检测API Key", use_container_width=True, type="primary"):
            st.session_state._keys_status = router.available_keys()
            st.session_state._keys_checked = True
            st.rerun()

    keys_status = st.session_state._keys_status
    if st.session_state._keys_checked:
        avail_platforms = [k for k, v in keys_status.items() if v]
        if avail_platforms:
            st.success(f"🔑 已配置：{' · '.join(avail_platforms)}")
        else:
            st.warning("⚠️ 未检测到任何 API Key！请在环境变量中设置后重新检测。")
            st.caption("常用环境变量：`BAILIAN_KEY`（阿里云）、`ZHIPU_KEY`（智谱）、`DEEPSEEK_KEY`（DeepSeek）")
    else:
        st.info("💡 点击上方按钮检测已配置的 API Key（不会发送网络请求，仅读取本地环境变量）")

    # ---- 模型能力表 ----
    with st.expander("📊 模型能力速查", expanded=False):
        _rows = []
        for name, info in router.MODEL_REGISTRY.items():
            has_key = bool(os.environ.get(info.get("env_key", ""), ""))
            vis = "🟢" if info["vision"] else "⚫"
            img = info.get("image_limit", 0)
            img_s = f"{img}张" if img > 0 else "-"
            mt = info.get("max_tokens", 0)
            mt_s = f"{mt//1024}K" if mt >= 1024 else str(mt)
            ci = info.get("cost_per_1M_input", 0)
            if ci == 0:
                cost_s = "🆓"
            else:
                est = (ci * 5000 / 1e6) + (info.get("cost_per_1M_output", 0) * 150 / 1e6)
                cost_s = f"≈¥{est:.3f}/次"
            _rows.append({
                "模型": name,
                "视觉": vis,
                "图片": img_s,
                "输出": mt_s,
                "单次≈": cost_s,
                "状态": "✅" if has_key else "⚪",
            })
        st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True)

    # ---- 一键推荐（根据检测结果自动适配） ----
    _has_ds = keys_status.get("DeepSeek", False) if st.session_state._keys_checked else False
    _has_zhipu = keys_status.get("智谱(GLM)", False) if st.session_state._keys_checked else False
    _has_qwen = keys_status.get("阿里云(Qwen)", False) if st.session_state._keys_checked else False
    _has_openai = keys_status.get("OpenAI", False) if st.session_state._keys_checked else False

    if st.session_state._keys_checked:
        st.markdown("**💡 推荐方案**")

    _rec_cols = st.columns(3 if _has_qwen else 2)

    if _has_qwen:
        with _rec_cols[0]:
            if st.button("🟢 均衡推荐", help="文本DeepSeek + 视觉Qwen-VL-Plus(5图)", use_container_width=True,
                         disabled=not _has_ds):
                config.setdefault("model_router", {})
                config["model_router"]["text_model"] = "deepseek-chat" if _has_ds else "glm-4v-flash"
                config["model_router"]["vision_model"] = "qwen-vl-plus"
                config["model_router"]["high_value_model"] = "qwen-vl-max"
                config["model_router"]["vision_fallback"] = ["qwen-vl-max", "glm-4v-flash"]
                with open(config_path, "w", encoding="utf-8") as f:
                    yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
                st.toast("✅ 均衡推荐已保存", icon="✅")
                st.rerun()

    with _rec_cols[1] if _has_qwen else _rec_cols[0]:
        if st.button("🆓 免费方案", help="智谱免费视觉(1图)+DeepSeek文本", use_container_width=True,
                     disabled=not _has_zhipu and not _has_ds):
            config.setdefault("model_router", {})
            config["model_router"]["text_model"] = "deepseek-chat" if _has_ds else "glm-4v-flash"
            config["model_router"]["vision_model"] = "glm-4v-flash"
            config["model_router"]["high_value_model"] = "glm-4v-flash"
            config["model_router"]["vision_fallback"] = ["qwen-vl-max"] if _has_qwen else ["glm-4v"]
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            st.toast("🆓 免费方案已保存（视觉仅1图）", icon="⚠️")
            st.rerun()

    last_col = 2 if _has_qwen else 1
    with _rec_cols[last_col] if _has_qwen else _rec_cols[last_col - 1]:
        if st.button("🏆 最强质量", help="视觉Qwen-VL-Max(10图)，全面评估", use_container_width=True,
                     disabled=not _has_qwen and not _has_openai):
            config.setdefault("model_router", {})
            config["model_router"]["text_model"] = "deepseek-chat"
            config["model_router"]["vision_model"] = "qwen-vl-max" if _has_qwen else "gpt-4o"
            config["model_router"]["high_value_model"] = "qwen-vl-max" if _has_qwen else "gpt-4o"
            config["model_router"]["high_value_threshold"] = 15
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            st.toast("🏆 最强质量已保存", icon="🏆")
            st.rerun()

    st.caption("根据当前环境自动适配：有Qwen用Qwen，只有智谱用免费版")

    st.divider()

    # ---- 手动配置 ----
    rc = config.get("model_router") or {}
    if not rc:
        rc = {}
        config["model_router"] = rc

    # 构建带标签的下拉选项
    dropdown_opts = router.models_for_dropdown()
    model_names = [m[0] for m in dropdown_opts]
    model_labels = [m[1] for m in dropdown_opts]

    def _smart_select(label, key, default):
        cur = rc.get(key, default)
        # 如果当前值不在可用列表中，添加进去（可能未配Key但已选）
        if cur not in model_names:
            model_names.append(cur)
            info = router.MODEL_REGISTRY.get(cur, {})
            model_labels.append(f"{cur} [{router.model_tier_label(cur)}]")
        try:
            idx = model_names.index(cur)
        except ValueError:
            idx = 0
        # 用 selectbox + format_func
        return st.selectbox(label, range(len(model_names)), index=idx,
                          format_func=lambda i: model_labels[i], key=f"mr_{key}")

    st.markdown("**手动配置**")
    mc1, mc2 = st.columns(2)
    with mc1:
        idx = _smart_select("📝 文本题", "text_model", "deepseek-chat")
        rc["text_model"] = model_names[idx]
        idx2 = _smart_select("👁️ 视觉题", "vision_model", "qwen-vl-plus" if _has_qwen else "glm-4v-flash")
        rc["vision_model"] = model_names[idx2]
        idx3 = _smart_select("🔍 档位判定", "tier_model", "deepseek-chat")
        rc["tier_model"] = model_names[idx3]
    with mc2:
        idx4 = _smart_select("💎 大分值题", "high_value_model", "qwen-vl-max" if _has_qwen else "glm-4v-flash")
        rc["high_value_model"] = model_names[idx4]
        rc["high_value_threshold"] = st.number_input("大分值阈值(分)", value=int(rc.get("high_value_threshold", 25)),
                                                      min_value=5, max_value=50, key="mr_thresh")

    # 当前选择效果说明
    cur_vis = rc.get("vision_model", "")
    vi = router.MODEL_REGISTRY.get(cur_vis, {})
    img_lim = vi.get("image_limit", 0)
    tier = img_lim if vi.get("vision") else 0

    tier_desc = {
        0: ("📝 纯文本模式", "无视觉模型，靠文字描述判断。视觉相关项以提示词为准。"),
        1: ("🆓 免费视觉(1图)→DeepSeek", "视觉模型描述1张图，DeepSeek评分。视频题看1帧，无法评估动态/配音。"),
        5: ("💰 付费视觉(5图)→DeepSeek", "视觉模型描述3-5张图，DeepSeek评分。视频题看3帧+生成图。"),
        10: ("💰 付费视觉(10图)→DeepSeek", "视觉模型描述多图，DeepSeek评分。全面评估，所有素材都看到。"),
    }
    desc_key = img_lim if img_lim in (0, 1, 5, 10) else (5 if img_lim >= 5 else 1)
    _title, _desc = tier_desc.get(desc_key, tier_desc[0])

    with st.container(border=True):
        st.markdown(f"**当前方案：{_title}**")
        st.caption(_desc)

    st.divider()
    st.markdown("**Fallback 备用链**")
    st.caption("主模型失败时依次尝试。可输入逗号分隔的模型名。")
    fc1, fc2 = st.columns(2)
    with fc1:
        vf = st.text_input("视觉 Fallback", value=", ".join(rc.get("vision_fallback", ["qwen-vl-max", "glm-4v", "glm-4v-flash"])), key="mr_vf")
        rc["vision_fallback"] = [m.strip() for m in vf.split(",") if m.strip()]
    with fc2:
        tf = st.text_input("文本 Fallback", value=", ".join(rc.get("text_fallback", ["deepseek-chat"])), key="mr_tf")
        rc["text_fallback"] = [m.strip() for m in tf.split(",") if m.strip()]

    if st.button("💾 保存路由配置", type="primary"):
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        st.success("已保存，下次评分生效")
