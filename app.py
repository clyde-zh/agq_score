import streamlit as st
import pandas as pd
import json
import re
from datetime import datetime
import base64
import random

# ========== 工具函数 ==========
def render_latex_textblock(text):
    pattern = re.compile(r"(\${1,2}.*?\${1,2})",re.DOTALL)
    res=""
    parts = pattern.split(text)
    for part in parts:
        if part.startswith("$$") or part.startswith("$"):
            res+=part
        else:
            res+=part.replace("\n","<br>")
    st.markdown(res,unsafe_allow_html=True)

def merge_scores_to_data(data, scores_dict):
    updated_data = []

    for item in data:
        qid = item.get("q_id", None)
        if not qid or qid not in scores_dict:
            updated_data.append(item)
            continue

        result_entry = {}

        for model_key in ["spark", "glm", "o4"]:
            model_scores = scores_dict[qid].get(model_key, {})
            result_entry[model_key] = model_scores

        item["result"] = result_entry
        updated_data.append(item)

    return updated_data

# ========== 加载评分数据 ==========
def load_scores(teacher_id):
    file_path = f"data_{teacher_id}.json"
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
            scores = {}
            for item in raw_data:
                qid = item.get("q_id")
                if qid and "result" in item:
                    scores[qid] = item["result"]
            return scores
    except FileNotFoundError:
        return {}

# ========== 展示布局的函数 ==========
def display(message, qid):
    st.markdown("## 用户需求：")
    st.markdown(message["query"])

    st.markdown("## 📊 模型 A / B / C 输出内容展示")

    # 定义原始模型键列表
    original_models = ["spark", "glm", "o4"]

    # 获取模型输出字段
    gen_questions = {
        "spark": message["gen_question_spark"],
        "glm": message["gen_question_glm"],
        "o4": message["gen_question_o4"]
    }

    # 如果尚未设置，则生成并保存随机顺序
    if "shuffled_model_order" not in st.session_state:
        shuffled_order = random.sample(original_models, k=3)
        st.session_state.shuffled_model_order = shuffled_order
    else:
        shuffled_order = st.session_state.shuffled_model_order

    # 固定列标题为“模型 A / B / C”
    col_a, col_b, col_c = st.columns(3)
    cols = [col_a, col_b, col_c]

    for i, model_key in enumerate(shuffled_order):
        with cols[i]:
            st.markdown("### 模型 " + chr(65 + i))  # 固定显示 A/B/C 标题
            render_latex_textblock(gen_questions[model_key])

    # 这里是评分表单
    render_scoring(qid)

# ========== 评分表单的函数 ==========
def render_scoring(qid: str):
    teacher_id = st.session_state.teacher_id

    dimensions = {
        "知识点匹配度（0,1,2）": {"type": "radio", "options": [0, 1, 2]},
        "题型匹配度（0,1,2）": {"type": "radio", "options": [0, 1, 2]},
        "题目准确性（0,1,2）": {"type": "radio", "options": [0, 1, 2]},
        "解析准确性（0,1,2）": {"type": "radio", "options": [0, 1, 2]},
        "素养导向性（0,2）": {"type": "radio", "options": [0, 2]},
        "题目难度（简单,中等,困难）": {"type": "radio", "options": ["简单", "中等", "困难"]},
        "模型回答质量排名（第1名,第2名,第3名）": {"type": "select", "options": ["未评分", "1", "2", "3"]}
    }

    scores = st.session_state.all_scores[teacher_id].setdefault("result", {})
    key = f"{qid}"
    scores.setdefault(key, {})

    if "shuffled_model_order" not in st.session_state:
        st.session_state.shuffled_model_order = ["spark", "glm", "o4"]
    shuffled_order = st.session_state.shuffled_model_order

    for dim_key, dim_info in dimensions.items():
        dim_type = dim_info["type"]
        options = dim_info["options"]
        cleaned_dim = dim_key.split("（")[0]

        st.markdown(f"**{dim_key}**")
        cols_inner = st.columns(3)

        for i in range(3):  # A/B/C 模型
            model_key_real = shuffled_order[i]
            model_name = f"模型 {chr(65 + i)}"

            key_score = f"{key}_{cleaned_dim}_score_{model_key_real}"
            key_comment = f"{key}_{cleaned_dim}_comment_{model_key_real}"

            scores[key].setdefault(model_key_real, {})

            prev_score = scores[key][model_key_real].get(f"{cleaned_dim}_scores", "")
            prev_comment = scores[key][model_key_real].get(f"{cleaned_dim}_comments", "")

            # 处理选项索引
            if isinstance(options[0], int):
                try:
                    index = options.index(int(prev_score)) if prev_score != "" else None
                except ValueError:
                    index = None
            else:
                try:
                    index = options.index(prev_score) if prev_score != "" else None
                except ValueError:
                    index = None

            # 渲染控件
            if dim_type == "radio":
                val_score = cols_inner[i].radio(model_name, options, key=key_score, index=index)
                if val_score is None:
                    cols_inner[i].caption("⚠️ 尚未评分")
                else:
                    cols_inner[i].caption("✅ 已评分")
                comment = cols_inner[i].text_area("评语", value=prev_comment, key=key_comment, height=70)

                if val_score is not None:
                    scores[key][model_key_real][f"{cleaned_dim}_scores"] = val_score
                else:
                    scores[key][model_key_real][f"{cleaned_dim}_scores"] = ""

                scores[key][model_key_real][f"{cleaned_dim}_comments"] = comment

            elif dim_type == "select":
                val_score = cols_inner[i].selectbox(model_name, options, index=index, key=key_score)
                if val_score == "未评分":
                    cols_inner[i].caption("⚠️ 尚未评分")
                else:
                    cols_inner[i].caption(f"✅ 已选第 {val_score} 名")

                # 仅保存排名信息，不需要评语
                if val_score != "未评分":
                    scores[key][model_key_real][f"{cleaned_dim}_scores"] = val_score
                else:
                    scores[key][model_key_real][f"{cleaned_dim}_scores"] = ""


