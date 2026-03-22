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
MODEL_LABELS = ["模型 A", "模型 B", "模型 C"]
PANEL_HEIGHT = 720

PROB_STEP = 0.05
PROB_TOL = 1e-6
PROB_ROUND = 2

DATA_FILE_TEMPLATE = "data_{teacher_id}.jsonl"
USER_QUESTION_FIELD = "user_designed_question"

# 三阶段控制
STAGE1_GROUP = "题型匹配度"
STAGE2_GROUP = "题目准确性"
STAGE3_GROUPS = ["知识点匹配度", "解析准确性", "素养导向性"]

# 第一阶段失败后，后续全部记 -1
LATE_GROUPS_AFTER_STAGE1_FAIL = [
    "题目准确性",
    "知识点匹配度",
    "解析准确性",
    "素养导向性",
    "约束满足",
]

# 第二阶段失败后，第三阶段维度记 -1（约束满足保留）
LATE_GROUPS_AFTER_STAGE2_FAIL = [
    "知识点匹配度",
    "解析准确性",
    "素养导向性",
]


# =========================
# SCHEMA（顺序已调整）
# =========================
SCHEMA = {
    "groups": [
        {
            "name": "题型匹配度",
            "desc": "第一阶段：主要考察题目类型是否与用户选择的题型一致，且符合题型格式规范与标准要求。若该维度总分为 0，则后续维度自动记为 -1。",
            "need_comment": True,
            "subdims": [
                {
                    "name": "题型与结构规范",
                    "desc": "题目类型是否与用户要求一致，且题干、设问等信息是否齐全。",
                    "options": [0, 1, 2],
                    "rubric": {
                        0: "题目类型与用户要求完全不符（例如，要求选择题，生成了填空题），或格式严重错误，题干、选项、设问等关键信息缺失或混乱，无法构成一道完整的题目。",
                        1: "题目类型与用户要求部分相符（例如，要求单项选择题，生成了多选题），或格式基本完整，但存在明显不规范之处（例如，选择题选项编号错误，非特殊要求下选项非4个；填空题缺少标识；进度条）。",
                        2: "题目类型与用户要求完全一致，且格式完全规范，题干、设问等元素齐全，排版合理，结构完整。",
                    },
                },
                {
                    "name": "数量匹配度",
                    "desc": "题目数量是否与用户要求的一致。",
                    "options": [0, 2],
                    "rubric": {
                        0: "题目数量和用户要求的不一致。",
                        2: "题目数量和用户要求的完全一致。",
                    },
                },
            ],
        },
        {
            "name": "题目准确性",
            "desc": "第二阶段：主要考察题目表达是否清晰、指向明确、术语规范，确保学生能理解题意且题目可正常作答。若该维度总分为 0，则后续第三阶段维度自动记为 -1。",
            "need_comment": True,
            "subdims": [
                {
                    "name": "表述严谨性",
                    "desc": "题目用词、语法是否规范，没有语病、错别字，语句通顺流畅。",
                    "options": [0, 1, 2],
                    "rubric": {
                        0: "语言表达存在严重问题，如大量错别字、严重语病或逻辑混乱，导致题意无法理解。",
                        1: "语言基本流畅，但存在少量错别字、语病或表述不清晰之处，造成歧义，轻微影响题意理解。",
                        2: "语言流畅、准确、规范，无错别字和语病，题意清晰明确。",
                    },
                },
                {
                    "name": "信息充分性",
                    "desc": "题干提供的已知条件与约束是否足以在目标学段的常规知识范围内建立可解的求解闭环，推导出所需量（允许隐含条件与可推导的中间量；不要求所有中间量必须显式给出）。",
                    "options": [0, 1, 2],
                    "rubric": {
                        0: "关键条件/变量定义/约束缺失，导致在该学段的常规知识与题干信息下无法形成可执行的求解路径（需要额外外部信息或任意假设才能继续），或题意关键对象/量的含义不明，无法开展计算/推理。",
                        1: "基本可建立求解思路，但存在必要条件表达不清或约束不完整（例如单位/取值范围/边界条件/对象定义/前提关系模糊），导致求解过程需要补充“合理默认假设”或存在明显歧义；在补充常见约定后通常可继续解题。",
                        2: "题干信息与约束充分且自洽，关键对象与变量定义清晰，条件链条闭合；仅依赖题干信息与目标学段常规知识即可推导出解题所需量（中间量可由已知推导获得），不存在阻断推理的核心遗漏。",
                    },
                },
                {
                    "name": "答案确定性",
                    "desc": "基于上述信息充分性，判断是否有确定的答案。",
                    "options": [0, 1, 2],
                    "rubric": {
                        0: "题目存在逻辑矛盾导致无解；或者解空间过于发散，存在多个互相冲突但均合理的答案（如单选题有多个正确选项、填空题限制条件不足导致答案不唯一）。",
                        1: "题目存在预期的最优解，但区分度不够显著。",
                        2: "题目逻辑收敛，具有唯一确定的标准答案或有限的正确答案集合。",
                    },
                },
            ],
        },
        {
            "name": "知识点匹配度",
            "desc": "第三阶段：主要衡量模型生成题目是否能够准确识别并体现用户输入的知识点，确保所生成的题目符合用户指定的知识点。",
            "need_comment": True,
            "subdims": [
                {
                    "name": "知识点满足度",
                    "desc": "评估题目是否将用户指定的知识点集合（kp_req）作为核心考查内容。",
                    "options": [0, 1, 2],
                    "rubric": {
                        0: "题目内容完全不包含 kp_req 中的概念、定义或公式。或 kp_req 仅作为无关紧要的装饰性词汇出现，与解题逻辑没有任何关联。",
                        1: "题目涉及了 kp_req ，但仅作为题目的部分信息、前置铺垫、辅助条件或解题过程中一个简单的中间步骤出现，移除后不影响核心考察意图。",
                        2: "题目主要考查 kp_req ，是解题的关键路径或核心瓶颈。题目指向该知识点，或者解题过程中主要依赖于该知识点。",
                    },
                },
                {
                    "name": "核心知识点对齐度",
                    "desc": "题目核心知识点预测集合（kp_pred）与用户指定集合（kp_req）的语义/层级相关程度。需要忽视 kp_req 在题干中的直接出现，独立评估题目的核心考点；若无法完全判断，可给出大致分数，并在评分理由中写出你认为的核心知识点是什么，数量尽量与最上方要求知识点数量一致，并按优先级排序。",
                    "options": [0, 1, 2],
                    "rubric": {
                        0: "kp_pred 与 kp_req 的知识体系位置明显不一致，属于不同方向的知识点；知识点路径明显不同。",
                        1: "kp_pred 与 kp_req 有一定关联或部分对齐，但存在明显偏差：可能只对齐到较泛的上位概念、或只覆盖了部分用户知识点、或题目核心更偏向相邻但不同的知识点；整体对齐不够充分。",
                        2: "kp_pred 与 kp_req 在体系中高度贴合：多数用户知识点都能在 kp_pred 中找到直接或紧邻的对应，且对应关系合理（同一路径/同一父亲节点知识点），对应相似度大于0.8；说明题目核心考点与用户指定知识点对齐良好。",
                    },
                },
                {
                    "name": "学段契合度",
                    "desc": "题目所涉及的知识点是否都符合用户指定的学段范围。",
                    "options": [0, 2],
                    "rubric": {
                        0: "超出用户学段所需掌握的知识范围。",
                        2: "符合用户学段所掌握的知识范围。",
                    },
                },
            ],
        },
        {
            "name": "解析准确性",
            "desc": "第三阶段：主要考察解析的正确性、严谨性与详细程度。",
            "need_comment": True,
            "subdims": [
                {
                    "name": "解析质量",
                    "desc": "解析内容是否表述清晰、流畅，解析思路严谨，充分展示分析过程和思考路径。",
                    "options": [0, 1, 2],
                    "rubric": {
                        0: "解析过程混乱，逻辑不清，步骤缺失；或解析过程中存在明显的计算错误、原理引用错误或逻辑推理错误。或存在对题目或答案修正的描述。",
                        1: "解析过程基本完整，但逻辑跳跃，关键步骤解释不足；或解析过程大体正确，但存在个别计算疏忽、笔误或不够严谨的推理。",
                        2: "解析过程步骤清晰，逻辑连贯，重点突出；且每一步计算、推理和原理引用都准确无误，逻辑严谨。",
                    },
                },
                {
                    "name": "独立求解一致性",
                    "desc": "验证“仅基于题目独立求解得到的答案”与“出题模型给出的参考答案”是否一致/等价。只比较最终答案，允许等价形式（分数/小数等价、单位换算、表达式等价、同一选项的等价表述）。",
                    "options": [0, 2],
                    "rubric": {
                        0: "两者不一致，且无法合理解释为等价答案。",
                        2: "两者一致或可证明等价（含单位换算/表达式等价/数值容差内一致/选项一致）。",
                    },
                },
            ],
        },
        {
            "name": "素养导向性",
            "desc": "第三阶段：主要考察生成题目是否设置具体情景（文化生活/学科应用等）并服务于解题，体现素养导向。",
            "need_comment": True,
            "subdims": [
                {
                    "name": "情景真实性与关联性",
                    "desc": "设计的情景是否与生活实际、社会热点和科学发展前沿相关，并且能够与知识点相联系。",
                    "options": [0, 1, 2],
                    "rubric": {
                        0: "题目没有情景设计，仅有抽象化知识点运用。",
                        1: "题目情景与现实有一定关联，但较为牵强或模式化，缺乏新意。",
                        2: "题目情景设计巧妙，与生活实际、社会热点或科学前沿紧密联系，真实可信，能激发学生兴趣。",
                    },
                },
                {
                    "name": "学科融合与应用",
                    "desc": "是否融合了两门以上的学科知识与方法，且主要考察内容与用户指定学科一致。",
                    "options": [0, 1, 2],
                    "rubric": {
                        0: "题目仅考察单一学科的孤立知识点，没有体现学科间的联系。考察核心不符合用户指定学科。",
                        1: "题目尝试进行学科融合，但融合方式较为生硬，或只是简单地将不同学科概念并列，没有体现深度应用。",
                        2: "题目自然地融合了多学科知识与方法来解决一个综合性问题，且考察的核心仍符合用户指定学科，体现了知识的综合应用能力。",
                    },
                },
                {
                    "name": "高阶素养培养",
                    "desc": "是否引导学生进行质疑、反思和评价；是否要求学生通过分析、建模、推理等方式解决问题。",
                    "options": [0, 1, 2],
                    "rubric": {
                        0: "题目仅考察对知识的简单记忆和复述，不涉及复杂分析、推理等高阶思维能力。",
                        1: "题目要求学生进行简单的分析或应用，但引导性不足，未能有效激发深度思考、质疑或反思。",
                        2: "题目能有效引导学生运用分析、建模、推理、评价等高阶思维方式解决复杂问题，或对问题进行开放性探究和批判性反思。",
                    },
                },
            ],
        },
        {
            "name": "约束满足",
            "desc": "主要考察模型输出是否满足用户指令与系统要求的约束（如题型格式、选项数量、必须包含答案/解析等）。",
            "need_comment": True,
            "subdims": [
                {
                    "name": "约束满足度",
                    "desc": "输出是否整体满足约束要求（格式/要素/限制条件等）。",
                    "options": [0, 1, 2],
                    "rubric": {
                        0: "多项关键约束未满足（结构/要素缺失或明显违背要求）。",
                        1: "大部分约束满足，但存在1~2处不符合或遗漏。",
                        2: "约束满足完整，无明显违背或遗漏。",
                    },
                },
            ],
        },
    ],
    "rank": {
        "name": "模型回答质量排名",
        "desc": "第1名/第2名/第3名（每个模型各自选择一个名次）。若前序阶段被判定终止，则排名自动记为 -1。",
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


def get_file_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except Exception:
        return 0.0


@st.cache_data(show_spinner=False)
def read_jsonl_cached(path: str, mtime: float) -> List[Dict[str, Any]]:
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
        os.makedirs(dir_name, exist_ok=True)

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
# 概率/期望分工具
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


def get_group_by_name(name: str):
    for g in SCHEMA["groups"]:
        if g["name"] == name:
            return g
    return None


def set_group_skipped(scores_root: Dict[str, Any], rid: str, group: Dict[str, Any], reason: str = "阶段跳过，记为-1"):
    gname = group["name"]
    scores_root.setdefault(rid, {})

    for sub in group["subdims"]:
        sname = sub["name"]
        scores_root[rid][f"{gname}_{sname}_score"] = -1

    scores_root[rid][f"{gname}_score"] = -1

    if group.get("need_comment", False):
        ck = f"{gname}_comment"
        old = scores_root[rid].get(ck, "")
        if old is None or str(old).strip() == "":
            scores_root[rid][ck] = reason


def set_rank_skipped(scores_root: Dict[str, Any], rid: str):
    rank_name = SCHEMA["rank"]["name"]
    scores_root.setdefault(rid, {})
    scores_root[rid][f"{rank_name}_score"] = "-1"


# =========================
# 完成判定
# =========================
def score_filled(v, opts):
    if v == -1 or v == "-1":
        return True

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

    for rid in required_rids:
        ms = scores.get(rid, {})

        g1 = get_group_by_name(STAGE1_GROUP)
        for sub in g1["subdims"]:
            sname = sub["name"]
            opts = sub.get("options", [0, 1, 2])
            k = f"{STAGE1_GROUP}_{sname}_score"
            if not score_filled(ms.get(k), opts):
                return False
        if g1.get("need_comment", False):
            ck = f"{STAGE1_GROUP}_comment"
            c = ms.get(ck)
            if c is None or str(c).strip() == "":
                return False

        stage1_score = ms.get(f"{STAGE1_GROUP}_score", None)

        if stage1_score == 0:
            for gname in LATE_GROUPS_AFTER_STAGE1_FAIL:
                g = get_group_by_name(gname)
                if g is None:
                    continue
                if ms.get(f"{gname}_score") != -1:
                    return False
            if ms.get(rank_key) not in [-1, "-1"]:
                return False
            continue

        g2 = get_group_by_name(STAGE2_GROUP)
        for sub in g2["subdims"]:
            sname = sub["name"]
            opts = sub.get("options", [0, 1, 2])
            k = f"{STAGE2_GROUP}_{sname}_score"
            if not score_filled(ms.get(k), opts):
                return False
        if g2.get("need_comment", False):
            ck = f"{STAGE2_GROUP}_comment"
            c = ms.get(ck)
            if c is None or str(c).strip() == "":
                return False

        stage2_score = ms.get(f"{STAGE2_GROUP}_score", None)

        if stage2_score == 0:
            for gname in LATE_GROUPS_AFTER_STAGE2_FAIL:
                g = get_group_by_name(gname)
                if g is None:
                    continue
                if ms.get(f"{gname}_score") != -1:
                    return False
            if ms.get(rank_key) not in [-1, "-1"]:
                return False

            g_constraint = get_group_by_name("约束满足")
            if g_constraint:
                for sub in g_constraint["subdims"]:
                    sname = sub["name"]
                    opts = sub.get("options", [0, 1, 2])
                    k = f"约束满足_{sname}_score"
                    if not score_filled(ms.get(k), opts):
                        return False
                if g_constraint.get("need_comment", False):
                    ck = "约束满足_comment"
                    c = ms.get(ck)
                    if c is None or str(c).strip() == "":
                        return False
            continue

        for gname in STAGE3_GROUPS + ["约束满足"]:
            g = get_group_by_name(gname)
            if g is None:
                continue

            for sub in g["subdims"]:
                sname = sub["name"]
                opts = sub.get("options", [0, 1, 2])
                k = f"{gname}_{sname}_score"
                if not score_filled(ms.get(k), opts):
                    return False

            if g.get("need_comment", False):
                ck = f"{gname}_comment"
                c = ms.get(ck)
                if c is None or str(c).strip() == "":
                    return False

        rank = ms.get(rank_key)
        if rank in [None, "", "未评分", -1, "-1"]:
            return False

    return True


# =========================
# 阶段状态判断（用于界面显示）
# =========================
def get_stage_status_for_rid(message: Dict[str, Any], rid: str, teacher_id: str):
    t_ann = get_teacher_annotation_readonly(message, teacher_id)
    scores = t_ann.get("scores") or {}
    ms = scores.get(rid, {})

    stage1_score = ms.get(f"{STAGE1_GROUP}_score", None)
    stage2_score = ms.get(f"{STAGE2_GROUP}_score", None)

    if stage1_score == 0:
        return {
            "stage1_failed": True,
            "stage2_failed": False,
            "reason": f"{STAGE1_GROUP} 总分为 0，后续维度自动跳过并记为 -1。",
        }

    if stage2_score == 0:
        return {
            "stage1_failed": False,
            "stage2_failed": True,
            "reason": f"{STAGE2_GROUP} 总分为 0，第三阶段维度自动跳过并记为 -1。",
        }

    return {
        "stage1_failed": False,
        "stage2_failed": False,
        "reason": "",
    }


def is_group_skipped_for_rid(group_name: str, status: Dict[str, Any]) -> bool:
    if status["stage1_failed"] and group_name in LATE_GROUPS_AFTER_STAGE1_FAIL:
        return True
    if status["stage2_failed"] and group_name in LATE_GROUPS_AFTER_STAGE2_FAIL:
        return True
    return False


def is_rank_skipped_for_status(status: Dict[str, Any]) -> bool:
    return status["stage1_failed"] or status["stage2_failed"]


# =========================
# 提交评分到 message
# =========================
def apply_scoring_form_to_message(message: Dict[str, Any]):
    teacher_id = st.session_state.teacher_id
    qid = message.get("q_id", "")
    t_ann = ensure_teacher_annotation(message, teacher_id)
    scores_root = t_ann.setdefault("scores", {})

    order = get_blind_order_for_qid(message, qid, teacher_id=teacher_id, persist=True)
    rindex = responses_index(message)

    rank_conf = SCHEMA["rank"]
    rank_name = rank_conf["name"]
    rank_key = f"{rank_name}_score"

    for group in SCHEMA["groups"]:
        gname = group["name"]

        for sub in group["subdims"]:
            sname = sub["name"]
            opts = sub.get("options", [0, 1, 2])

            for i in range(3):
                rid = order[i]
                if not rid or rid not in rindex:
                    continue

                scores_root.setdefault(rid, {})
                wkey = f"{qid}_{safe_key(gname)}_{safe_key(sname)}_{rid}"
                mean_key = f"{wkey}_mean"
                mean_val = float(st.session_state.get(mean_key, min(opts)))
                probs = mean_to_probs(opts, mean_val)
                scores_root[rid][f"{gname}_{sname}_score"] = probs

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

        if group.get("need_comment", False):
            for i in range(3):
                rid = order[i]
                if not rid or rid not in rindex:
                    continue
                scores_root.setdefault(rid, {})
                wkey_c = f"{qid}_{safe_key(gname)}_comment_{rid}"
                c = st.session_state.get(wkey_c, "")
                scores_root[rid][f"{gname}_comment"] = c

    for i in range(3):
        rid = order[i]
        if not rid or rid not in rindex:
            continue
        scores_root.setdefault(rid, {})
        wkey = f"{qid}_{safe_key(rank_name)}_{rid}"
        val = st.session_state.get(wkey, "未评分")
        scores_root[rid][rank_key] = val

    for rid in order:
        if not rid or rid not in rindex:
            continue

        ms = scores_root[rid]
        stage1_score = ms.get(f"{STAGE1_GROUP}_score", None)
        stage2_score = ms.get(f"{STAGE2_GROUP}_score", None)

        if stage1_score == 0:
            for gname in LATE_GROUPS_AFTER_STAGE1_FAIL:
                g = get_group_by_name(gname)
                if g:
                    set_group_skipped(scores_root, rid, g, reason=f"因{STAGE1_GROUP}总分为0，自动跳过并记为-1")
            set_rank_skipped(scores_root, rid)
            continue

        if stage2_score == 0:
            for gname in LATE_GROUPS_AFTER_STAGE2_FAIL:
                g = get_group_by_name(gname)
                if g:
                    set_group_skipped(scores_root, rid, g, reason=f"因{STAGE2_GROUP}总分为0，自动跳过并记为-1")
            set_rank_skipped(scores_root, rid)
            continue


# =========================
# 内容展示区
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
# 评分区（带友好跳过提示）
# =========================
def render_scoring_form(message: Dict[str, Any], idx: int, total_pages: int):
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

    action = None

    with st.form(key=f"score_form_{qid}", clear_on_submit=False):
        st.info(
            "评测顺序：题型匹配度 → 题目准确性 → 其余维度。"
            "若第一阶段总分为 0，则后续维度自动记为 -1；"
            "若第二阶段总分为 0，则第三阶段维度自动记为 -1。"
        )

        for group in SCHEMA["groups"]:
            gname = group["name"]
            gdesc = group.get("desc", "")
            need_comment = group.get("need_comment", False)

            with st.expander(f"📌 {gname}", expanded=False):
                if gdesc:
                    st.caption(f"**指标说明：** {gdesc}")

                cols_status = st.columns(3)

                # 先判断这一组是否对某些模型已跳过
                group_skip_flags = []
                for i in range(3):
                    rid = order[i]
                    if not rid or rid not in rindex:
                        group_skip_flags.append(False)
                        continue
                    status = get_stage_status_for_rid(message, rid, teacher_id)
                    group_skip_flags.append(is_group_skipped_for_rid(gname, status))

                if any(group_skip_flags):
                    st.warning("本维度对部分模型已自动跳过；界面显示“已跳过（保存为 -1）”的列无需填写。")

                for sub in group["subdims"]:
                    sname = sub["name"]
                    sdesc = sub.get("desc", "")
                    opts = sub.get("options", [0, 1, 2])
                    rubric = sub.get("rubric", {})

                    st.markdown(f"**🔖 {sname}**")
                    st.write(f"<span style='font-size: 0.9em;'>{sdesc}</span>", unsafe_allow_html=True)

                    if rubric:
                        rubric_lines = [
                            f"<div style='margin-bottom: 4px;'><b>{score}分</b>：{rubric[score]}</div>"
                            for score in opts if score in rubric
                        ]
                        if rubric_lines:
                            st.markdown(
                                f"<div style='background-color: #f4f6f9; padding: 10px 15px; border-radius: 6px; "
                                f"font-size: 0.85em; color: #2c3e50; margin-bottom: 15px; border-left: 4px solid #1f77b4;'>"
                                f"{''.join(rubric_lines)}"
                                f"</div>",
                                unsafe_allow_html=True,
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

                            status = get_stage_status_for_rid(message, rid, teacher_id)
                            skipped = is_group_skipped_for_rid(gname, status)

                            if skipped:
                                st.info("⏭️ 已跳过（保存为 -1）")
                                st.caption(status["reason"])
                                continue

                            scores_root.setdefault(rid, {})
                            sub_key = f"{gname}_{sname}_score"
                            prev = scores_root[rid].get(sub_key, "")

                            if prev == -1 or prev == "-1":
                                prev = float(min(opts))

                            wkey = f"{qid}_{safe_key(gname)}_{safe_key(sname)}_{rid}"
                            mean_key = f"{wkey}_mean"

                            default_mean = expected_from_prev(prev, opts)
                            grid = build_grid(float(min(opts)), float(max(opts)), float(PROB_STEP))
                            default_mean = min(grid, key=lambda x: abs(x - float(default_mean)))
                            default_idx = grid.index(default_mean)

                            st.selectbox(
                                "总分 E[S]",
                                options=grid,
                                index=default_idx,
                                key=mean_key,
                                format_func=lambda x: f"{x:.2f}",
                                label_visibility="collapsed",
                            )

                            current_mean = float(st.session_state.get(mean_key, default_mean))
                            probs = mean_to_probs(opts, current_mean)

                            if sorted(opts) == [0, 2]:
                                prob_str = f"P(0): {probs['0']:.2f} &nbsp;|&nbsp; P(2): {probs['2']:.2f}"
                            else:
                                prob_str = (
                                    f"P(0): {probs['0']:.2f} &nbsp;|&nbsp; "
                                    f"P(1): {probs['1']:.2f} &nbsp;|&nbsp; "
                                    f"P(2): {probs['2']:.2f}"
                                )

                            st.markdown(
                                f"<div style='font-size: 0.85em; color: #555; margin-top: 2px;'>{prob_str}</div>"
                                f"<div style='font-size: 1.15em; font-weight: 700; color: #1f77b4; "
                                f"margin-top: 4px; margin-bottom: 10px;'>👉 总分: {current_mean:.2f}</div>",
                                unsafe_allow_html=True,
                            )

                    st.divider()

                if need_comment:
                    st.markdown("💬 **维度整体评语（必填）**")
                    cols_c = st.columns(3)
                    for i in range(3):
                        rid = order[i]
                        label = MODEL_LABELS[i]
                        with cols_c[i]:
                            if not rid or rid not in rindex:
                                continue

                            status = get_stage_status_for_rid(message, rid, teacher_id)
                            skipped = is_group_skipped_for_rid(gname, status)

                            if skipped:
                                st.info("⏭️ 已跳过（评语自动保存）")
                                st.caption(status["reason"])
                                continue

                            scores_root.setdefault(rid, {})
                            ck = f"{gname}_comment"
                            prev_c = scores_root[rid].get(ck, "")
                            if prev_c in ["阶段跳过，记为-1", f"因{STAGE1_GROUP}总分为0，自动跳过并记为-1", f"因{STAGE2_GROUP}总分为0，自动跳过并记为-1"]:
                                prev_c = ""
                            wkey_c = f"{qid}_{safe_key(gname)}_comment_{rid}"
                            st.text_area(
                                f"{label} 评语",
                                value=prev_c,
                                key=wkey_c,
                                height=68,
                                label_visibility="collapsed",
                                placeholder=f"输入 {label} 的评语...",
                            )

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

                    status = get_stage_status_for_rid(message, rid, teacher_id)
                    if is_rank_skipped_for_status(status):
                        st.info("⏭️ 排名已跳过（保存为 -1）")
                        st.caption(status["reason"])
                        continue

                    scores_root.setdefault(rid, {})
                    prev_rank = scores_root[rid].get(rank_key, "未评分")
                    if prev_rank == "-1":
                        prev_rank = "未评分"
                    try:
                        rank_idx = rank_opts.index(prev_rank) if prev_rank != "" else 0
                    except ValueError:
                        rank_idx = 0

                    wkey = f"{qid}_{safe_key(rank_name)}_{rid}"
                    val = st.selectbox("名次", rank_opts, index=rank_idx, key=wkey, label_visibility="collapsed")
                    if rid in rindex and val not in [None, "", "未评分"]:
                        chosen_ranks.append(val)

            if len(chosen_ranks) != len(set(chosen_ranks)):
                st.error("⚠️ 当前名次存在重复，请为不同模型选择不同名次。")

        st.markdown("### ⚙️ 操作区")
        nav1, nav2, nav3 = st.columns([1, 1.2, 1])

        with nav1:
            prev_clicked = st.form_submit_button(
                "⬅️ 上一条",
                use_container_width=True,
                disabled=(idx <= 0),
            )

        with nav2:
            save_clicked = st.form_submit_button(
                "💾 保存本题评分",
                use_container_width=True,
                type="primary",
            )

        with nav3:
            next_clicked = st.form_submit_button(
                "下一条 ➡️",
                use_container_width=True,
                disabled=(idx >= total_pages - 1),
            )

    if prev_clicked:
        action = "prev"
    elif save_clicked:
        action = "save"
    elif next_clicked:
        action = "next"

    return action


# =========================
# 页面展示
# =========================
def display(message: Dict[str, Any], idx: int, total_pages: int):
    user_req = message.get("user_req", {}) or {}

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

    st.write("")
    col_left, col_right = st.columns([1.1, 1], gap="large")

    with col_left:
        st.markdown("##### 📊 模型输出区域")
        with st.container(height=PANEL_HEIGHT, border=True):
            render_outputs(message)

    with col_right:
        st.markdown("##### ⭐ 评分区域")
        with st.container(height=PANEL_HEIGHT, border=True):
            action = render_scoring_form(message, idx, total_pages)

    return action


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
# 保存函数
# =========================
def persist_all(file_path: str, data: List[Dict[str, Any]]):
    _sync_user_designed_question_to_data(data)
    write_jsonl_atomic(file_path, data)
    st.cache_data.clear()


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

    try:
        mtime = get_file_mtime(file_path)
        data = read_jsonl_cached(file_path, mtime)
    except FileNotFoundError:
        st.error(f"❌ 未找到编号 `{teacher_id}` 对应的数据文件：`{file_path}`。请联系管理员或先转换生成。")
        if st.button("重新输入编号"):
            del st.session_state.teacher_id
            st.rerun()
        return
    except Exception as e:
        st.error(f"❌ 读取 JSONL 失败：{str(e)}")
        return

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

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🧭 快速跳转")
    qid_to_index = {item.get("q_id", f"id_{i}"): i for i, item in enumerate(data)}
    selected_qid = st.sidebar.selectbox(
        "选择题目 ID 跳转",
        options=list(qid_to_index.keys()),
        label_visibility="collapsed",
    )

    if st.sidebar.button("🚀 跳转到该题目", use_container_width=True):
        st.session_state.page = qid_to_index[selected_qid]
        st.rerun()

    total_pages = len(data)
    idx = max(0, min(st.session_state.page, total_pages - 1))
    st.session_state.page = idx

    current = data[idx]
    qid = current.get("q_id", f"id_{idx}")

    st.title("🎯 题目质量评估工作台")
    st.markdown(
        f"**身份编号：** `{teacher_id}` &nbsp; | &nbsp; **当前进度：** 第 `{idx + 1}` / `{total_pages}` 条 &nbsp; | &nbsp; **题目 ID：** `{qid}`"
    )
    st.divider()

    action = display(current, idx, total_pages)

    if action in {"save", "prev", "next"}:
        try:
            apply_scoring_form_to_message(current)
            persist_all(file_path, data)

            if action == "save":
                st.success(f"✅ 本题评分已保存！({datetime.now().strftime('%H:%M:%S')})")
                st.rerun()
            elif action == "prev":
                st.session_state.page = max(0, idx - 1)
                st.rerun()
            elif action == "next":
                st.session_state.page = min(total_pages - 1, idx + 1)
                st.rerun()
        except Exception as e:
            st.error(f"❌ 保存评分失败：{str(e)}")

    if not is_question_scored(current, teacher_id):
        st.warning(
            "⚠️ 当前题目尚未完成评测。评测顺序为：题型匹配度 → 题目准确性 → 其余维度。"
            "若前序阶段得分为 0，后续未评维度将自动记为 -1。切换界面时系统会自动保存，但仍建议先点击“保存”。"
        )
    else:
        st.success("✅ 当前题目评分已完善！")

    st.markdown("---")

    col_bot_left, col_bot_right = st.columns([3, 2], gap="large")

    with col_bot_left:
        st.markdown("#### 💡 附加信息录入")
        prev_ud = current.get(USER_QUESTION_FIELD, "")
        with st.form(key=f"user_question_form_{qid}", clear_on_submit=False):
            wkey_ud = f"{qid}_{USER_QUESTION_FIELD}"
            st.text_area(
                "用户自拟题目（可选）",
                value=prev_ud,
                key=wkey_ud,
                height=135,
                placeholder="✍️ 若用户能自行设计更优题目，请在此录入；也可留空。",
                label_visibility="collapsed",
            )
            ud_submit = st.form_submit_button("💾 保存附加信息", use_container_width=False)

        if ud_submit:
            try:
                _sync_user_designed_question_to_data(data)
                persist_all(file_path, data)
                st.success(f"✅ 附加信息已保存！({datetime.now().strftime('%H:%M:%S')})")
                st.rerun()
            except Exception as e:
                st.error(f"❌ 保存附加信息失败：{str(e)}")

    with col_bot_right:
        st.markdown("#### ⚙️ 其他操作")
        st.write("")
        if st.button("🔄 刷新当前页", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        st.write("")
        if st.button("📥 导出全部评分结果 (JSONL)", use_container_width=True):
            try:
                _sync_user_designed_question_to_data(data)
                jsonl_str = "\n".join(json.dumps(it, ensure_ascii=False) for it in data)
                b64 = base64.b64encode(jsonl_str.encode("utf-8")).decode()
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"出题评分结果_{teacher_id}_{timestamp}.jsonl"
                href = (
                    f'<a href="data:application/json;base64,{b64}" download="{filename}" style="text-decoration:none;">'
                    f'<div style="text-align:center; padding:8px; background-color:#f0f2f6; border-radius:4px; color:#31333F;">'
                    f'👉 点击下载 {filename}</div></a>'
                )
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