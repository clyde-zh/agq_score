import streamlit as st
import json
import re
from datetime import datetime
import base64
import random
import hashlib
import os
from typing import Any, Dict, List, Optional

# =========================
# 全局配置
# =========================
MODEL_LABELS = ["模型 A", "模型 B", "模型 C"]  # 盲评展示标签
PANEL_HEIGHT = 720

PROB_STEP = 0.05
PROB_TOL = 1e-6
PROB_ROUND = 2

DATA_FILE_TEMPLATE = "data_{teacher_id}.jsonl"
USER_QUESTION_FIELD = "user_designed_question"  # ✅ 恢复用户自拟题目字段

# =========================
# SCHEMA（与你现在一致）
# =========================
SCHEMA = {
    "groups": [
        {
            "name": "知识点匹配度",
            "desc": "主要衡量模型生成题目是否能够准确识别并体现用户输入的知识点，确保所生成的题目符合用户指定的知识点。",
            "need_comment": True,
            "subdims": [
                {"name": "知识点满足度", "desc": "评估题目是否将用户指定的知识点集合（kp_req）作为核心考查内容。",
                 "options": [0, 1, 2],
                 "rubric": {0: "题目内容完全不包含 kp_req 中的概念、定义或公式。或仅作为装饰词，与解题无关。",
                            1: "题目涉及了 kp_req ，但仅作为题目的部分信息，移除后不影响解题",
                            2: "题目主要考查 kp_req ，是解题的关键路径或核心瓶颈。"}},
                {"name": "核心知识点对齐度",
                 "desc": "题目核心知识点预测集合（kp_pred）与用户指定集合（kp_req）的语义/层级相关程度。",
                 "options": [0, 1, 2],
                 "rubric": {0: "kp_pred 与 kp_req 属于不同类型的知识点。",
                            1: "kp_pred 与 kp_req 有一定关联或部分对齐。",
                            2: "kp_pred 与 kp_req 相对应程度较高，对齐良好。"}},
                {"name": "学段契合度", "desc": "题目所涉及的知识点是否都符合用户指定的学段范围。",
                 "options": [0, 2],
                 "rubric": {0: "明显超纲/学段不匹配", 2: "学段完全匹配"}},
            ],
        },
        {
            "name": "题型匹配度",
            "desc": "主要考察题目类型是否与用户选择的题型一致，且符合题型格式规范与标准要求。",
            "need_comment": True,
            "subdims": [
                {"name": "题型与结构规范", "desc": "题目类型是否与用户要求一致，且题干、设问等信息是否齐全",
                 "options": [0, 1, 2],
                 "rubric": {0: "题目类型与用户要求完全不符，或格式严重错误，关键信息缺失/混乱，无法构成完整题目",
                            1: "题型部分相符或格式基本完整但存在明显不规范之处（如选项数量/编号错误、填空无明显空等）",
                            2: "题型与用户要求完全一致，格式规范，结构完整，题干/设问等要素齐全"}},
                {"name": "数量匹配度", "desc": "生成题目数量是否与用户要求一致（如要求1题/多题）",
                 "options": [0, 2],
                 "rubric": {0: "数量不匹配", 2: "数量完全匹配"}},
            ],
        },
        {
            "name": "题目准确性",
            "desc": "主要考察题目表达是否清晰、指向明确、术语规范，确保学生能理解题意且题目可正常作答。",
            "need_comment": True,
            "subdims": [
                {"name": "表述严谨性", "desc": "题目用词、语法是否规范，没有语病、错别字，语句通顺流畅。",
                 "options": [0, 1, 2],
                 "rubric": {0: "表达混乱/大量错误/歧义严重。",
                            1: "语言基本流畅，但存在少量错别字、语病或表述不清晰之处，轻微影响题意理解。",
                            2: "表述严谨清晰、符号术语规范，题意清晰明确。"}},
                {"name": "信息充分性",
                 "desc": "题干提供的已知条件与约束是否足以在目标学段的常规知识范围内建立可解的求解闭环。",
                 "options": [0, 1, 2],
                 "rubric": {0: "关键条件/变量定义/约束缺失，导致无法正常解题。",
                            1: "基本可建立求解思路，但存在必要条件表达不清或约束不完整，存在较为明显歧义。",
                            2: "题干信息与约束充分且自洽，关键对象与变量定义清晰，条件链条闭合，能完成正确解题。"}},
                {"name": "答案确定性", "desc": "评估在信息完备的前提下，题目是否存在客观、唯一的正确答案。",
                 "options": [0, 1, 2],
                 "rubric": {0: "题目存在逻辑矛盾导致无解；或者解空间过于发散，存在多个互相冲突但均合理的答案。",
                            1: "题目存在预期的最优解，但区分度不够显著。",
                            2: "题目逻辑收敛，具有唯一确定的标准答案或有限的正确答案集合。"}},
            ],
        },
        {
            "name": "解析准确性",
            "desc": "主要考察解析的正确性、严谨性与详细程度，且解析内容与目标学段相适配。",
            "need_comment": True,
            "subdims": [
                {"name": "解析质量", "desc": "解析是否清晰、流畅、思路严谨，充分展示分析过程和思考路径",
                 "options": [0, 1, 2],
                 "rubric": {0: "解析混乱/关键步骤缺失/明显错误；或在解析中存在对题目答案的修正描述。",
                            1: "基本正确但较简略或有跳步/不够严谨",
                            2: "思路清晰、推导严谨、步骤完整"}},
                {"name": "独立求解一致性",
                 "desc": "验证“仅基于题目独立求解得到的答案”与“出题模型给出的参考答案”是否一致/等价。",
                 "options": [0, 2],
                 "rubric": {0: "两者不一致，且无法合理解释为等价答案。",
                            2: "两者一致或可证明等价（含单位换算/表达式等价/数值容差内一致/选项一致）。"}},
                {"name": "学段适配性", "desc": "解析过程所用的词语和方式是否符合该学段学生的认知",
                 "options": [0, 1, 2],
                 "rubric": {0: "知识、方法或语言风格完全不符合指定学段认知水平。或存在对题目或答案修正的描述。",
                            1: "方法基本符合但表达过于专业/晦涩，不利于理解。",
                            2: "知识、方法和表述贴合学段认知，易于理解学习。"}},
            ],
        },
        {
            "name": "素养导向性",
            "desc": "主要考察生成题目是否设置具体情景（文化生活/学科应用等）并服务于解题，体现素养导向。",
            "need_comment": True,
            "subdims": [
                {"name": "情景真实性与关联性", "desc": "情景是否与生活实际、社会热点和科学发展前沿相关",
                 "options": [0, 1, 2],
                 "rubric": {0: "无情景或情景与解题无关",
                            1: "与现实有一定关联但牵强/模式化，缺乏新意",
                            2: "情景真实可信，与现实/热点/前沿紧密联系，能激发兴趣"}},
                {"name": "学科融合与应用", "desc": "是否体现应用/跨情境（可选跨学科），且不偏离用户指定学科与考点",
                 "options": [0, 1, 2],
                 "rubric": {0: "题目仅考察单一学科的孤立知识点。",
                            1: "题目尝试进行学科融合，但融合方式较为生硬。",
                            2: "应用/融合自然，且聚焦目标学科与知识点"}},
                {"name": "高阶素养培养", "desc": "是否引导学生质疑、反思、评价；是否要求通过分析、建模、推理等方式解决问题",
                 "options": [0, 1, 2],
                 "rubric": {0: "仅考察简单记忆/复述，几乎不体现高阶能力",
                            1: "有一定分析或应用，但深度一般",
                            2: "高阶素养导向明确，促进分析、建模、推理、评价等高阶思维"}},
            ],
        },
        {
            "name": "约束满足",
            "desc": "主要考察模型输出是否满足用户指令与系统要求的约束（如题型格式、选项数量、必须包含答案/解析等）。",
            "need_comment": True,
            "subdims": [
                {"name": "约束满足度", "desc": "输出是否整体满足约束要求（格式/要素/限制条件等）",
                 "options": [0, 1, 2],
                 "rubric": {0: "多项关键约束未满足（结构/要素缺失或明显违背要求）",
                            1: "大部分约束满足，但存在1~2处不符合或遗漏",
                            2: "约束满足完整，无明显违背或遗漏"}},
            ],
        },
    ],
    "rank": {
        "name": "模型回答质量排名",
        "desc": "第1名/第2名/第3名（每个模型各自选择一个名次）",
        "options": ["未评分", "1", "2", "3"],
    },
}


