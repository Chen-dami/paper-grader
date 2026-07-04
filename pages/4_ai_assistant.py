"""
AI 助手 -- DeepSeek 风格对话 + 评分配置修改
"""
import streamlit as st
import os, sys, json, copy, yaml, re, time, uuid
from openai import OpenAI

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.ui_style import inject; inject()

if not st.session_state.get("authenticated", False):
    st.warning("请先登录")
    st.stop()

# ============================================================
#  session 初始化
# ============================================================
defaults = {
    "ai_model": "fast",           # fast | deep | vision
    "ai_mode": "chat",            # chat | config
    "ai_threads": {},             # {thread_id: {title, messages, created}}
    "ai_current_thread": None,
    "ai_thread_order": [],        # ordered list of thread_ids
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ============================================================
#  模型配置
# ============================================================
MODELS = {
    "fast": {
        "label": "快速",
        "desc": "DeepSeek-Chat · 日常对话、快速修改",
        "model": "deepseek-chat",
        "vision": False,
    },
    "deep": {
        "label": "深度",
        "desc": "DeepSeek-Reasoner · 复杂推理、深度分析",
        "model": "deepseek-reasoner",
        "vision": False,
    },
    "vision": {
        "label": "识图",
        "desc": "DeepSeek-Chat · 支持图片理解",
        "model": "deepseek-chat",
        "vision": True,
    },
}

def get_client():
    api_key = (st.session_state.get("api_key_input", "") or
               os.environ.get("DEEPSEEK_KEY", ""))
    base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    if not api_key:
        return None
    return OpenAI(api_key=api_key, base_url=base)

def get_model_config():
    m = st.session_state.ai_model
    return MODELS.get(m, MODELS["fast"])

# ============================================================
#  对话管理
# ============================================================
def new_thread():
    tid = uuid.uuid4().hex[:12]
    st.session_state.ai_threads[tid] = {
        "title": "新对话",
        "messages": [],
        "created": time.strftime("%m/%d %H:%M"),
    }
    st.session_state.ai_thread_order.insert(0, tid)
    st.session_state.ai_current_thread = tid
    return tid

def current_thread():
    tid = st.session_state.ai_current_thread
    if not tid or tid not in st.session_state.ai_threads:
        tid = new_thread()
    return tid

def get_messages():
    tid = current_thread()
    return st.session_state.ai_threads[tid]["messages"]

def add_message(role, content):
    tid = current_thread()
    msgs = st.session_state.ai_threads[tid]["messages"]
    msgs.append({"role": role, "content": content})
    # 自动更新标题
    if role == "user" and len(msgs) <= 2:
        title = content[:30] + ("..." if len(content) > 30 else "")
        st.session_state.ai_threads[tid]["title"] = title

def delete_thread(tid):
    if tid in st.session_state.ai_threads:
        del st.session_state.ai_threads[tid]
    if tid in st.session_state.ai_thread_order:
        st.session_state.ai_thread_order.remove(tid)
    if st.session_state.ai_current_thread == tid:
        remaining = st.session_state.ai_thread_order
        st.session_state.ai_current_thread = remaining[0] if remaining else None

# ============================================================
#  评分配置上下文（仅在 config 模式下注入）
# ============================================================
def build_config_context():
    ctx = []
    rubric_path = "data/rubric.json"
    config_path = "config.yaml"

    if os.path.exists(rubric_path):
        try:
            with open(rubric_path, "r", encoding="utf-8") as f:
                rubric = json.load(f)
            # 精简
            r = copy.deepcopy(rubric)
            for q in r.get("questions", []):
                for c in q.get("criteria", []):
                    c.pop("desc", None)
                q.pop("submission_labels", None)
                q.pop("data_checks", None)
            ctx.append("## 当前评分标准 (rubric.json)")
            ctx.append("```json")
            ctx.append(json.dumps(r, ensure_ascii=False, indent=2))
            ctx.append("```")
        except:
            pass

    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            ctx.append("## 当前评分配置 (config.yaml)")
            ctx.append("```yaml")
            ctx.append(yaml.dump(cfg.get("grading", {}), allow_unicode=True))
            ctx.append("```")
        except:
            pass

    return "\n".join(ctx)

CONFIG_SYSTEM_PROMPT = """你是阅卷系统的 AI 评分配置助手。你可以帮教师修改评分标准。

## 规则
- 用中文回复
- 当用户要求修改时，在回复末尾输出变更块：

```action
{"type":"rubric"|"config"|"both","summary":"一句话","rubric":{...},"config":{...}}
```

- rubric 只包含要修改的题目（按 id 匹配），config 只包含要改的 grading 项
- 例：改 Q1 满分20 → {"type":"rubric","rubric":{"questions":[{"id":1,"max_score":20}]}}
- 不要编造不存在的 id 或档位名
- 若只需回答问题，不输出 action 块"""

# ============================================================
#  调用 LLM
# ============================================================
def call_llm(messages, stream=False):
    client = get_client()
    if not client:
        return "请先设置 API Key（环境变量 DEEPSEEK_KEY 或在 config.yaml 中配置）"

    mc = get_model_config()
    model = mc["model"]

    # 构建消息列表
    full_msgs = []

    # 评分配置模式：注入系统提示词
    if st.session_state.ai_mode == "config":
        ctx = build_config_context()
        sys_prompt = CONFIG_SYSTEM_PROMPT + "\n\n" + ctx
        full_msgs.append({"role": "system", "content": sys_prompt})

    # 历史消息（限制最近 20 条）
    full_msgs.extend(messages[-20:])

    try:
        kwargs = dict(
            model=model,
            messages=full_msgs,
            max_tokens=4096 if model == "deepseek-reasoner" else 2048,
            temperature=0.2 if st.session_state.ai_mode == "config" else 0.7,
            stream=stream,
        )
        response = client.chat.completions.create(**kwargs)

        if stream:
            return response  # 返回 stream 对象
        else:
            return response.choices[0].message.content
    except Exception as e:
        err = str(e)
        if "401" in err:
            return "API Key 无效或已过期"
        if "402" in err:
            return "API 余额不足"
        return f"调用失败: {err[:150]}"

# ============================================================
#  解析 + 应用变更
# ============================================================
def parse_action(text):
    pattern = r'```action\s*\n(.*?)\n\s*```'
    m = re.search(pattern, text, re.DOTALL)
    if not m:
        return text, None
    try:
        action = json.loads(m.group(1))
        return text[:m.start()] + text[m.end():], action
    except:
        return text, None

def apply_rubric_change(patch):
    rubric_path = "data/rubric.json"
    if not os.path.exists(rubric_path):
        return ["rubric.json 不存在"]
    with open(rubric_path, "r", encoding="utf-8") as f:
        rubric = json.load(f)
    changes = []
    if "questions" in patch:
        existing = {q["id"]: i for i, q in enumerate(rubric.get("questions", []))}
        for pq in patch["questions"]:
            qid = pq.get("id")
            if qid in existing:
                idx = existing[qid]
                for k, v in pq.items():
                    if k == "criteria" and isinstance(v, list):
                        cmap = {c["id"]: ci for ci, c in enumerate(rubric["questions"][idx].get("criteria", []))}
                        for pc in v:
                            cid = pc.get("id")
                            if cid in cmap:
                                rubric["questions"][idx]["criteria"][cmap[cid]].update(pc)
                            else:
                                rubric["questions"][idx]["criteria"].append(pc)
                    elif k != "id":
                        rubric["questions"][idx][k] = v
                changes.append(f"Q{qid} 已更新")
            else:
                rubric.setdefault("questions", []).append(pq)
                changes.append(f"新增 Q{qid}")
        rubric.setdefault("exam", {})["total_score"] = sum(
            q.get("max_score", 0) for q in rubric["questions"])
    if "exam" in patch:
        rubric.setdefault("exam", {}).update(patch["exam"])
        changes.append("考试信息已更新")
    with open(rubric_path, "w", encoding="utf-8") as f:
        json.dump(rubric, f, ensure_ascii=False, indent=2)
    if "rubric" in st.session_state:
        st.session_state.rubric = None
    return changes

def apply_config_change(patch):
    config_path = "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    changes = []
    if "grading" in patch:
        g = cfg.setdefault("grading", {})
        if "tiers" in patch["grading"]:
            g.setdefault("tiers", {}).update(patch["grading"]["tiers"])
            for tk in patch["grading"]["tiers"]:
                changes.append(f"档位「{tk}」已更新")
        if "mode" in patch["grading"]:
            g["mode"] = patch["grading"]["mode"]
            changes.append(f"模式切为「{patch['grading']['mode']}」")
        if "pass_line" in patch["grading"]:
            g["pass_line"] = patch["grading"]["pass_line"]
            changes.append(f"及格线 → {patch['grading']['pass_line']}")
    if "custom_presets" in patch:
        cfg.setdefault("custom_presets", {}).update(patch["custom_presets"])
        for pk in patch["custom_presets"]:
            if patch["custom_presets"][pk] is None:
                cfg["custom_presets"].pop(pk, None)
                changes.append(f"预设「{pk}」已删除")
            else:
                changes.append(f"预设「{pk}」已更新")
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    return changes

# ============================================================
#  布局：左侧主聊天区 + 右侧历史栏
# ============================================================
col_main, col_hist = st.columns([4, 1])

# ===== 右侧：历史对话 =====
with col_hist:
    st.caption("历史对话")
    if st.button("+ 新对话", use_container_width=True, key="new_chat"):
        new_thread()
        st.rerun()

    # 列表
    for tid in st.session_state.ai_thread_order:
        t = st.session_state.ai_threads.get(tid)
        if not t:
            continue
        is_active = tid == st.session_state.ai_current_thread
        title = t.get("title", "新对话")
        # 高亮当前对话
        btn_label = ("🔹 " if is_active else "  ") + title
        if st.button(btn_label, key=f"th_{tid}", use_container_width=True,
                     help=f"创建于 {t.get('created','')}"):
            st.session_state.ai_current_thread = tid
            st.rerun()
    # 删除
    if st.session_state.ai_thread_order:
        with st.expander("管理"):
            for tid in st.session_state.ai_thread_order[:]:
                if st.button(f"🗑 {st.session_state.ai_threads[tid]['title'][:20]}",
                             key=f"del_{tid}", use_container_width=True):
                    delete_thread(tid)
                    st.rerun()

# ===== 左侧：主界面 =====
with col_main:
    st.markdown("### 🤖 AI 助手")

    # 顶部控制栏
    ctl1, ctl2, ctl3 = st.columns([2, 2, 2])
    with ctl1:
        # 模型选择
        cur_model = st.session_state.ai_model
        model_opts = list(MODELS.keys())
        model_idx = model_opts.index(cur_model) if cur_model in model_opts else 0
        new_model = st.selectbox(
            "模型",
            model_opts,
            index=model_idx,
            format_func=lambda x: MODELS[x]["label"],
            key="model_select",
            label_visibility="collapsed",
        )
        if new_model != cur_model:
            st.session_state.ai_model = new_model
            st.rerun()
        mc = MODELS[st.session_state.ai_model]
        st.caption(mc["desc"])

    with ctl2:
        # 模式切换
        mode_opts = {"chat": "自由对话", "config": "评分配置"}
        cur_mode = st.session_state.ai_mode
        new_mode = st.radio(
            "模式",
            list(mode_opts.keys()),
            format_func=lambda x: mode_opts[x],
            horizontal=True,
            key="mode_radio",
            label_visibility="collapsed",
        )
        if new_mode != cur_mode:
            st.session_state.ai_mode = new_mode
            st.rerun()

    with ctl3:
        if st.button("🗑 清空当前对话", use_container_width=True):
            tid = current_thread()
            st.session_state.ai_threads[tid]["messages"] = []
            st.rerun()

    if st.session_state.ai_mode == "config":
        st.info("评分配置模式：可修改评分标准、档位比例、题目分值，改动预览后确认应用。")

    st.divider()

    # ===== 消息列表 =====
    msgs = get_messages()

    for i, msg in enumerate(msgs):
        with st.chat_message(msg["role"]):
            st.markdown(msg.get("display", msg["content"]))

            # 变更卡片
            action = msg.get("action")
            if action and not msg.get("action_done"):
                with st.container(border=True):
                    st.caption(f"📋 {action.get('summary','配置变更')}")
                    if action.get("rubric"):
                        with st.expander("rubric.json 变更"):
                            st.json(action["rubric"])
                    if action.get("config"):
                        with st.expander("config.yaml 变更"):
                            st.json(action["config"])
                    ca, cb = st.columns([1, 5])
                    with ca:
                        if st.button("✅ 应用", key=f"ap_{i}", type="primary"):
                            res = []
                            try:
                                if action.get("rubric"):
                                    res += apply_rubric_change(action["rubric"])
                                if action.get("config"):
                                    res += apply_config_change(action["config"])
                                st.session_state.ai_threads[current_thread()]["messages"][i]["action_done"] = True
                                st.session_state.ai_threads[current_thread()]["messages"][i]["action_result"] = res
                                st.rerun()
                            except Exception as e:
                                st.error(f"失败: {e}")
                    with cb:
                        if st.button("↩ 放弃", key=f"cx_{i}"):
                            st.session_state.ai_threads[current_thread()]["messages"][i]["action_done"] = True
                            st.rerun()
            if msg.get("action_result"):
                for r in msg["action_result"]:
                    st.success(f"✅ {r}")

    # ===== 输入区 =====
    prompt = st.chat_input("输入消息..." if st.session_state.ai_mode == "chat" else "描述你想要的评分调整...")
    if prompt:
        add_message("user", prompt)
        with st.spinner("思考中..."):
            raw_reply = call_llm(get_messages())
        clean, action = parse_action(raw_reply) if st.session_state.ai_mode == "config" else (raw_reply, None)
        tid = current_thread()
        st.session_state.ai_threads[tid]["messages"].append({
            "role": "assistant",
            "content": raw_reply,
            "display": clean,
            "action": action,
            "action_done": False,
            "action_result": None,
        })
        st.rerun()
