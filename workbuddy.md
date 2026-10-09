# WorkBuddy 开发上下文

本文件记录「减脂期麦门指南」在 WorkBuddy 中的开发过程与对话上下文，
用于核验本项目真实使用了 WorkBuddy 智能体完成开发。

## 开发环境

| 项 | 值 |
|---|---|
| 智能体 | WorkBuddy |
| 工作目录 | `C:/Users/Administrator/WorkBuddy/2026-10-09-19-30-00/mcd-fitness-guide` |
| 开发日期 | 2026-10-09 |
| 运行环境 | Windows / Git Bash |

## 开发过程摘要

### 阶段一：调研活动与 MCP 能力

1. 阅读活动仓库 `M-China/mcd-developer-innovation-challenge` 的 README 与
   `activityGuidelines.md`，明确参赛要求与排名规则（GitHub Star 数）
2. 阅读 `M-China/mcd-mcp-server`，确认 MCP 接入方式（Streamable HTTP、
   `https://mcp.mcd.cn`、Bearer Token）
3. 确认五大业务场景：麦乐送点餐、到店取餐、团餐、积分兑换券、活动日历

### 阶段二：连通性与工具探测

用申请的 MCP Token 实际调用服务器，验证 35 个工具可用：

```bash
# 初始化
curl -s -X POST "https://mcp.mcd.cn" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer $MCD_MCP_TOKEN" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize",
       "params":{"protocolVersion":"2024-11-05","capabilities":{},
                 "clientInfo":{"name":"probe","version":"1.0"}}}'

# 列出工具
curl -s -X POST "https://mcp.mcd.cn" ... \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

实测结果：35 个工具，`list-nutrition-foods` 返回 160 条营养数据。

**关键观察**：营养数据的返回结构是三层包装
（JSON-RPC → `content[].text` → `structuredContent.data`），
且 `data` 字符串中**表头与第一条数据同行**。这两点是后续解析器设计的核心依据。

### 阶段三：选题与方案设计

选定「减脂期麦门指南」，理由是：

1. `list-nutrition-foods` 是明确为「帮助用户搭配指定热量套餐」设计的工具，
   说明官方鼓励这个方向
2. 减脂人群对麦当劳存在真实的「想吃但不敢」的心理阻力，痛点明确
3. 该场景天然需要组合多个工具（营养 + 门店 + 券 + 价格），
   能体现 MCP 的组合价值，而非单工具调用

### 阶段四：实现

| 产出 | 说明 |
|---|---|
| `SKILL.md` | 技能定义：三个必需输入、六步工作流、输出模板、配餐经验规则、边界与拒答 |
| `nutrition_parse.py` | 解析器：三层解包 → 表头剥离 → 逐行解析 → 去重 → 派生字段 |
| `pick_meals.py` | 求解引擎：分类 → 评分 → 组合枚举 → 三档输出 |
| `references/*.md` | 工具清单、计算规则、热量参考表 |

### 阶段五：调试

开发过程中遇到并修复的问题（详见 `MCP_INTEGRATION.md` 第五节）：

1. **解析器拿到整个文件而非数据块**
   —— 根因：`HEADER_RE` 锚定了 `^`，但表头出现在字符串开头（前面无换行）
   —— 修复：改为 `r"\[\d+\]\{([^}]*)\}\s*:?"`，去掉行首锚定

2. **表头与首条数据同行**
   —— 根因：`data` 字符串中表头后直接跟换行符再接数据，`splitlines()` 后首行混在一起
   —— 修复：先用正则切掉表头，再逐行解析

3. **方案出现「大杯咖啡 + 小杯咖啡」**
   —— 根因：组合枚举无商品族约束
   —— 修复：引入 `drink_family()`，同族饮料不重复；同类别配餐不重复两份

4. **三档方案收敛为同一结果**
   —— 根因：小预算下确实没有更好的填法（这其实是正确行为）
   —— 处理：保留该行为，但在 `REFERENCES` 与输出说明中如实告知用户

5. **`--json` 输出缺少 `note` 字段**
   —— 修复：在 `best` 字典中补上 `note`

### 阶段六：验证

```bash
# 解析验证
python scripts/nutrition_parse.py nutri.json -o nutrition.json
# → 已解析 158 项餐品营养数据

# 配餐验证（550 kcal）
python scripts/pick_meals.py --budget 550 --protein 30 --data nutrition.json
# → 标准方案：485 kcal | 蛋白质 30g | 钠 719mg（三项指标同时达标）

# 配餐验证（800 kcal，验证三档差异化）
python scripts/pick_meals.py --budget 800 --protein 40 --data nutrition.json
# → 保守 558 / 标准 584 / 放开 718 kcal，三档正常区分

# 边界验证（低预算告警）
python scripts/pick_meals.py --budget 300 --data nutrition.json
# → 提示：单餐预算低于 400 kcal 属于较激进的节食区间

# 忌口验证
python scripts/pick_meals.py --budget 600 --avoid "新地,麦旋风,派,咖啡" --data nutrition.json
# → 已正确过滤

# JSON 输出验证
python scripts/pick_meals.py --budget 550 --data nutrition.json --json
# → 三个 tier 正常输出
```

## WorkBuddy 在本项目中的具体作用

| 环节 | WorkBuddy 做了什么 |
|---|---|
| 活动调研 | 抓取并结构化 GitHub 仓库与活动规则，提炼参赛硬约束 |
| MCP 探测 | 编写并执行 curl 探针，验证连通性、枚举工具、捕获真实返回样例 |
| 数据分析 | 从 160 条营养数据中识别规律（低卡区、薯条级差、钠分布） |
| 工程实现 | 生成并迭代两个 Python 脚本，含完整类型标注与参数校验 |
| 调试 | 依据真实报错定位三层包装与表头同行问题，逐轮修复并回归验证 |
| 文档 | 生成 README、MCP_INTEGRATION、SKILL 与三份 reference |

## 可复现步骤

```bash
# 1. 申请 MCP Token
#    https://open.mcd.cn/mcp → 登录 → 控制台 → 激活

# 2. 配置 MCP（WorkBuddy 连接器页）
#    参考 mcp-config.example.json

# 3. 拉取营养数据并保存为 raw.txt
#    在对话中让 WorkBuddy 调用 list-nutrition-foods

# 4. 解析与求解
python scripts/nutrition_parse.py raw.txt -o nutrition.json
python scripts/pick_meals.py --budget 550 --protein 30 --data nutrition.json
```

## 备注

- 脚本仅依赖 Python 标准库（`argparse` / `json` / `re` / `sys` / `typing`），无第三方依赖
- Python 3.9+ 可运行（使用了 `list[dict]` 等 PEP 585 泛型标注需 3.9+）
- 所有 Token 通过环境变量注入，仓库内不含任何真实凭证
