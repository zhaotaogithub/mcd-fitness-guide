#!/usr/bin/env python3
"""
nutrition_parse.py — 把 list-nutrition-foods 的返回原文解析成结构化 JSON。

MCP 返回的 data 字段是一个「表格型字符串」，格式为：

    [160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
      猪柳麦满分,null,1288,308,16,16,24,781,213
      巨无霸,null,2146,513,27,26,42,961,171

本脚本把它转成 list[dict]，并补充两个派生字段：
  - proteinPer100kcal : 每 100 kcal 含多少克蛋白质（蛋白质密度）
  - kcalPerYuan       : 若有价格则计算热量性价比（无价格时为 None）

用法：
    python nutrition_parse.py <raw_text_file>  -o nutrition.json
    cat raw.txt | python nutrition_parse.py -   -o nutrition.json

也可以作为模块导入：
    from nutrition_parse import parse_nutrition_text
    rows = parse_nutrition_text(text)
"""

import argparse
import json
import re
import sys
from typing import Any, Optional

# 表头字段顺序（来自 MCP 实际返回）
COLUMNS = [
    "productName",
    "nutritionDescription",
    "energyKj",
    "energyKcal",
    "protein",
    "fat",
    "carbohydrate",
    "sodium",
    "calcium",
]

# 需要转成数字的列
NUMERIC_COLUMNS = {
    "energyKj",
    "energyKcal",
    "protein",
    "fat",
    "carbohydrate",
    "sodium",
    "calcium",
}

# 表头形如：[160]{a,b,c}:  —— 注意它可能出现在字符串开头（前面没有换行），
# 也可能出现在某一行的行首，所以不能锚定 ^ 或 $。
HEADER_RE = re.compile(r"\[\d+\]\{([^}]*)\}\s*:?")


def _coerce(value: str) -> Any:
    """把 'null' 转成 None，数字字符串转成 int/float，其余保持字符串。"""
    v = value.strip()
    if v == "" or v.lower() == "null":
        return None
    try:
        if "." in v:
            return float(v)
        return int(v)
    except ValueError:
        return v


def _dig_data(obj: Any) -> Optional[str]:
    """
    在可能的嵌套结构里寻找 app 层的 data 字符串（形如 '[160]{...}:\\n...'）。

    优先级很重要：JSON-RPC 的 content[].text 里也包含表头文本（还夹着大段说明
    文字），但它不如 structuredContent.data 干净。所以先广度优先找 dict 的
    'data' 键，找不到再退而求其次接受任何含表头的字符串。
    """
    # 第一轮：只认 dict 里的 'data' 键
    found = _find_by_key(obj, "data")
    if found:
        return found
    # 第二轮：接受任意含表头的字符串
    return _find_any_header_string(obj)


def _find_by_key(obj: Any, key: str) -> Optional[str]:
    if isinstance(obj, dict):
        value = obj.get(key)
        if isinstance(value, str) and HEADER_RE.search(value):
            return value
        for v in obj.values():
            found = _find_by_key(v, key)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_by_key(item, key)
            if found:
                return found
    return None


def _find_any_header_string(obj: Any) -> Optional[str]:
    if isinstance(obj, str):
        m = HEADER_RE.search(obj)
        if m:
            # 从表头处截断，丢掉前面的说明文字
            return obj[m.start():]
        return None
    if isinstance(obj, dict):
        for v in obj.values():
            found = _find_any_header_string(v)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_any_header_string(item)
            if found:
                return found
    return None


def extract_data_block(raw: str) -> str:
    """
    MCP 的返回通常是三层包装：
      1. JSON-RPC 外层  {"jsonrpc":..,"result":{"content":[{"text": ...}]}}
      2. 人类可读的说明文字 + 'Original Response' + 一个 JSON 字符串
      3. 该 JSON 的 data 字段，才是真正的 '[160]{...}:\\n  猪柳麦满分,...' 表格

    本函数逐层剥离，拿到第 3 层。若拿不到就退回原始文本，交给逐行解析兜底。
    """
    # 先尝试整体当 JSON 解析（含前面有说明文字的情况）
    start = raw.find("{")
    while start != -1:
        try:
            payload = json.loads(raw[start:])
        except json.JSONDecodeError:
            # 尝试用括号配对扫描出一个完整 JSON 片段
            snippet = _scan_json(raw, start)
            if snippet is None:
                break
            try:
                payload = json.loads(snippet)
            except json.JSONDecodeError:
                start = raw.find("{", start + 1)
                continue
        found = _dig_data(payload)
        if found:
            return found
        break

    # 兜底：直接找表头行，从那里开始截
    m = HEADER_RE.search(raw)
    if m:
        return raw[m.start():]

    return raw


def _scan_json(text: str, start: int) -> Optional[str]:
    """从 start 处的 '{' 开始做括号配对，返回第一个完整 JSON 对象的文本。"""
    depth = 0
    in_str = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:idx + 1]
    return None


def parse_nutrition_text(raw: str) -> list[dict]:
    """
    解析营养表文本，返回结构化记录列表。

    注意真实形态：表头 '[160]{...}:' 与第一条数据常常**在同一行**，
    中间只隔一个换行转义已被解码的 '\\n'，所以先把表头切掉再逐行解析。
    """
    block = extract_data_block(raw)

    # 先摘掉表头（可能不在行首），记录它声明的字段顺序
    columns = COLUMNS
    header = HEADER_RE.search(block)
    if header:
        declared = [c.strip() for c in header.group(1).split(",") if c.strip()]
        if declared:
            columns = declared
        block = block[header.end():]

    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]

    rows: list[dict] = []
    for line in lines:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < len(columns):
            continue

        record: dict[str, Any] = {}
        for idx, col in enumerate(columns):
            value = parts[idx] if idx < len(parts) else None
            if col in NUMERIC_COLUMNS:
                record[col] = _coerce(value) if value is not None else None
            else:
                record[col] = value

        name = record.get("productName")
        if not name or not isinstance(name, str):
            continue
        # 数字列必须是数字，否则这行不是数据行
        if not isinstance(record.get("energyKcal"), (int, float)):
            continue

        # 派生字段
        kcal = record.get("energyKcal") or 0
        protein = record.get("protein") or 0
        record["proteinPer100kcal"] = (
            round(protein * 100 / kcal, 2) if kcal > 0 else None
        )
        record["kcalPerYuan"] = None

        rows.append(record)

    # 去重：同名餐品保留首次出现
    seen: set[str] = set()
    deduped: list[dict] = []
    for r in rows:
        key = r["productName"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    return deduped


def main() -> int:
    ap = argparse.ArgumentParser(
        description="解析麦当劳 MCP 营养数据为结构化 JSON"
    )
    ap.add_argument(
        "input",
        help="原始返回文本文件路径，'-' 表示从 stdin 读取",
    )
    ap.add_argument(
        "-o",
        "--output",
        default="nutrition.json",
        help="输出 JSON 路径（默认 nutrition.json）",
    )
    args = ap.parse_args()

    if args.input == "-":
        raw = sys.stdin.read()
    else:
        with open(args.input, "r", encoding="utf-8") as fh:
            raw = fh.read()

    rows = parse_nutrition_text(raw)

    if not rows:
        print("解析结果为空：请检查输入是否为 list-nutrition-foods 的返回文本。", file=sys.stderr)
        return 1

    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)

    print(f"已解析 {len(rows)} 项餐品营养数据 -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
