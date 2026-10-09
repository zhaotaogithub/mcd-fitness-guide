#!/usr/bin/env python3
"""
pick_meals.py — 在热量预算内，按蛋白质目标与营养质量筛出麦当劳配餐方案。

设计目标：把「今天还剩 550 kcal」翻译成 3 档可执行的组合。
本脚本只做营养层面的筛选与排序，不涉及门店在售性与优惠券——
那两部分由 MCP 的 query-meals / calculate-price 负责。

用法：
    python pick_meals.py --budget 550 --protein 30 --data nutrition.json
    python pick_meals.py --budget 550 --data nutrition.json --json
    python pick_meals.py --budget 500 --avoid "冰淇淋,新地,麦旋风" --data nutrition.json

退出码：0 正常；1 输入异常；2 无可行方案。
"""

import argparse
import json
import sys
from typing import Any, Optional

# ---------------------------------------------------------------- 分类

# 碳水/甜品/饮料类：允许与主餐自由搭配，热量低但营养密度低
DRINK_KEYWORDS = ["可乐", "雪碧", "咖啡", "红茶", "牛奶", "纯悦", "果汁", "朱古力", "柠檬"]
DESSERT_KEYWORDS = ["冰淇淋", "新地", "麦旋风", "派", "奶冻", "麦旋酷"]
FRIES_KEYWORDS = ["薯条", "薯饼", "油条"]

# 主餐：汉堡、鸡肉卷、麦满分等
MAIN_KEYWORDS = ["堡", "麦满分", "鸡排", "麦乐鸡", "鱼排", "板烧", "粥"]

# 糖分刺客：热量不算高，但基本是纯糖，减脂期按「高代价」处理
SUGAR_TRAP_KEYWORDS = ["新地", "麦旋风", "朱古力", "奶冻", "冰淇淋", "麦旋酷"]


def classify(name: str) -> str:
    """返回主餐 / 配餐 / 饮料 / 甜品 / 薯类 之一。"""
    for kw in DESSERT_KEYWORDS:
        if kw in name:
            return "甜品"
    for kw in DRINK_KEYWORDS:
        if kw in name:
            return "饮料"
    for kw in FRIES_KEYWORDS:
        if kw in name:
            return "薯类"
    for kw in MAIN_KEYWORDS:
        if kw in name:
            return "主餐"
    return "配餐"


def drink_family(name: str) -> Optional[str]:
    """
    饮料细分品类。同属一族的饮料不该同时出现两份
    （比如「大杯鲜萃咖啡 + 小杯鲜萃咖啡」）。
    """
    families = [
        ("咖啡", ["鲜萃咖啡", "浓缩咖啡", "美式", "拿铁", "卡布奇诺", "玛奇朵", "阿芙佳朵"]),
        ("奶类", ["牛奶", "奶铁", "燕麦奶", "豆浆"]),
        ("可乐", ["可乐"]),
        ("雪碧", ["雪碧"]),
        ("茶", ["红茶", "柠檬红茶", "伯爵红茶", "锡兰"]),
        ("果汁", ["苹果汁", "橙橙", "麦旋酷"]),
        ("朱古力", ["朱古力", "黑巧"]),
        ("冰沙", ["雪冰", "抹茶牛奶", "抹茶"]),
        ("水", ["纯悦", "怡泉"]),
    ]
    for family, keywords in families:
        if any(k in name for k in keywords):
            return family
    return None