# =========================
# 通用工具
# =========================
def safe_key(s: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "_", str(s))


def format_inline_value(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        return "、".join([str(x) for x in v])
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


def write_jsonl_atomic(path: str, items: List[Dict[str, Any]]):
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name,exist_ok=True)

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def build_grid(minv: float, maxv: float, step: float):
    n = int(round((maxv - minv) / step))
    return [round(minv + i * step, PROB_ROUND) for i in range(n + 1)]


def render_latex_textblock(text: str):
    if not text:
        st.markdown("")
        return
    t = (text or "").replace("\r\n", "\n")
    t = t.replace(r"\[", "$$").replace(r"\]", "$$")
    t = t.replace(r"\(", "$").replace(r"\)", "$")

    pattern = re.compile(r"(\$\$.*?\$\$|\$.*?\$)", re.DOTALL)
    parts = pattern.split(t)

    out = []
    for part in parts:
        if not part:
            continue
        if pattern.fullmatch(part):
            out.append(part)
        else:
            out.append(part.replace("\n", "  \n"))
    st.markdown("".join(out), unsafe_allow_html=False)


def strip_section_tags(s: str) -> str:
    if not s:
        return ""
    t = s.strip()
    t = re.sub(r"</\s*(题目|解析|答案)\s*>", "", t)
    t = re.sub(r"<\s*(题目|解析|答案)\s*>", "", t)
    t = re.sub(r"[【\[]\s*(题目|解析|答案)\s*[】\]]", "", t)
    t = re.sub(r"^\s*(题目|解析|答案)\s*[:：]\s*", "", t)
    return t.strip()


