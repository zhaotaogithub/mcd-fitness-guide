<div align="center">

# 减脂期麦门指南

**把「今天还剩 550 kcal」翻译成一份此刻就能下单的麦当劳订单。**

基于麦当劳中国 MCP 构建 · WorkBuddy Skill

</div>

---

## 问题

减脂最难的不是「不吃」，是**想吃麦当劳的时候不知道怎么吃**。

公开的热量表早就有，但没人帮你把它和这三件事算在一起：

- 你今天**还剩多少热量**
- 你附近**这家店此刻在卖什么**
- 你手里**这些券到底能不能用**

所以大多数人的做法是：打开 App 看一眼热量，凭感觉点一个麦香鸡，回家后悔。
或者更常见的——**干脆不吃，然后在晚上十点多报复性点一份大薯**。

## 这个 Skill 做什么

一次对话，四步，出一份能直接照着点的方案：

```
你说：我在减脂，今天还剩 550 kcal，人在北京三里屯

它做：
  ① 拉取 160 项餐品的完整营养数据（能量/蛋白质/脂肪/碳水/钠/钙）
  ② 定位三里屯真实门店，拉取此刻在售商品
  ③ 在 550 kcal 约束下求解，输出 保守/标准/放开 三档组合
  ④ 叠加该门店真实可用优惠券，算出实付金额

它给：
  原味板烧鸡腿炒双蛋堡  419 kcal  蛋白 27g  钠  715mg
  小杯玉米杯            53 kcal  蛋白  2g  钠    1mg
  大杯鲜萃咖啡           13 kcal  蛋白  1g  钠    3mg
  ─────────────────────────────────────────────
  合计 485 kcal (88% 预算) | 蛋白质 30g (100% 达成) | 钠 719mg
  实付 ¥XX（已叠加门店可用券）
```

## 为什么不只是「热量表」

| 只做热量表 | 本 Skill |
|---|---|
| 静态数据 | 实时查询，价格/库存/券都会变 |
| 只看热量 | 同时约束**蛋白质**与**钠** |
| 不知道能不能买到 | 与门店在售商品取交集 |
| 不考虑价格 | 叠加真实可用券，算实付 |
| 一档推荐 | 三档方案，让你自己选节奏 |

## 核心设计

### 1. 双线并行，最后取交集

```
营养线：list-nutrition-foods → 解析 → pick_meals.py 求解
门店线：query-nearby-stores → query-meals 拿在售商品
                    ↓
        交集 = 营养合理 ∩ 此刻买得到
                    ↓
        query-store-coupons + calculate-price → 实付金额
```

很多同类工具的通病是「营养上算得漂亮，门店里根本买不到」。
两条线独立跑完再取交集，输出的每一件都是真的能下单的。

### 2. 三档方案

| 档位 | 预算占比 | 定位 |
|---|---|---|
| 保守 | 70% | 宁少勿多，留机动空间 |
| 标准 | 90% | 热量与饱腹感平衡（**通常推荐**） |
| 放开 | 100% | 用满预算，吃得更满足 |

### 3. 有立场的配餐规则

不是冷冰冰的最优化，内置了一些真实经验：

- **烘烤优于油炸**：板烧鸡腿堡(391) 优于 麦辣鸡腿堡(485) 优于 巨无霸(513)
- **饮品是最大的破局点**：可乐中杯 147 kcal → 无糖可乐 0 kcal，一键省下一份小薯条
- **麦满分是全天最低卡的主食区**：烟肉蛋麦满分仅 260 kcal
- **薯条按级差**：迷你 106 / 小 210 / 中 289 / 大 379 kcal
- **警惕糖分刺客**：新地、麦旋风 240–300 kcal 且几乎全是糖
- **钠最容易被忽略**：麦辣鸡腿堡 1208mg、巨无霸 961mg，占每日上限一半

### 4. 会说「不」

- 预算 < 400 kcal 时**不硬凑最低卡组合**，而是提示拆成两餐
- 预算下三档收敛到同一方案时**如实告知**「这个预算在这份菜单里没有更好的填法」
- 用户提到糖尿病、肾病、高血压、孕期、进食障碍时**只给数据，建议遵医嘱**
- **不承诺减重效果**

## 安装

### 前置：申请麦当劳 MCP Token

1. 访问 https://open.mcd.cn/mcp
2. 右上角【登录】，手机号验证
3. 登录后点【控制台】→【激活】申请 MCP Token
4. 同意服务协议，复制 Token

