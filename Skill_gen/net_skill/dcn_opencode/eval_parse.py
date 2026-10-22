"""解析评测平台返回的 agents 结果：case 名、question、answer、准确率、轨迹。

结果接口返回 CSV（含轨迹与准确率），也可能拿到 JSON（list 或 {results:[...]} 包装）。
两种输入都按容错实现：每类信息接受常见命名别名（含中文表头），准确率接受
0–1 / 0–100 / 带 % 字符串三种规格，统一归一为 0–1 浮点。
拿到真实样例后收紧别名即可。
"""
import csv
import io

# 字段别名（含中文表头）：按顺序取第一个命中的键 / 列名，匹配忽略大小写与首尾空白。
ALIASES = {
    "case": ("case", "case_name", "用例", "用例名", "case名", "name", "id"),
    "question": ("question", "问题", "题目", "q", "problem", "prompt"),
    "answer": ("answer", "答案", "agent答案", "agent_answer", "final_answer", "response"),
    "expected": ("expected", "期望根因", "期望答案", "gold_answer", "gold", "standard_answer"),
    "accuracy": ("accuracy", "准确率", "acc", "score", "得分", "pass_rate", "rate"),
    "trace": ("trace", "轨迹", "执行轨迹", "trajectory", "agent_trace", "steps", "history"),
}


def _pick(item: dict, keys) -> object:
    for key in keys:
        if key in item and item[key] is not None:
            return item[key]
    return None


def normalize_accuracy(value) -> float:
    """把 0–1 / 0–100 / '85%' / '0.85' 归一为 0–1 浮点；无法解析返回 0.0。"""
    if isinstance(value, str):
        value = value.strip().rstrip("%").strip()
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number > 1:
        number /= 100.0
    return max(0.0, min(1.0, number))


def _trace_text(trace) -> str:
    if isinstance(trace, (list, tuple)):
        return "\n".join(str(step) for step in trace)
    return "" if trace is None else str(trace)


def parse_item(raw: dict) -> dict:
    """单条 agent 结果 → {case, question, answer, expected, accuracy, trace}。"""
    item = raw if isinstance(raw, dict) else {}
    return {
        "case": str(_pick(item, ALIASES["case"]) or ""),
        "question": str(_pick(item, ALIASES["question"]) or ""),
        "answer": str(_pick(item, ALIASES["answer"]) or ""),
        "expected": str(_pick(item, ALIASES["expected"]) or ""),
        "accuracy": normalize_accuracy(_pick(item, ALIASES["accuracy"])),
        "trace": _trace_text(_pick(item, ALIASES["trace"])),
    }


def _column_map(header) -> dict:
    """把 CSV 表头映射到标准字段：{字段名: 列名}，别名匹配忽略大小写与空白。"""
    lowered = [(name or "").strip().lower() for name in header]
    mapping = {}
    for field, aliases in ALIASES.items():
        for alias in aliases:
            if alias.lower() in lowered and field not in mapping:
                mapping[field] = header[lowered.index(alias.lower())]
    return mapping


def parse_csv(text: str) -> list:
    """CSV 文本 → 标准化结果列表；分隔符自动嗅探（逗号 / 分号 / 制表符），
    轨迹列的引号内换行由 csv 模块正确处理。"""
    sample = text.lstrip(chr(0xFEFF)).strip()
    if not sample:
        return []
    try:
        dialect = csv.Sniffer().sniff(sample.splitlines()[0], delimiters=",;\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    rows = csv.DictReader(io.StringIO(sample), delimiter=delimiter)
    header = rows.fieldnames or []
    mapping = _column_map(header)
    items = []
    for row in rows:
        if not any((value or "").strip() for value in row.values()):
            continue  # 跳过空行
        items.append(parse_item({field: row.get(column) for field, column in mapping.items()}))
    return items


def parse_agents(raw) -> list:
    """统一入口：CSV 文本 / JSON 列表 / {results|items|data: [...]} 包装 → 标准化结果列表。"""
    if isinstance(raw, str):
        return parse_csv(raw)
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = next((raw[key] for key in ("results", "items", "data", "agents")
                      if isinstance(raw.get(key), list)), [])
    else:
        items = []
    return [parse_item(item) for item in items if isinstance(item, dict)]


def summarize(items: list) -> dict:
    """汇总：平均准确率（无结果记 0）与条数。"""
    if not items:
        return {"accuracy": 0.0, "total": 0}
    return {"accuracy": sum(item["accuracy"] for item in items) / len(items), "total": len(items)}