def load_rows(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("营养数据文件应为 JSON 数组")
    return data


def enrich(rows: list[dict], avoid: list[str]) -> list[dict]:
    """补上分类、风味标签，并剔除忌口项与零热量项。"""
    out: list[dict] = []
    for r in rows:
        name = str(r.get("productName") or "").strip()
        if not name:
            continue
        if any(a and a in name for a in avoid):
            continue
        kcal = r.get("energyKcal")
        if not isinstance(kcal, (int, float)):
            continue

        r = dict(r)
        r["category"] = classify(name)
        r["isSugarTrap"] = any(k in name for k in SUGAR_TRAP_KEYWORDS)
        # 计算整份热量（默认 1 份）
        r["totalKcal"] = kcal
        out.append(r)
    return out


def score_main(r: dict, budget: float, protein_target: float) -> float:
    """
    主餐评分：越高越好。
    - 蛋白质密度（每 100 kcal 蛋白质克数）权重最高
    - 热量越贴近预算越好（避免「吃了跟没吃一样」）
    - 钠超标扣分
    - 纯糖项重罚
    """
    kcal = r["totalKcal"] or 1
    protein = r.get("protein") or 0
    sodium = r.get("sodium") or 0
    fat = r.get("fat") or 0

    density = protein * 100 / kcal if kcal else 0
    score = density * 12.0

    # 蛋白质绝对量奖励（减脂期主餐蛋白质越多越好，上限截断）
    score += min(protein, protein_target) * 0.55

    # 热量贴近度：落在预算 50%~100% 区间最佳
    fill = kcal / budget if budget else 1.0
    if 0.5 <= fill <= 1.0:
        score += 8
    elif fill > 1.0:
        score -= (fill - 1.0) * 60

    # 钠惩罚（1000mg 以上开始扣）
    if sodium > 1000:
        score -= (sodium - 1000) / 100.0
    # 脂肪惩罚
    if fat > 25:
        score -= (fat - 25) * 0.4
    # 糖分刺客
    if r["isSugarTrap"]:
        score -= 40

    return round(score, 2)


def score_side(r: dict, budget: float) -> float:
    """
    配餐/饮料评分：低热量 + 有额外价值优先。
    饮料几乎是「免费」的破局点——无糖可乐 0 kcal 但能提供口腹满足。
    """
    kcal = r["totalKcal"] or 0
    protein = r.get("protein") or 0
    score = 0.0
    if kcal <= 60:
        score += 10        # 极低卡，几乎无代价
    elif kcal <= 180:
        score += 4         # 可接受
    else:
        score -= (kcal - 180) / 60.0
    score += protein * 0.3
    if r["isSugarTrap"]:
        score -= 30
    return round(score, 2)


def build_plans(rows: list[dict], budget: float, protein_target: float) -> list[dict]:
    """产出 保守 / 标准 / 放开 三档方案。"""
    mains = [r for r in rows if r["category"] == "主餐"]
    sides = [r for r in rows if r["category"] in ("配餐", "薯类", "饮料", "甜品")]

    for r in mains:
        r["score"] = score_main(r, budget, protein_target)
        r["family"] = None
    for r in sides:
        r["score"] = score_side(r, budget)
        r["family"] = drink_family(r["productName"])

    mains.sort(key=lambda x: x["score"], reverse=True)
    sides.sort(key=lambda x: x["score"], reverse=True)

    # 「升级项」：极低卡饮料 + 干净的配餐，用于兜底凑满预算
    zero_drinks = [
        r for r in sides if r["totalKcal"] <= 5 and r["category"] == "饮料"
    ]

    tiers = [
        ("保守", 0.70, "宁少勿多，优先控热量"),
        ("标准", 0.90, "热量与饱腹感平衡"),
        ("放开", 1.00, "用满预算，吃得更满足"),
    ]

    plans: list[dict] = []
    for tier_name, ratio, note in tiers:
        cap = budget * ratio
        best: Optional[dict] = None

        for main in mains:
            if main["totalKcal"] > cap:
                continue

            base_kcal = main["totalKcal"]
            base_score = main["score"]
            candidates: list[tuple[str, list[dict], float, float]] = [
                ("仅主餐", [main], base_kcal, base_score)
            ]

            for side in sides[:30]:
                if side["productName"] == main["productName"]:
                    continue
                k1 = base_kcal + side["totalKcal"]
                if k1 > cap:
                    continue
                s1 = base_score + side["score"]
                candidates.append(("主餐+配餐", [main, side], k1, s1))

                # 第二个配餐：限制在 160 kcal 内，且不与已有项同族
                if side["totalKcal"] > 160:
                    continue
                for side2 in sides[:30]:
                    if side2["productName"] in (
                        main["productName"], side["productName"]
                    ):
                        continue
                    if side2["totalKcal"] > 160:
                        continue
                    # 同类别的第二份要有区分度：
                    #  - 两个都是饮料 → 必须是不同族
                    #  - 两个都是薯类/甜品 → 不要重复
                    if side["category"] == side2["category"] == "饮料":
                        if side["family"] and side["family"] == side2["family"]:
                            continue
                    elif side["category"] == side2["category"]:
                        continue

                    k2 = k1 + side2["totalKcal"]
                    if k2 > cap:
                        continue
                    candidates.append(
                        ("主餐+2配餐", [main, side, side2], k2, s1 + side2["score"])
                    )

            for label, items, kcal, sc in candidates:
                total_protein = sum(i.get("protein") or 0 for i in items)
                sc += min(total_protein, protein_target) * 0.4
                # 有饮品更完整（真实减脂依从性更好）
                if any(i["category"] == "饮料" for i in items):
                    sc += 5
                # 有固体配餐（薯类/配餐）加分，纯饮料组合不够像一顿饭
                if any(i["category"] in ("配餐", "薯类") for i in items):
                    sc += 4
                # 热量太低的组合在「放开」档不受欢迎（没吃到位）
                if tier_name == "放开" and kcal < cap * 0.75:
                    sc -= 12

                if best is None or sc > best["_score"]:
                    best = {
                        "tier": tier_name,
                        "note": note,
                        "label": label,
                        "items": items,
                        "kcal": kcal,
                        "protein": round(total_protein, 1),
                        "sodium": round(sum(i.get("sodium") or 0 for i in items), 0),
                        "fat": round(sum(i.get("fat") or 0 for i in items), 1),
                        "carb": round(
                            sum(i.get("carbohydrate") or 0 for i in items), 1
                        ),
                        "kcalRatio": round(kcal / budget * 100, 1) if budget else 0,
                        "_score": round(sc, 2),
                    }

        if best:
            best.pop("_score", None)
            plans.append(best)

    # 附上「零卡饮料替换建议」
    for p in plans:
        sugary = [
            i for i in p["items"]
            if i["category"] == "饮料" and i["totalKcal"] > 5
        ]
        if sugary and zero_drinks:
            saved = sum(i["totalKcal"] for i in sugary)
            p["upgradeHint"] = (
                f"把「{sugary[0]['productName']}」换成"
                f"「{zero_drinks[0]['productName']}」，可再省 {saved:.0f} kcal"
            )

    return plans


def render_text(plans: list[dict], budget: float, protein_target: float) -> str:
    lines = [
        f"热量预算 {budget:.0f} kcal · 蛋白质目标 {protein_target:.0f} g",
        "=" * 58,
    ]
    if not plans:
        lines.append("没有找到可行的组合。建议放宽热量预算，或拆分到两餐。")
        return "\n".join(lines)

    for p in plans:
        lines.append("")
        lines.append(f"【{p['tier']}方案】{p['note']}")
        lines.append("-" * 58)
        for item in p["items"]:
            cat = item["category"]
            lines.append(
                f"  · {item['productName']:<20s} "
                f"{item['totalKcal']:>5.0f} kcal  "
                f"蛋白 {item.get('protein') or 0:>4.0f}g  "
                f"钠 {item.get('sodium') or 0:>5.0f}mg  [{cat}]"
            )
        lines.append(
            f"  合计：{p['kcal']:.0f} kcal ({p['kcalRatio']:.0f}% 预算) | "
            f"蛋白质 {p['protein']:.0f}g | 脂肪 {p['fat']:.0f}g | "
            f"碳水 {p['carb']:.0f}g | 钠 {p['sodium']:.0f}mg"
        )
        pr = p["protein"] / protein_target * 100 if protein_target else 0
        lines.append(f"  蛋白质达成度：{pr:.0f}%")
        if p.get("upgradeHint"):
            lines.append(f"  提示：{p['upgradeHint']}")

    lines.append("")
    lines.append("=" * 58)
    lines.append("下一步：用 query-meals 核验门店在售，用 query-store-coupons")
    lines.append("+ calculate-price 核验真实价格。以上仅为营养层筛选结果。")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="在热量预算内筛选麦当劳配餐方案（减脂期麦门指南）"
    )
    ap.add_argument("--budget", type=float, required=True,
                    help="本餐剩余热量预算（kcal）")
    ap.add_argument("--protein", type=float, default=30.0,
                    help="本餐蛋白质目标（g，默认 30）")
    ap.add_argument("--data", default="nutrition.json",
                    help="营养数据 JSON 路径（由 nutrition_parse.py 生成）")
    ap.add_argument("--avoid", default="",
                    help="忌口关键字，逗号分隔，例如 '新地,麦旋风'")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = ap.parse_args()

    if args.budget <= 0:
        print("热量预算必须大于 0。", file=sys.stderr)
        return 1

    if args.budget < 400:
        print(
            "提示：单餐预算低于 400 kcal 属于较激进的节食区间，"
            "建议拆成两餐或适当上调。\n",
            file=sys.stderr,
        )

    try:
        rows = load_rows(args.data)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"读取营养数据失败：{exc}", file=sys.stderr)
        return 1

    avoid = [s.strip() for s in args.avoid.split(",") if s.strip()]
    rows = enrich(rows, avoid)

    plans = build_plans(rows, args.budget, args.protein)

    if args.json:
        print(json.dumps(plans, ensure_ascii=False, indent=2))
    else:
        print(render_text(plans, args.budget, args.protein))

    return 0 if plans else 2


if __name__ == "__main__":
    raise SystemExit(main())