# ========== 检查评分是否完成（仅检查评分，不检查评语）==========
def is_question_scored(qid, scores_dict):
    if qid not in scores_dict:
        return False

    question_scores = scores_dict[qid]
    dimensions = [
        "知识点匹配度",
        "题型匹配度",
        "题目准确性",
        "解析准确性",
        "素养导向性"
    ]

    for model_key in ["spark", "glm", "o4"]:
        if model_key not in question_scores:
            return False
        model_scores = question_scores[model_key]
        for dim in dimensions:
            score_key = f"{dim}_scores"
            value = model_scores.get(score_key)
            if value is None or value == "" or (isinstance(value, str) and not value.strip()):
                return False
    return True


# ========== 主程序入口 ==========
def main():
    if "confirm_navigate" not in st.session_state:
        st.session_state.confirm_navigate = None

    # 确保 teacher_id 已经设置
    if "teacher_id" not in st.session_state:
        # 如果没有 teacher_id，则显示输入界面
        st.title("教师评测系统")
        st.markdown("请输入您的教师编号（例如 T001）：")
        teacher_input = st.text_input("教师编号", "")
        if st.button("开始评测") and teacher_input.strip():
            st.session_state.teacher_id = teacher_input.strip().upper()
            st.rerun()
        return

    teacher_id = st.session_state.teacher_id


    # 初始化评分数据
    if "all_scores" not in st.session_state:
        st.session_state.all_scores = {teacher_id: {"result": load_scores(teacher_id)}}
    elif teacher_id not in st.session_state.all_scores:
        st.session_state.all_scores[teacher_id] = {"result": load_scores(teacher_id)}

    # ========== 加载数据：每位教师一个 JSON ==========
    file_path = f"data_{teacher_id}.json"
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        st.session_state.raw_data = data
    except FileNotFoundError:
        st.error(f"未找到编号 {teacher_id} 对应的数据文件：`{file_path}`。请联系管理员。")
        if st.button("重新输入编号"):
            del st.session_state.teacher_id
            st.rerun()
        return

    teacher_id = st.session_state.teacher_id
    data = st.session_state.raw_data
    scores = st.session_state.all_scores[teacher_id]["result"]

    # 计算完成率
    total_questions = len(data)
    completed_questions = sum(1 for item in data if is_question_scored(item.get("q_id"), scores))
    completion_rate = (completed_questions / total_questions) * 100 if total_questions > 0 else 0

    # 显示完成率统计面板
    st.sidebar.markdown("## 📊 完成情况")
    st.sidebar.write(f"总共题目数: {total_questions}")
    st.sidebar.write(f"已评分题目数: {completed_questions}")
    st.sidebar.write(f"完成率: {completion_rate:.2f}%")
    st.sidebar.progress(completion_rate / 100)

    # ========== 添加下拉选择器 + 自动保存跳转 ==========
    st.markdown("### 🧭 快速跳转到指定题目")

    # 构建 q_id 到 page 的映射
    qid_to_index = {item.get("q_id", f"id_{i}"): i for i, item in enumerate(data)}
    selected_qid = st.selectbox("选择题目 ID 跳转", options=list(qid_to_index.keys()))

    if st.button("跳转到该题目", use_container_width=True):
        # 当前页信息
        current_idx = st.session_state.page
        current_qid = data[current_idx].get("q_id", f"id_{current_idx}")
        teacher_id = st.session_state.teacher_id

        # 合并评分数据到原始数据中
        scores = st.session_state.all_scores[teacher_id]["result"]
        merged_data = merge_scores_to_data(data, scores)

        # 写入文件保存
        try:
            with open(f"data_{teacher_id}.json", "w", encoding="utf-8") as f:
                json.dump(merged_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            st.stop()

        # 跳转到目标页面
        st.session_state.page = qid_to_index[selected_qid]
        st.rerun()

    # ========== 页面导航 ==========
    total_pages = len(data)
    if "page" not in st.session_state:
        st.session_state.page = 0

    idx = st.session_state.page
    current = data[idx]
    qid = current.get("q_id", f"id_{idx}")

    st.markdown(f"#### 第 {idx + 1} / {total_pages} 条样本")
    st.markdown(f"**样本 ID：** {qid}")

    display(current, qid)

    # ========== 页面导航 + 评分检查 ==========
    col1, col2, col3 = st.columns([1, 1, 1])

    with col1:
        if idx > 0:
            if st.button("⬅️ 上一条"):
                qid = data[idx].get("q_id", f"id_{idx}")
                scores = st.session_state.all_scores[teacher_id]["result"]
                if not is_question_scored(qid, scores):
                    st.session_state.confirm_navigate = ("prev", teacher_id, qid)
                else:
                    # 清除随机顺序标记
                    if "shuffled_model_order" in st.session_state:
                        del st.session_state.shuffled_model_order
                    st.session_state.page -= 1
                    st.rerun()
    with col2:
        # ========== 手动保存当前页评分 ==========
        if st.button("💾 保存当前页评分"):
            teacher_id = st.session_state.teacher_id
            idx = st.session_state.page
            data = st.session_state.raw_data
            qid = data[idx].get("q_id", f"id_{idx}")

            scores = st.session_state.all_scores[teacher_id]["result"]

            # 合并当前评分到原始数据
            merged_data = merge_scores_to_data(data, scores)

            # 写入文件
            try:
                with open(f"data_{teacher_id}.json", "w", encoding="utf-8") as f:
                    json.dump(merged_data, f, indent=2, ensure_ascii=False)
                st.success("✅ 当前页评分已手动保存。")
            except Exception as e:
                st.error(f"❌ 保存失败：{str(e)}")
    with col3:
        if idx < total_pages - 1:
            if st.button("➡️ 下一条"):
                qid = data[idx].get("q_id", f"id_{idx}")
                scores = st.session_state.all_scores[teacher_id]["result"]
                if not is_question_scored(qid, scores):
                    st.session_state.confirm_navigate = ("next", teacher_id, qid)
                else:
                    # 清除随机顺序标记
                    if "shuffled_model_order" in st.session_state:
                        del st.session_state.shuffled_model_order
                    st.session_state.page += 1
                    st.rerun()

    # ========== 处理确认切换逻辑 ==========
    if st.session_state.confirm_navigate:
        direction, teacher_id, qid = st.session_state.confirm_navigate
        st.warning("⚠️ 当前题目尚未完成评分，确定要切换吗？")
        if st.button("确认切换并保存"):
            scores = st.session_state.all_scores[teacher_id]["result"]
            merged_data = merge_scores_to_data(data, scores)
            with open(f"data_{teacher_id}.json", "w", encoding="utf-8") as f:
                json.dump(merged_data, f, indent=2, ensure_ascii=False)

            if direction == "next":
                st.session_state.page += 1
            else:
                st.session_state.page -= 1

            st.session_state.confirm_navigate = None
            st.rerun()
        elif st.button("取消"):
            st.session_state.confirm_navigate = None
            st.rerun()

        # ========== 导出按钮 ==========
    st.markdown("---")
    if st.button("导出所有评分结果"):
        teacher_scores = st.session_state.all_scores.get(teacher_id, {})
        raw_data = st.session_state.raw_data

        merged_data = merge_scores_to_data(raw_data, teacher_scores.get("result", {}))

        json_str = json.dumps(merged_data, indent=2, ensure_ascii=False)
        b64 = base64.b64encode(json_str.encode("utf-8")).decode()
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"评分结果_{teacher_id}_{timestamp}.json"
        href = f'<a href="data:application/json;base64,{b64}" download="{filename}">📥 点击下载完整评分数据</a>'
        st.markdown(href, unsafe_allow_html=True)



if __name__ == "__main__":
    st.set_page_config(layout="wide")

    st.markdown("""
        <style>
            .block-container {
                padding-left: 2rem;
                padding-right: 2rem;
            }
        </style>
    """, unsafe_allow_html=True)

    main()