def split_qa(text: str):
    t = (text or "").replace("\r\n", "\n")
    markers = [
        ("题目", [r"<题目>", r"【题目】", r"题目[:：]"]),
        ("解析", [r"<解析>", r"【解析】", r"解析[:：]"]),
        ("答案", [r"<答案>", r"【答案】", r"答案[:：]"]),
    ]
    hits = []
    for name, pats in markers:
        for p in pats:
            m = re.search(p, t)
            if m:
                hits.append((m.start(), m.end(), name))
                break
    hits.sort(key=lambda x: x[0])

    if not hits:
        return {"题目": strip_section_tags(t), "解析": "", "答案": ""}

    out = {"题目": "", "解析": "", "答案": ""}
    for idx, (s, e, name) in enumerate(hits):
        content_start = e
        content_end = hits[idx + 1][0] if idx + 1 < len(hits) else len(t)
        out[name] = strip_section_tags(t[content_start:content_end])
    return out


# =========================
# 概率/期望分工具（保持逻辑不变）
# =========================
def normalize_prob_dict(prob_dict, opts):
    keys = [str(o) for o in opts]
    vals = []
    for k in keys:
        try:
            vals.append(float(prob_dict.get(k, 0.0)))
        except Exception:
            vals.append(0.0)

    s = sum(vals)
    if s <= PROB_TOL:
        vals = [1.0 / len(keys)] * len(keys)
    else:
        vals = [v / s for v in vals]

    out = {k: round(v, PROB_ROUND) for k, v in zip(keys, vals)}
    total = sum(out.values())
    diff = round(1.0 - total, PROB_ROUND)
    out[keys[-1]] = round(out[keys[-1]] + diff, PROB_ROUND)

    for k in keys:
        out[k] = min(1.0, max(0.0, out[k]))
    return out


def mean_to_probs(opts, mean_value: float):
    opts = sorted(opts)
    e = float(mean_value)

    if len(opts) == 2:
        a, b = opts[0], opts[1]
        if abs(b - a) < 1e-9:
            probs = {str(a): 1.0, str(b): 0.0}
        else:
            pb = (e - a) / (b - a)
            pb = max(0.0, min(1.0, pb))
            pa = 1.0 - pb
            probs = {str(a): pa, str(b): pb}
        return normalize_prob_dict(probs, opts)

    # 默认 0/1/2
    if e <= 1.0:
        p0 = 1.0 - e
        p1 = e
        p2 = 0.0
    else:
        p0 = 0.0
        p1 = 2.0 - e
        p2 = e - 1.0

    return normalize_prob_dict({"0": p0, "1": p1, "2": p2}, [0, 1, 2])