### 配置 MCP

WorkBuddy：左侧边栏【专家·技能·连接器】→【连接器】→ 右上角【自定义连接器】→【配置 MCP】，
填入 `mcp-config.example.json` 的内容（把 `${MCD_MCP_TOKEN}` 换成真实 Token）。

### 放入 Skill

把 `skill/mcd-fitness-guide/` 目录放到：

- 用户级（跨项目可用）：`~/.workbuddy/skills/mcd-fitness-guide/`
- 项目级：`<项目>/.workbuddy/skills/mcd-fitness-guide/`

## 使用示例

### 对话式（推荐）

```
你：我在减脂，今天还剩 550 kcal 想吃麦当劳，人在北京三里屯

AI：（调用 list-nutrition-foods / query-nearby-stores / query-meals）
    （运行 pick_meals.py --budget 550 --protein 30）
    （调用 query-store-coupons / calculate-price）

    ## 今日麦门方案 · 剩余预算 550 kcal
    门店：麦当劳(三里屯店) storeCode: XXX
    ...
```

### 命令行

```bash
# ① 拉取营养数据（把 MCP 返回的原始文本存成 raw.txt）
python scripts/nutrition_parse.py raw.txt -o nutrition.json
# 已解析 158 项餐品营养数据 -> nutrition.json

# ② 求解配餐方案
python scripts/pick_meals.py --budget 550 --protein 30 --data nutrition.json

# ③ JSON 输出（供程序消费）
python scripts/pick_meals.py --budget 550 --data nutrition.json --json

# ④ 忌口过滤
python scripts/pick_meals.py --budget 600 --avoid "新地,麦旋风,派,咖啡" --data nutrition.json
```

## 脚本参数

### pick_meals.py

| 参数 | 默认 | 说明 |
|---|---|---|
| `--budget` | 必填 | 本餐热量预算（kcal） |
| `--protein` | 30 | 蛋白质目标（g） |
| `--data` | nutrition.json | 营养数据路径 |
| `--avoid` | 空 | 忌口关键字，逗号分隔 |
| `--json` | 关 | 输出 JSON |

退出码：`0` 正常 · `1` 输入异常 · `2` 无可行方案

## 项目结构

```
mcd-fitness-guide/
├── README.md                       本文件
├── CONTEST_DECLARATION.md          参赛声明（官方原文，不可改动）
├── MCP_INTEGRATION.md              MCP Server / Tool / 调用流程 / 业务价值
├── mcp-config.example.json         脱敏的 MCP 配置示例
├── workbuddy.md                    WorkBuddy 开发对话上下文
└── skill/
    └── mcd-fitness-guide/
        ├── SKILL.md                技能定义与工作流
        ├── scripts/
        │   ├── pick_meals.py       配餐求解引擎
        │   └── nutrition_parse.py  营养数据解析器
        └── references/
            ├── mcp-tools.md        工具清单与踩坑点
            ├── calculation-rules.md 计算规则与权重
            └── budget-guide.md     热量与蛋白质参考表
```

## 数据来源

全部来自麦当劳中国官方 MCP Server（`https://mcp.mcd.cn`），**不凭记忆报数字**：

- `list-nutrition-foods` —— 160 项营养数据（去重后 158）
- `query-nearby-stores` / `query-meals` —— 门店与在售商品
- `query-store-coupons` / `calculate-price` —— 可用券与实付金额

## 目标用户

- **减脂 / 控卡人群**：有热量预算，但不想放弃麦当劳
- **健身人群**：关注蛋白质摄入，需要在快餐里凑够蛋白质
- **健康管理人群**：需要控钠（高血压风险人群），想知道哪款钠最低
- **打工人**：午餐时间有限，想在预算内快速决定吃什么

## 免责声明

本项目为麦当劳程序员节创意开发大赛参赛作品，由参赛者独立开发，**非麦当劳官方产品**。

输出内容仅供参考，**不构成医疗、营养或其他专业建议**。餐品信息、价格及供应状态以麦当劳官方渠道的实时结果为准。有疾病史（糖尿病、肾病、高血压等）、孕期或进食障碍者请遵医嘱。

## 许可

本项目代码以 MIT 许可开源。麦当劳相关商标、餐品名称与营养数据归麦当劳及其关联方所有。

---

<div align="center">

**减脂不是不能吃，是知道怎么吃。**

</div>
