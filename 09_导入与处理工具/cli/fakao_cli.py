#!/usr/bin/env python3
"""法考提分 CLI：资料导入、诊断、任务生成和复测记录。"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "00_系统与用户" / "用户档案.json"
CONTRACT = ROOT / "00_系统与用户" / "学习合同.md"
QUESTION_DIR = ROOT / "04_题目训练库" / "结构化真题"
WRONG_DIR = ROOT / "04_题目训练库" / "错题"
RECORD_DIR = ROOT / "05_训练记录"
TASK_DIR = ROOT / "06_提分任务"
MOCK_DIR = ROOT / "07_模拟考试"
INBOX = ROOT / "01_待导入资料"
BANK_DIR = ROOT / "04_题目训练库" / "个性化题库"

KNOWLEDGE_RULES = {
    "刑法": {"犯罪构成": ["犯罪构成", "构成要件", "主观方面"], "正当防卫": ["正当防卫", "防卫过当"], "财产犯罪": ["盗窃", "抢劫", "诈骗", "侵占"], "共同犯罪": ["共同犯罪", "共犯"]},
    "民法": {"合同": ["合同", "违约", "解除"], "物权": ["物权", "所有权", "善意取得", "担保物权"], "侵权责任": ["侵权", "损害赔偿", "过错责任"]},
    "刑诉": {"证据": ["证据", "非法证据"], "强制措施": ["逮捕", "拘留", "取保候审", "强制措施"], "管辖": ["管辖", "立案", "侦查"], "审判程序": ["审判", "上诉", "抗诉"]},
    "民诉": {"管辖": ["管辖", "级别管辖", "地域管辖"], "证据": ["证据", "举证", "证明"], "执行": ["执行", "执行程序"]},
    "行政法": {"行政处罚": ["行政处罚", "处罚"], "行政复议": ["行政复议", "复议"], "行政诉讼": ["行政诉讼", "诉讼"], "行政行为": ["行政行为", "行政许可"]},
    "理论法": {"法治思想": ["法治思想", "依法治国"], "法理学": ["法理", "法律原则", "法律规则"], "宪法": ["宪法", "基本权利"]},
    "商经知": {"公司法": ["公司", "股东", "董事", "公司法"], "破产法": ["破产", "债权人会议"], "知识产权": ["商标", "专利", "著作权"]},
    "三国法": {"国际私法": ["冲突规范", "准据法", "国际私法"], "国际经济法": ["WTO", "贸易", "国际货物"], "国际公法": ["国际法", "条约", "国籍"]},
}
GLOBAL_KNOWLEDGE_RULES = {
    "环境法": ["环境保护法", "污染防治", "排污"],
    "劳动法": ["劳动合同", "工伤", "用人单位"],
    "监察法": ["监察机关", "监察法", "留置"],
}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def now():
    return datetime.now().isoformat(timespec="seconds")


def file_checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_within(path, directory):
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def subject_from_text(text):
    subjects = ["刑法", "民法", "刑诉", "民诉", "行政法", "理论法", "商经知", "三国法"]
    for s in subjects:
        if s in text:
            return s
    for kw in ["习近平法治思想", "法治思想", "法理学", "宪法"]:
        if kw in text:
            return "理论法"
    return "未分类"


def parse_questions(path):
    text = path.read_text(encoding="utf-8", errors="ignore")
    blocks = re.split(r"(?m)^##\s+", text)
    result = []
    for index, block in enumerate(blocks[1:], 1):
        lines = block.splitlines()
        title = lines[0].strip() if lines else ""
        question_match = re.search(r"\*\*题目:\*\*\s*\n(.*?)(?=\n\n\*\*选项:|\Z)", block, re.S)
        options = []
        for line in lines:
            match = re.match(r"-\s+\[([ xX])\]\s+([A-Z])\.\s+(.*)", line)
            if match:
                option_text = match.group(3).strip()
                options.append({
                    "id": match.group(2),
                    "text": option_text,
                    "correct": match.group(1).lower() == "x",
                    "user_selected": "❌ 我的答案" in option_text,
                })
        if not question_match and not options:
            continue
        source_subject = subject_from_text(path.name + " " + title + " " + block[:1200])
        source_key = hashlib.sha1(str(path.relative_to(ROOT)).encode("utf-8")).hexdigest()[:10]
        question_id = "Q-{}-{}".format(source_key, index)
        answers = [o["id"] for o in options if o["correct"]]
        user_answers = [o["id"] for o in options if o["user_selected"]]
        fingerprint_source = json.dumps(
            {"question": question_match.group(1).strip() if question_match else "", "options": [(o["id"], o["text"]) for o in options], "answers": answers},
            ensure_ascii=False,
            sort_keys=True,
        )
        item = {
            "id": question_id,
            "fingerprint": hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest(),
            "source_file": str(path.relative_to(ROOT)),
            "source_checksum": file_checksum(path),
            "title": title,
            "subject": source_subject,
            "question": question_match.group(1).strip() if question_match else "",
            "options": options,
            "answers": answers,
            "user_answers": user_answers,
            "is_imported_mistake": ("错题" in path.name) or bool(user_answers and set(user_answers) != set(answers)),
            "legal_version": "待确认",
            "review_status": "待审核",
            "tags": [],
            "review_count": 0,
            "last_review": None,
            "next_review": date.today().isoformat(),
            "status": "unreviewed",
        }
        enrich_question(item)
        result.append(item)
    return result


def enrich_question(question):
    text = " ".join([question.get("title", ""), question.get("question", ""), " ".join(o.get("text", "") for o in question.get("options", []))])
    question_type = re.search(r"(单选题|多选题|不定项选择题|判断题)", question.get("title", ""))
    question["question_type"] = question_type.group(1) if question_type else "未标注"
    subject_rules = KNOWLEDGE_RULES.get(question.get("subject"), {})
    points = [point for point, keywords in subject_rules.items() if any(keyword in text for keyword in keywords)]
    points.extend(point for point, keywords in GLOBAL_KNOWLEDGE_RULES.items() if any(keyword in text for keyword in keywords))
    question["knowledge_points"] = points or ["待标注"]
    return question


def cmd_init(args):
    profile = load_json(PROFILE, {})
    profile.update({
        "exam": "国家统一法律职业资格考试",
        "exam_date": args.exam_date or profile.get("exam_date", ""),
        "target_score": args.target_score if args.target_score is not None else profile.get("target_score", 108),
        "daily_minutes": args.daily_minutes if args.daily_minutes is not None else profile.get("daily_minutes", 120),
        "created_at": profile.get("created_at", now()),
        "updated_at": now(),
    })
    write_json(PROFILE, profile)
    CONTRACT.write_text(
        "# 学习合同\n\n"
        f"- 目标考试：{profile['exam']}\n"
        f"- 考试日期：{profile['exam_date'] or '待填写'}\n"
        f"- 目标分数：{profile['target_score']} 分\n"
        f"- 每日可用时间：{profile['daily_minutes']} 分钟\n\n"
        "## 执行规则\n\n"
        "1. 以真题、复测正确率和模拟成绩作为反馈。\n"
        "2. 原始资料只读，AI 生成内容须标注来源并审核。\n"
        "3. 每日只执行收益最高的有限任务，计划可根据作答数据重排。\n",
        encoding="utf-8",
    )
    print(json.dumps(profile, ensure_ascii=False, indent=2))


def cmd_import(args):
    source = Path(args.path).expanduser().resolve()
    if not source.exists():
        raise SystemExit("路径不存在: {}".format(source))
    files = [source] if source.is_file() else [p for p in source.rglob("*") if p.is_file()]
    copied = 0
    parsed = 0
    for file_path in files:
        if is_within(file_path, INBOX):
            target = file_path
        else:
            target_dir = INBOX / ("题库" if file_path.suffix.lower() in {".md", ".txt", ".json", ".csv"} else "其他")
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / file_path.name
            if target.exists() and file_checksum(target) != file_checksum(file_path):
                target = target_dir / (file_path.stem + "_" + file_checksum(file_path)[:10] + file_path.suffix)
            if not target.exists():
                shutil.copy2(file_path, target)
                copied += 1
        if target.suffix.lower() == ".md":
            output = QUESTION_DIR / (target.stem + ".json")
            existing = load_json(output, [])
            checksum = file_checksum(target)
            if existing and all(question.get("source_checksum") == checksum for question in existing):
                parsed += len(existing)
                continue
            questions = parse_questions(target)
            if questions:
                write_json(output, questions)
                parsed += len(questions)
    print("新增 {} 个文件，解析题目 {} 道。".format(copied, parsed))


def question_files():
    return sorted(QUESTION_DIR.glob("*.json"))


def all_questions():
    result = []
    for path in question_files():
        value = load_json(path, [])
        if isinstance(value, list):
            for question in value:
                enrich_question(question)
            result.extend(value)
    for path in WRONG_DIR.glob("*.md"):
        result.extend(parse_questions(path))
    unique = {}
    for question in result:
        key = question.get("fingerprint") or question["id"]
        # first-wins：结构化 json（含持久化的错题复测状态）先读入，
        # 不能被错题 md 的实时解析结果覆盖，否则复测排期丢失。
        if key not in unique:
            unique[key] = question
    return list(unique.values())


def cmd_inspect(args):
    files = [p for p in INBOX.rglob("*") if p.is_file()]
    questions = all_questions()
    subjects = {}
    for question in questions:
        subjects[question["subject"]] = subjects.get(question["subject"], 0) + 1
    print("待导入文件: {}".format(len(files)))
    print("可训练题目: {}".format(len(questions)))
    for subject, count in sorted(subjects.items()):
        print("- {}: {} 道".format(subject, count))


def cmd_index(args):
    """将已确认的 Markdown 题目建立本地结构化索引。"""
    sources = list((ROOT / "02_原始资料库").rglob("*.md"))
    total = 0
    files = 0
    for source in sources:
        questions = parse_questions(source)
        if not questions:
            continue
        source_key = hashlib.sha1(str(source.relative_to(ROOT)).encode("utf-8")).hexdigest()[:10]
        write_json(QUESTION_DIR / (source.stem + "_" + source_key + ".json"), questions)
        files += 1
        total += len(questions)
    print("已索引 {} 个文件，共 {} 道题目。".format(files, total))


def cmd_diagnose(args):
    questions = all_questions()
    records = load_json(RECORD_DIR / "作答记录.json", [])
    by_subject = {}
    for q in questions:
        by_subject.setdefault(q["subject"], {"total": 0, "wrong": 0})["total"] += 1
    for record in records:
        if record.get("result") == "wrong":
            subject = record.get("subject", "未分类")
            by_subject.setdefault(subject, {"total": 0, "wrong": 0})["wrong"] += 1
    diagnosis = {"generated_at": now(), "question_count": len(questions), "subjects": by_subject}
    write_json(RECORD_DIR / "诊断结果.json", diagnosis)
    print(json.dumps(diagnosis, ensure_ascii=False, indent=2))


def cmd_error_analysis(args):
    questions = {q["id"]: q for q in all_questions()}
    records = load_json(RECORD_DIR / "作答记录.json", [])
    groups = defaultdict(lambda: {"count": 0, "question_ids": [], "subjects": Counter(), "types": Counter()})
    recorded_ids = {record.get("question_id") for record in records}

    def add_record(record):
        if record.get("result") != "wrong" and record.get("confidence") != "low":
            return
        question = questions.get(record.get("question_id"), {})
        reason = record.get("reason") or "未标注错因"
        for point in question.get("knowledge_points", ["待标注"]):
            key = (reason, point)
            group = groups[key]
            group["count"] += 1
            group["question_ids"].append(record.get("question_id"))
            group["subjects"][question.get("subject", record.get("subject", "未分类"))] += 1
            group["types"][question.get("question_type", "未标注")] += 1

    for record in records:
        add_record(record)
    for question in questions.values():
        if question.get("is_imported_mistake") and question["id"] not in recorded_ids:
            add_record({
                "question_id": question["id"],
                "subject": question["subject"],
                "result": "wrong",
                "confidence": "medium",
                "reason": "导入历史错题，待标注错因",
            })
    analysis = []
    for (reason, point), value in sorted(groups.items(), key=lambda item: item[1]["count"], reverse=True):
        analysis.append({"reason": reason, "knowledge_point": point, "count": value["count"], "question_ids": value["question_ids"], "subjects": dict(value["subjects"]), "question_types": dict(value["types"])})
    output = RECORD_DIR / "错误分析.json"
    write_json(output, {"generated_at": now(), "groups": analysis})
    print(json.dumps({"group_count": len(analysis), "output": str(output.relative_to(ROOT))}, ensure_ascii=False, indent=2))


def cmd_build_bank(args):
    questions = all_questions()
    records = load_json(RECORD_DIR / "作答记录.json", [])
    wrong_ids = {r.get("question_id") for r in records if r.get("result") == "wrong"}
    wrong_ids.update(q["id"] for q in questions if q.get("is_imported_mistake"))
    error_rows = load_json(RECORD_DIR / "错误分析.json", {}).get("groups", [])
    priority_points = [row["knowledge_point"] for row in error_rows for _ in range(max(1, row["count"]))]
    point_rank = Counter(priority_points)
    candidates = []
    for question in questions:
        if question.get("id") in wrong_ids:
            continue
        points = [point for point in question.get("knowledge_points", ["待标注"]) if point != "待标注"]
        score = max((point_rank.get(point, 0) for point in points), default=0)
        if score:
            candidates.append((score, question))
    candidates.sort(key=lambda item: (-item[0], item[1].get("id", "")))
    selected = [{**question, "bank_reason": "针对错误知识点：{}".format("、".join(question.get("knowledge_points", []))), "priority_score": score} for score, question in candidates[:args.limit]]
    BANK_DIR.mkdir(parents=True, exist_ok=True)
    output = BANK_DIR / (date.today().isoformat() + ".json")
    write_json(output, selected)
    print(json.dumps({"question_count": len(selected), "output": str(output.relative_to(ROOT))}, ensure_ascii=False, indent=2))


def cmd_plan(args):
    profile = load_json(PROFILE, {})
    minutes = int(profile.get("daily_minutes", 120))
    errors = load_json(RECORD_DIR / "错误分析.json", {}).get("groups", [])
    bank = load_json(BANK_DIR / (date.today().isoformat() + ".json"), [])
    tasks = []
    for row in errors[: max(1, args.limit // 2)]:
        tasks.append({"type": "error_attack", "reason": row["reason"], "knowledge_point": row["knowledge_point"], "question_ids": row["question_ids"], "estimated_minutes": 15, "acceptance": "主动回忆 + 原题重做 + 隔日复测"})
    if bank:
        tasks.append({"type": "personalized_bank", "question_ids": [q["id"] for q in bank[:args.limit]], "estimated_minutes": min(30, minutes // 3), "acceptance": "完成后记录正确率、耗时和信心"})
    output = TASK_DIR / "本周计划" / (date.today().isoformat() + ".json")
    write_json(output, {"generated_at": now(), "daily_minutes": minutes, "strategy": "错误专项优先，再做针对性题库，依据新记录重新生成", "tasks": tasks})
    print(json.dumps({"task_count": len(tasks), "output": str(output.relative_to(ROOT))}, ensure_ascii=False, indent=2))


def question_year(question):
    match = re.search(r"(?:19|20)\d{2}", question.get("source_file", ""))
    return int(match.group(0)) if match else None


def recurring_terms(text):
    # 无第三方分词依赖时，使用中文二至四字短语作为候选线索；结果必须人工复核。
    text = re.sub(r"[^\u4e00-\u9fff]", "", text)
    terms = []
    for size in (2, 3, 4):
        terms.extend(text[i:i + size] for i in range(len(text) - size + 1))
    stop = {
        "下列", "关于", "选项", "正确", "错误", "构成", "属于", "可以", "应当", "行为", "情形", "说法",
        "的是", "哪一", "表述", "哪些", "是否", "某", "甲乙", "选项", "题目", "确的",
    }
    return [term for term in terms if len(term) == 4 and not any(token in term for token in stop)]


def cmd_analyze(args):
    questions = all_questions()
    years = sorted({question_year(q) for q in questions if question_year(q)})
    selected_years = years[-args.years:]
    recent = [q for q in questions if question_year(q) in selected_years]
    subject_year = Counter((q["subject"], question_year(q)) for q in recent)
    terms_by_subject = defaultdict(Counter)
    years_by_term = defaultdict(lambda: defaultdict(set))
    for question in recent:
        terms = set(recurring_terms(question.get("question", "")))
        terms_by_subject[question["subject"]].update(terms)
        for term in terms:
            years_by_term[question["subject"]][term].add(question_year(question))
    candidates = {
        subject: [{"term": term, "question_count": count, "year_count": len(years_by_term[subject][term])}
                  for term, count in counter.most_common(40)
                  if count >= 3 and len(years_by_term[subject][term]) >= 2]
        for subject, counter in terms_by_subject.items()
    }
    report = {
        "generated_at": now(),
        "method": "近十年题目频次与跨年度出现线索；短语候选需映射到正式考点后才能用于预测",
        "years": selected_years,
        "question_count": len(recent),
        "subject_year_count": {"{}-{}".format(subject, year): count for (subject, year), count in subject_year.items()},
        "prediction_candidates": candidates,
        "prediction_status": "heuristic_candidates_require_topic_review",
    }
    output = ROOT / "03_考点知识库" / "考点索引" / "近十年真题分析.json"
    write_json(output, report)
    markdown = ["# 近十年真题分析", "", "> 预测候选只表示频次线索，必须结合最新法规和人工审核，不代表押题结论。", "", "## 覆盖年份", "", ", ".join(map(str, selected_years)), "", "## 预测候选"]
    for subject, terms in sorted(candidates.items()):
        markdown.extend(["", "### {}".format(subject)])
        markdown.extend("- {}（{} 道题，跨 {} 年）".format(item["term"], item["question_count"], item["year_count"]) for item in terms[:10])
    (output.with_suffix(".md")).write_text("\n".join(markdown) + "\n", encoding="utf-8")
    print(json.dumps({"years": selected_years, "question_count": len(recent), "output": str(output.relative_to(ROOT))}, ensure_ascii=False, indent=2))


def cmd_error_attack(args):
    analysis = load_json(RECORD_DIR / "错误分析.json", {}).get("groups", [])
    if not analysis:
        cmd_error_analysis(args)
        analysis = load_json(RECORD_DIR / "错误分析.json", {}).get("groups", [])
    tasks = [{"type": "error_attack", "reason": row["reason"], "knowledge_point": row["knowledge_point"], "question_types": row.get("question_types", {}), "question_ids": row["question_ids"], "count": row["count"], "actions": ["先口述规则和成立条件", "再重做原题", "隔日完成同构变体", "三次独立答对后降级"]} for row in analysis]
    output = TASK_DIR / "补洞任务" / (date.today().isoformat() + "-错误专项.json")
    write_json(output, {"generated_at": now(), "tasks": tasks})
    print(json.dumps({"task_count": len(tasks), "output": str(output.relative_to(ROOT))}, ensure_ascii=False, indent=2))


def cmd_today(args):
    questions = all_questions()
    due = [q for q in questions if q.get("next_review") and q["next_review"] <= date.today().isoformat()]
    due = due[: max(1, min(20, getattr(args, "limit", 8)))]
    tasks = [{"type": "review_question", "question_id": q["id"], "subject": q["subject"], "reason": "错题或到期复测", "estimated_minutes": 3} for q in due]
    if not tasks:
        tasks = [{"type": "diagnostic", "reason": "暂无复测数据，先完成摸底题", "estimated_minutes": 20}]
    output = TASK_DIR / "今日任务" / (date.today().isoformat() + ".json")
    write_json(output, {"date": date.today().isoformat(), "tasks": tasks})
    print(json.dumps({"date": date.today().isoformat(), "tasks": tasks}, ensure_ascii=False, indent=2))


def record_review(question_id, result, seconds=0, confidence="medium", reason="",
                  source_type="original", training_stage="original_review",
                  independent=True, looked_at_explanation=False):
    """记录一次作答并更新复测排期；供 CLI 与 Web 共用。失败返回 {"ok": False, "error"}。"""
    questions = {q["id"]: q for q in all_questions()}
    question = questions.get(question_id)
    if not question:
        return {"ok": False, "error": "找不到题目: {}".format(question_id)}
    previous_records = load_json(RECORD_DIR / "作答记录.json", [])
    prior_issue = question.get("is_imported_mistake", False) or any(
        row.get("question_id") == question_id
        and (row.get("result") == "wrong" or row.get("confidence") in {"low", "guess"})
        for row in previous_records
    )
    record = {
        "time": now(),
        "question_id": question_id,
        "subject": question["subject"],
        "result": result,
        "seconds": seconds,
        "confidence": confidence,
        "reason": reason,
        "source_type": source_type,
        "training_stage": training_stage,
        "knowledge_points": question.get("knowledge_points", []),
        "independent": independent,
        "looked_at_explanation": looked_at_explanation,
    }
    records = previous_records
    records.append(record)
    write_json(RECORD_DIR / "作答记录.json", records)
    question["review_count"] = question.get("review_count", 0) + 1
    question["last_review"] = date.today().isoformat()
    if result == "correct" and confidence == "high" and independent and not prior_issue:
        question["next_review"] = None
        question["status"] = "correct_once"
    else:
        interval = 1 if result == "wrong" or confidence in {"low", "guess"} else min(14, 2 ** question["review_count"])
        question["next_review"] = (date.today() + timedelta(days=interval)).isoformat()
        question["status"] = "mastered" if result == "correct" and interval >= 4 else "reviewing"
    updated = False
    for json_file in question_files():
        items = load_json(json_file, [])
        changed = False
        for item in items:
            if item.get("id") == question["id"]:
                item.update(question)
                changed = True
        if changed:
            write_json(json_file, items)
            updated = True
    if not updated and "错题" in question.get("source_file", ""):
        # 来自错题 Markdown 的题目不在任何结构化 json 里；把复测状态持久化，
        # 否则每次重新解析 md 会丢失 next_review（错题会永远出现在今日任务）。
        source_stem = Path(question["source_file"]).stem
        output = QUESTION_DIR / "错题状态_{}.json".format(source_stem)
        items = [item for item in load_json(output, []) if item.get("id") != question["id"]]
        items.append(question)
        write_json(output, items)
    return {"ok": True, "question_id": question_id, "next_review": question["next_review"], "status": question["status"]}


def cmd_review(args):
    outcome = record_review(
        args.question_id, args.result, args.seconds, args.confidence, args.reason,
        args.source_type, args.training_stage, args.independent, args.looked_at_explanation,
    )
    if not outcome["ok"]:
        raise SystemExit(outcome["error"])
    print("已记录 {}，下次复测：{}".format(args.question_id, outcome["next_review"]))


def cmd_metrics(args):
    records = load_json(RECORD_DIR / "作答记录.json", [])
    prior_wrong = set()
    remedial = []
    for row in records:
        question_id = row.get("question_id")
        if question_id in prior_wrong:
            remedial.append(row)
        if row.get("result") == "wrong":
            prior_wrong.add(question_id)
    variant = [row for row in records if row.get("source_type") == "variant" and row.get("independent")]
    correct = [row for row in records if row.get("result") == "correct"]
    timed = [row for row in records if isinstance(row.get("seconds"), (int, float)) and row.get("seconds", 0) > 0]
    guessed = [row for row in correct if row.get("confidence") in {"low", "guess"} or row.get("reason") == "猜的"]
    def rate(numerator, denominator):
        return round(numerator / denominator, 4) if denominator else None
    mocks = load_json(MOCK_DIR / "模拟记录.json", [])
    comparable = [row for row in mocks if isinstance(row.get("score"), (int, float))]
    simulation_change = round(comparable[-1]["score"] - comparable[-2]["score"], 2) if len(comparable) >= 2 else None
    report = {
        "generated_at": now(),
        "sample_counts": {
            "all_attempts": len(records),
            "remedial_attempts": len(remedial),
            "variant_attempts": len(variant),
            "timed_attempts": len(timed),
        },
        "high_frequency_mistake_retest_accuracy": rate(sum(row.get("result") == "correct" for row in remedial), len(remedial)),
        "unseen_variant_accuracy": rate(sum(row.get("result") == "correct" for row in variant), len(variant)),
        "average_seconds": round(sum(row["seconds"] for row in timed) / len(timed), 2) if timed else None,
        "correct_but_low_confidence_ratio": rate(len(guessed), len(correct)),
        "simulation_score_change": simulation_change,
        "notes": ["复测正确率只统计某题首次错误之后的作答。", "任何指标样本不足时都不能视为提分证据。"],
    }
    output = RECORD_DIR / "提分指标.json"
    write_json(output, report)
    print(json.dumps({"output": str(output.relative_to(ROOT)), "metrics": report}, ensure_ascii=False, indent=2))


def cmd_mock_record(args):
    path = MOCK_DIR / "模拟记录.json"
    records = load_json(path, [])
    record = {
        "date": args.date or date.today().isoformat(),
        "score": args.score,
        "total_questions": args.total_questions,
        "seconds": args.seconds,
        "source": args.source,
        "notes": args.notes,
    }
    records.append(record)
    write_json(path, records)
    print(json.dumps(record, ensure_ascii=False, indent=2))


def cmd_cloud(args):
    script = Path(__file__).with_name("kuake_materials.py")
    command = [sys.executable, str(script), args.cloud_command]
    if args.cloud_command == "list":
        command.append(args.remote_path)
    else:
        command.extend([args.remote_path, args.local_path])
    raise SystemExit(subprocess.run(command, cwd=str(ROOT), check=False).returncode)


def run_zhuma(action, chrome_path=None):
    """运行竹马导入脚本；返回 {"returncode", "stdout", "stderr", "exported"}。供 CLI 与 Web 共用。"""
    script = Path(__file__).with_name("竹马全自动导出神器.py")
    command = [sys.executable, str(script), action]
    if chrome_path:
        command.extend(["--chrome-path", chrome_path])
    completed = subprocess.run(command, cwd=str(ROOT), check=False, capture_output=True, text=True)
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
        "exported": "错题导出完成" in (completed.stdout or ""),
    }


def cmd_zhuma(args):
    action = getattr(args, "action", None) or "auto"
    outcome = run_zhuma(action, args.chrome_path)
    if outcome["stdout"]:
        print(outcome["stdout"], end="")
    if outcome["stderr"]:
        print(outcome["stderr"], end="", file=sys.stderr)
    if outcome["returncode"]:
        raise SystemExit(outcome["returncode"])
    # 仅当脚本实际完成错题导出（出现成功标记）时才继续错误分析与今日任务；
    # open / 等待登录等分支没有该标记，不会误触发。
    if action in ("login", "auto") and outcome["exported"]:
        cmd_error_analysis(args)
        cmd_today(args)


def cmd_ui(args):
    server = Path(__file__).with_name("web") / "server.py"
    if not server.exists():
        raise SystemExit("缺少 Web 组件，请更新仓库。")
    try:
        import flask  # noqa: F401
    except ImportError:
        raise SystemExit(
            "Web 工作台需要 Flask：\n"
            "    pip3 install -r 09_导入与处理工具/web/requirements.txt\n"
            "（核心 CLI 功能仍零依赖，不受影响）"
        )
    raise SystemExit(subprocess.run(
        [sys.executable, str(server), "--host", args.host, "--port", str(args.port)],
        cwd=str(ROOT), check=False).returncode)


def build_parser():
    parser = argparse.ArgumentParser(prog="fakao", description="法考提分 CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="建立或更新用户档案")
    init.add_argument("--exam-date")
    init.add_argument("--target-score", type=int)
    init.add_argument("--daily-minutes", type=int)
    init.set_defaults(func=cmd_init)
    imp = sub.add_parser("import", help="导入用户资料并尝试解析 Markdown 题目")
    imp.add_argument("path")
    imp.set_defaults(func=cmd_import)
    zhuma = sub.add_parser("zhuma", help="导入竹马错题（auto/open/login/close）")
    zhuma.add_argument("action", nargs="?", default="auto", choices=["auto", "open", "login", "close"],
                       help="auto=有会话直接导出否则打开浏览器 open=打开浏览器 login=登录后导出 close=关闭浏览器")
    zhuma.add_argument("--chrome-path", help="Chrome、Chromium 或 Edge 的可执行文件路径")
    zhuma.set_defaults(func=cmd_zhuma)
    ui = sub.add_parser("ui", help="启动本地 Web 工作台")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=7800)
    ui.set_defaults(func=cmd_ui)
    for name, func, help_text in [("inspect", cmd_inspect, "检查导入和题目状态"), ("index", cmd_index, "为已确认资料建立题目索引"), ("analyze", cmd_analyze, "分析近十年真题并生成预测候选"), ("diagnose", cmd_diagnose, "生成分科诊断"), ("error-analysis", cmd_error_analysis, "分析错误知识点和题型"), ("build-bank", cmd_build_bank, "生成个人专项题库"), ("error-attack", cmd_error_attack, "生成错误专项突击任务"), ("plan", cmd_plan, "根据错误和题库生成迭代计划"), ("today", cmd_today, "生成今日提分任务"), ("metrics", cmd_metrics, "生成提分指标周报")]:
        item = sub.add_parser(name, help=help_text)
        if name == "analyze":
            item.add_argument("--years", type=int, default=10)
        if name == "build-bank":
            item.add_argument("--limit", type=int, default=30)
        if name == "plan":
            item.add_argument("--limit", type=int, default=6)
        if name == "today":
            item.add_argument("--limit", type=int, default=8)
        item.set_defaults(func=func)
    mock = sub.add_parser("mock-record", help="记录一次模拟考试结果")
    mock.add_argument("--score", type=float, required=True)
    mock.add_argument("--total-questions", type=int, default=0)
    mock.add_argument("--seconds", type=int, default=0)
    mock.add_argument("--date")
    mock.add_argument("--source", default="")
    mock.add_argument("--notes", default="")
    mock.set_defaults(func=cmd_mock_record)
    review = sub.add_parser("review", help="记录一次题目复测")
    review.add_argument("question_id")
    review.add_argument("--result", choices=["correct", "wrong"], required=True)
    review.add_argument("--seconds", type=int, default=0)
    review.add_argument("--confidence", choices=["low", "medium", "high", "guess"], default="medium")
    review.add_argument("--reason", default="")
    review.add_argument("--source-type", choices=["original", "variant", "recall"], default="original")
    review.add_argument("--training-stage", default="original_review")
    review.add_argument("--independent", action=argparse.BooleanOptionalAction, default=True)
    review.add_argument("--looked-at-explanation", action="store_true")
    review.set_defaults(func=cmd_review)
    cloud = sub.add_parser("cloud", help="通过 kuake 列出或下载待导入资料")
    cloud_sub = cloud.add_subparsers(dest="cloud_command", required=True)
    listing = cloud_sub.add_parser("list", help="列出夸克云盘目录")
    listing.add_argument("remote_path", nargs="?", default="/")
    listing.set_defaults(func=cmd_cloud)
    download = cloud_sub.add_parser("download", help="下载到 01_待导入资料")
    download.add_argument("remote_path")
    download.add_argument("local_path")
    download.set_defaults(func=cmd_cloud)
    return parser


if __name__ == "__main__":
    parsed = build_parser().parse_args()
    parsed.func(parsed)