def expected_from_probs(probs: dict, opts):
    if not isinstance(probs, dict):
        return None
    s = 0.0
    for o in sorted(opts):
        s += float(o) * float(probs.get(str(o), 0.0))
    return float(s)


def expected_from_prev(prev, opts):
    if isinstance(prev, dict):
        v = expected_from_probs(prev, opts)
        return float(v) if v is not None else float(min(opts))
    if prev is None or prev == "":
        return float(min(opts))
    try:
        v = float(prev)
        return float(max(min(v, max(opts)), min(opts)))
    except Exception:
        return float(min(opts))


# =========================
# responses / annotations 操作
# =========================
def responses_index(message: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for r in (message.get("responses") or []):
        rid = r.get("response_id")
        if rid:
            out[rid] = r
    return out


def ensure_teacher_annotation(message: Dict[str, Any], teacher_id: str) -> Dict[str, Any]:
    ann = message.setdefault("annotations", {})
    t_ann = ann.setdefault(teacher_id, {})
    t_ann.setdefault("blind_map", {})
    t_ann.setdefault("scores", {})
    return t_ann


def get_teacher_annotation_readonly(message: Dict[str, Any], teacher_id: str) -> Dict[str, Any]:
    ann = message.get("annotations")
    if not isinstance(ann, dict):
        return {}
    t_ann = ann.get(teacher_id)
    return t_ann if isinstance(t_ann, dict) else {}


def deterministic_pick_three(response_ids: List[str], seed_text: str) -> List[Optional[str]]:
    ids = list(response_ids)
    seed = int(hashlib.md5(seed_text.encode("utf-8")).hexdigest()[:8], 16)
    rnd = random.Random(seed)
    rnd.shuffle(ids)
    ids = ids[:3]
    while len(ids) < 3:
        ids.append(None)
    return ids


def get_blind_order_for_qid(
        message: Dict[str, Any],
        qid: str,
        teacher_id: Optional[str] = None,
        persist: bool = True,
) -> List[Optional[str]]:
    if teacher_id is None:
        teacher_id = st.session_state.teacher_id

    rindex = responses_index(message)
    rid_set = set(rindex.keys())
    rid_list = list(rindex.keys())
    seed_text = f"{teacher_id}::{qid}::blind"

    if persist:
        t_ann = ensure_teacher_annotation(message, teacher_id)
    else:
        t_ann = get_teacher_annotation_readonly(message, teacher_id)

    blind_map = t_ann.get("blind_map") if isinstance(t_ann, dict) else {}
    if isinstance(blind_map, dict) and all(lbl in blind_map for lbl in MODEL_LABELS):
        saved = [blind_map.get("模型 A"), blind_map.get("模型 B"), blind_map.get("模型 C")]
        if all((rid is None) or (rid in rid_set) for rid in saved):
            return saved

    picked = deterministic_pick_three(rid_list, seed_text=seed_text)
    if persist:
        t_ann["blind_map"] = {
            "模型 A": picked[0],
            "模型 B": picked[1],
            "模型 C": picked[2],
        }
    return picked


# =========================
# 完成判定（基于 response_id）
# =========================
def score_filled(v, opts):
    if v is None or v == "":
        return False
    if isinstance(v, dict):
        keys = [str(o) for o in opts]
        if not all(k in v for k in keys):
            return False
        try:
            vals = [float(v[k]) for k in keys]
        except Exception:
            return False
        if any((x < -PROB_TOL) or (x > 1 + PROB_TOL) for x in vals):
            return False
        return abs(sum(vals) - 1.0) <= 0.03
    return v in opts


def is_question_scored(message: Dict[str, Any], teacher_id: str) -> bool:
    qid = message.get("q_id", "")
    t_ann = get_teacher_annotation_readonly(message, teacher_id)
    order = get_blind_order_for_qid(message, qid, teacher_id=teacher_id, persist=False)
    rindex = responses_index(message)
    required_rids = [rid for rid in order if rid and rid in rindex]

    rank_name = SCHEMA["rank"]["name"]
    rank_key = f"{rank_name}_score"

    scores = t_ann.get("scores") or {}
    ranks = []
    for rid in required_rids:

        ms = scores.get(rid, {})
        for group in SCHEMA["groups"]:
            gname = group["name"]
            for sub in group["subdims"]:
                sname = sub["name"]
                opts = sub.get("options", [0, 1, 2])
                k = f"{gname}_{sname}_score"
                if not score_filled(ms.get(k), opts):
                    return False

            if group.get("need_comment", False):
                ck = f"{gname}_comment"
                c = ms.get(ck)
                if c is None or str(c).strip() == "":
                    return False

        rank = ms.get(rank_key)
        if rank in [None, "", "未评分"]:
            return False
        ranks.append(rank)

    if len(ranks) != len(set(ranks)):
        return False

    return True


# =========================
# 渲染评分区（绑定 response_id）
# =========================
def render_scoring(message: Dict[str, Any]):
    teacher_id = st.session_state.teacher_id
    qid = message.get("q_id", "")

    t_ann = ensure_teacher_annotation(message, teacher_id)
    scores_root = t_ann.setdefault("scores", {})

    order = get_blind_order_for_qid(message, qid, teacher_id=teacher_id, persist=True)
    rindex = responses_index(message)

    rank_conf = SCHEMA["rank"]
    rank_name = rank_conf["name"]
    rank_opts = rank_conf["options"]
    rank_key = f"{rank_name}_score"

    for group in SCHEMA["groups"]:
        gname = group["name"]
        gdesc = group.get("desc", "")
        need_comment = group.get("need_comment", False)

        with st.expander(f"📌 {gname}", expanded=False):
            if gdesc:
                st.caption(f"**指标说明：** {gdesc}")

            for sub in group["subdims"]:
                sname = sub["name"]
                sdesc = sub.get("desc", "")
                opts = sub.get("options", [0, 1, 2])
                rubric = sub.get("rubric", {})

                st.markdown(f"**🔖 {sname}**")
                st.write(f"<span style='font-size: 0.9em;'>{sdesc}</span>", unsafe_allow_html=True)

                # ✅ 优化点 2：评分标准直接展示，不再隐藏在折叠弹窗中
                if rubric:
                    rubric_lines = [f"<div style='margin-bottom: 4px;'><b>{score}分</b>：{rubric[score]}</div>" for score
                                    in opts if score in rubric]
                    if rubric_lines:
                        st.markdown(
                            f"<div style='background-color: #f4f6f9; padding: 10px 15px; border-radius: 6px; font-size: 0.85em; color: #2c3e50; margin-bottom: 15px; border-left: 4px solid #1f77b4;'>"
                            f"{''.join(rubric_lines)}"
                            f"</div>",
                            unsafe_allow_html=True
                        )

                cols = st.columns(3)
                for i in range(3):
                    rid = order[i]
                    label = MODEL_LABELS[i]

                    with cols[i]:
                        st.markdown(f"**🤖 {label}**")

                        if not rid or rid not in rindex:
                            st.info("无模型输出 (免评)")
                            continue

                        scores_root.setdefault(rid, {})
                        sub_key = f"{gname}_{sname}_score"
                        prev = scores_root[rid].get(sub_key, "")

                        wkey = f"{qid}_{safe_key(gname)}_{safe_key(sname)}_{rid}"
                        mean_key = f"{wkey}_mean"

                        default_mean = expected_from_prev(prev, opts)
                        grid = build_grid(float(min(opts)), float(max(opts)), float(PROB_STEP))
                        default_mean = min(grid, key=lambda x: abs(x - float(default_mean)))
                        default_idx = grid.index(default_mean)

                        mean_val = st.selectbox(
                            "总分 E[S]",
                            options=grid,
                            index=default_idx,
                            key=mean_key,
                            format_func=lambda x: f"{x:.2f}",
                            label_visibility="collapsed"
                        )

                        probs = mean_to_probs(opts, mean_val)
                        scores_root[rid][sub_key] = probs

                        # ✅ 优化点 1：加粗加黑/主题色突出总分显示
                        if sorted(opts) == [0, 2]:
                            prob_str = f"P(0): {probs['0']:.2f} &nbsp;|&nbsp; P(2): {probs['2']:.2f}"
                        else:
                            prob_str = f"P(0): {probs['0']:.2f} &nbsp;|&nbsp; P(1): {probs['1']:.2f} &nbsp;|&nbsp; P(2): {probs['2']:.2f}"

                        st.markdown(
                            f"<div style='font-size: 0.85em; color: #555; margin-top: 2px;'>{prob_str}</div>"
                            f"<div style='font-size: 1.15em; font-weight: 700; color: #1f77b4; margin-top: 4px; margin-bottom: 10px;'>👉 总分: {mean_val:.2f}</div>",
                            unsafe_allow_html=True
                        )

                st.divider()

            # 一级维度_score（平均期望分）
            for rid in order:
                if not rid or rid not in rindex:
                    continue
                scores_root.setdefault(rid, {})
                sub_means = []
                for sub in group["subdims"]:
                    sname = sub["name"]
                    opts = sub.get("options", [0, 1, 2])
                    sub_key = f"{gname}_{sname}_score"
                    probs = scores_root[rid].get(sub_key)
                    ev = expected_from_probs(probs, opts) if isinstance(probs, dict) else None
                    if ev is not None:
                        sub_means.append(ev)
                if sub_means:
                    scores_root[rid][f"{gname}_score"] = round(sum(sub_means) / len(sub_means), 2)

            # 整体评语
            if need_comment:
                st.markdown("💬 **维度整体评语（必填）**")
                cols_c = st.columns(3)
                for i in range(3):
                    rid = order[i]
                    label = MODEL_LABELS[i]
                    with cols_c[i]:
                        if not rid or rid not in rindex:
                            continue
                        scores_root.setdefault(rid, {})
                        ck = f"{gname}_comment"
                        prev_c = scores_root[rid].get(ck, "")
                        wkey_c = f"{qid}_{safe_key(gname)}_comment_{rid}"
                        c = st.text_area(f"{label} 评语", value=prev_c, key=wkey_c, height=68,
                                         label_visibility="collapsed", placeholder=f"输入 {label} 的评语...")
                        scores_root[rid][ck] = c

    # 排名
    with st.expander(f"🏆 {rank_name}", expanded=True):
        st.caption(f"**指标说明：** {rank_conf.get('desc', '')}")
        cols = st.columns(3)
        chosen_ranks = []
        for i in range(3):
            rid = order[i]
            label = MODEL_LABELS[i]
            with cols[i]:
                st.markdown(f"**🤖 {label}**")
                if not rid:
                    st.info("无输出 (免评)")
                    continue

                scores_root.setdefault(rid, {})
                prev_rank = scores_root[rid].get(rank_key, "未评分")
                try:
                    idx = rank_opts.index(prev_rank) if prev_rank != "" else 0
                except ValueError:
                    idx = 0

                wkey = f"{qid}_{safe_key(rank_name)}_{rid}"
                val = st.selectbox("名次", rank_opts, index=idx, key=wkey, label_visibility="collapsed")
                scores_root[rid][rank_key] = val
                if rid in rindex and val not in [None, "", "未评分"]:
                    chosen_ranks.append(val)

        if len(chosen_ranks) != len(set(chosen_ranks)):
            st.error("⚠️ 当前名次存在重复，请为不同模型选择不同名次。")


# =========================
# 内容展示区（按 response_id）
# =========================
def render_outputs(message: Dict[str, Any]):
    qid = message.get("q_id", "")
    teacher_id = st.session_state.teacher_id
    order = get_blind_order_for_qid(message, qid, teacher_id=teacher_id, persist=True)
    rindex = responses_index(message)

    expand_all = st.checkbox("🔽 展开全部（题目/解析/答案）", value=False, key=f"expandall_{safe_key(qid)}")

    c1, c2, c3 = st.columns(3)
    cols = [c1, c2, c3]
    for i, rid in enumerate(order):
        with cols[i]:
            st.markdown(f"###### 🤖 {MODEL_LABELS[i]}")
            if not rid or rid not in rindex:
                st.warning("⚠️ 该列没有模型输出。")
                continue

            text = rindex[rid].get("text", "")
            sections = split_qa(text)

            with st.expander("📝 题目", expanded=True):
                if sections["题目"].strip():
                    render_latex_textblock(sections["题目"])
                else:
                    st.info("未检测到题目段")

            with st.expander("🧠 解析", expanded=expand_all):
                if sections["解析"].strip():
                    render_latex_textblock(sections["解析"])
                else:
                    st.info("未检测到解析段")

            with st.expander("✅ 答案", expanded=expand_all):
                if sections["答案"].strip():
                    render_latex_textblock(sections["答案"])
                else:
                    st.info("未检测到答案段")


# =========================
# 页面展示（左输出 / 右评分）
# =========================
def display(message: Dict[str, Any]):
    user_req = message.get("user_req", {}) or {}

    # 美化用户需求区块
    with st.container(border=True):
        st.markdown("##### 👩‍🏫 用户原始需求")
        st.info(f"**提问内容：**\n\n{user_req.get('query', '（空）')}")

        qtype = format_inline_value(user_req.get("type", ""))
        knowledge = format_inline_value(user_req.get("knowledge", ""))
        constraint = format_inline_value(user_req.get("constraint", ""))

        c1, c2, c3 = st.columns(3)
        c1.markdown(f"**🎯 题型：** `{qtype if qtype else '-'}`")
        c2.markdown(f"**📚 知识点：** `{knowledge if knowledge else '-'}`")
        c3.markdown(f"**⚠️ 约束内容：** `{constraint if constraint else '-'}`")

    st.write("")  # 留白
    col_left, col_right = st.columns([1.1, 1], gap="large")

    with col_left:
        st.markdown("##### 📊 模型输出区域")
        with st.container(height=PANEL_HEIGHT, border=True):
            render_outputs(message)

    with col_right:
        st.markdown("##### ⭐ 评分区域")
        with st.container(height=PANEL_HEIGHT, border=True):
            render_scoring(message)


# =========================
# 同步“用户自拟题目”到 data
# =========================
def _sync_user_designed_question_to_data(data: List[Dict[str, Any]]):
    for i, item in enumerate(data):
        qid = item.get("q_id", f"id_{i}")
        wkey_ud = f"{qid}_{USER_QUESTION_FIELD}"
        if wkey_ud in st.session_state:
            item[USER_QUESTION_FIELD] = st.session_state.get(wkey_ud, "")


# =========================
# 主程序
# =========================
def main():
    if "teacher_id" not in st.session_state:
        st.title("🎯 题目质量评测系统")
        st.markdown("👋 欢迎！请输入您的身份编号以开始评测（例如 `T001`）：")
        teacher_input = st.text_input("身份编号", "")
        if st.button("开始评测", type="primary") and teacher_input.strip():
            st.session_state.teacher_id = teacher_input.strip().upper()
            st.rerun()
        return

    teacher_id = st.session_state.teacher_id
    file_path = DATA_FILE_TEMPLATE.format(teacher_id=teacher_id)

    if "page" not in st.session_state:
        st.session_state.page = 0

    # 加载数据
    try:
        data = read_jsonl(file_path)
    except FileNotFoundError:
        st.error(f"❌ 未找到编号 `{teacher_id}` 对应的数据文件：`{file_path}`。请联系管理员或先转换生成。")
        if st.button("重新输入编号"):
            del st.session_state.teacher_id
            st.rerun()
        return
    except Exception as e:
        st.error(f"❌ 读取 JSONL 失败：{str(e)}")
        return

    # 完成率
    total = len(data)
    done = sum(1 for item in data if is_question_scored(item, teacher_id))
    rate = (done / total) * 100 if total else 0

    st.sidebar.markdown("## 📊 评测进度")
    st.sidebar.progress(rate / 100 if rate <= 100 else 1.0)
    col_s1, col_s2 = st.sidebar.columns(2)
    col_s1.metric("已完成", done)
    col_s2.metric("总题目", total)

    if total == 0:
        st.warning(f"⚠️ 数据文件为空：`{file_path}`")
        if st.button("重新输入编号"):
            del st.session_state.teacher_id
            st.rerun()
        return

    def save_all():
        _sync_user_designed_question_to_data(data)
        write_jsonl_atomic(file_path, data)

    # 快速跳转
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🧭 快速跳转")
    qid_to_index = {item.get("q_id", f"id_{i}"): i for i, item in enumerate(data)}
    selected_qid = st.sidebar.selectbox("选择题目 ID 跳转", options=list(qid_to_index.keys()),
                                        label_visibility="collapsed")

    if st.sidebar.button("🚀 跳转到该题目", use_container_width=True):
        try:
            save_all()
        except Exception as e:
            st.sidebar.error(f"❌ 保存失败：{str(e)}")
            st.stop()
        st.session_state.page = qid_to_index[selected_qid]
        st.rerun()

    # 当前页逻辑
    total_pages = len(data)
    idx = max(0, min(st.session_state.page, total_pages - 1))
    st.session_state.page = idx

    current = data[idx]
    qid = current.get("q_id", f"id_{idx}")

    # 顶部统一 Title
    st.title("🎯 题目质量评估工作台")
    st.markdown(
        f"**身份编号：** `{teacher_id}` &nbsp; | &nbsp; **当前进度：** 第 `{idx + 1}` / `{total_pages}` 条 &nbsp; | &nbsp; **题目 ID：** `{qid}`")
    st.divider()

    display(current)

    if not is_question_scored(current, teacher_id):
        st.warning("⚠️ **温馨提示：** 当前题目有评分项或评语未填写，请完善后进行下一条。")
    else:
        st.success("✅ 当前题目评分已完善！")

    st.markdown("---")

    # 附加信息与底部操作栏使用两列布局
    col_bot_left, col_bot_right = st.columns([3, 2], gap="large")

    with col_bot_left:
        st.markdown("#### 💡 附加信息录入")
        prev_ud = current.get(USER_QUESTION_FIELD, "")
        wkey_ud = f"{qid}_{USER_QUESTION_FIELD}"
        user_text = st.text_area(
            "用户自拟题目（可选）",
            value=prev_ud,
            key=wkey_ud,
            height=135,
            placeholder="✍️ 若用户能自行设计更优题目，请在此录入；也可留空。",
            label_visibility="collapsed"
        )
        current[USER_QUESTION_FIELD] = user_text

    with col_bot_right:
        st.markdown("#### ⚙️ 操作区")
        st.write("")  # 占位对齐
        # 翻页 + 保存
        col1, col2, col3 = st.columns([1, 1.2, 1])

        with col1:
            if idx > 0:
                ok = is_question_scored(current, teacher_id)
                if st.button("⬅️ 上一条", disabled=not ok, use_container_width=True):
                    try:
                        save_all()
                    except Exception as e:
                        st.error(f"❌ 保存失败：{str(e)}")
                        st.stop()
                    st.session_state.page -= 1
                    st.rerun()

        with col2:
            if st.button("💾 保存当前进度", type="primary", use_container_width=True):
                try:
                    save_all()
                    # 加上时间戳，每次点击都会更新，完美解决多次点击无反馈的问题
                    current_time = datetime.now().strftime("%H:%M:%S")
                    st.success(f"✅ 保存成功！({current_time})")
                except Exception as e:
                    st.error(f"❌ 保存失败：{str(e)}")

        with col3:
            if idx < total_pages - 1:
                ok = is_question_scored(current, teacher_id)
                if st.button("下一条 ➡️", disabled=not ok, use_container_width=True):
                    try:
                        save_all()
                    except Exception as e:
                        st.error(f"❌ 保存失败：{str(e)}")
                        st.stop()
                    st.session_state.page += 1
                    st.rerun()

        st.write("")
        if st.button("📥 导出全部评分结果 (JSONL)", use_container_width=True):
            try:
                _sync_user_designed_question_to_data(data)
                jsonl_str = "\n".join(json.dumps(it, ensure_ascii=False) for it in data)
                b64 = base64.b64encode(jsonl_str.encode("utf-8")).decode()
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"出题评分结果_{teacher_id}_{timestamp}.jsonl"
                href = f'<a href="data:application/json;base64,{b64}" download="{filename}" style="text-decoration:none;">' \
                       f'<div style="text-align:center; padding:8px; background-color:#f0f2f6; border-radius:4px; color:#31333F;">' \
                       f'👉 点击下载 {filename}</div></a>'
                st.markdown(href, unsafe_allow_html=True)
            except Exception as e:
                st.error(f"❌ 导出失败：{str(e)}")


if __name__ == "__main__":
    st.set_page_config(page_title="题目评测系统", page_icon="🎯", layout="wide")
    st.markdown(
        """
        <style>
            .block-container { 
                padding-top: 2rem !important; 
                padding-bottom: 2rem !important; 
                padding-left: 3rem; 
                padding-right: 3rem; 
            }
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
        </style>
        """,
        unsafe_allow_html=True,
    )
    main()