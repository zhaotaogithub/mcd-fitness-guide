# MCP 集成说明

本文件说明「减脂期麦门指南」实际使用的麦当劳 MCP Server、Tool、调用流程与业务价值。

## 一、使用的 MCP Server

| 项 | 值 |
|---|---|
| Server 名称 | `mcd-mcp`（麦当劳中国官方 MCP Server） |
| 接入地址 | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP |
| 鉴权方式 | 请求头 `Authorization: Bearer <MCP_TOKEN>` |
| 限流 | 600 次/分钟，超限返回 429 |
| Token 申请 | https://open.mcd.cn/mcp → 登录 → 控制台 → 激活 |
| 实测可用工具数 | 35 |

## 二、使用的 Tool 清单

### 核心工具（每次配餐必用）

| Tool | 用途 | 为什么必需 |
|---|---|---|
| `list-nutrition-foods` | 拉取 160 项餐品的能量/蛋白质/脂肪/碳水/钠/钙 | 整个 Skill 的数据基线。没有它就只能靠记忆报热量 |
| `query-nearby-stores` | 根据城市+地标定位真实门店，拿 `storeCode` | 脚本算出的候选必须落到「此刻这家店」，否则方案不可执行 |
| `query-meals` | 拉取该门店在售商品与 `productCode` | 与营养候选取交集，确保推荐的东西真的买得到 |
| `query-store-coupons` | 拿「该门店+该订单类型」下**真正可用**的券 | 减脂人群同样在意价格，且这是「省钱」环节的唯一可信来源 |
| `calculate-price` | 用真实商品+优惠券计算应付总价 | 把「营养方案」变成「能下单的订单」，输出实付金额 |

### 辅助工具（按场景调用）

| Tool | 用途 |
|---|---|
| `query-meal-detail` | 查套餐组成与可替换项，用于把套餐换成低卡组合 |
| `query-my-coupons` | 查看用户卡包已有券（仅展示，不用于比价） |
| `available-coupons` | 查看麦麦省可领取的券，引导先领券 |
| `auto-bind-coupons` | 一键领取所有可领券 |
| `now-time-info` | 取服务器当前时间，判断早餐/正餐时段与预约日期 |
| `campaign-calendar` | 当月营销活动，用于解释某些券的来源 |
| `query-my-account` | 积分余额，配合兑换场景 |
| `order-list` | 历史订单，用于分析用户口味偏好 |

### 下单工具（需用户显式确认）

| Tool | 用途 |
|---|---|
| `create-order` | 创建订单。**仅在用户明确说「下单」后调用** |

## 三、调用流程

```
┌─────────────────────────────────────────────────────────┐
│ 第 0 步：采集三个必需输入                                  │
│   剩余热量预算(kcal) / 就餐方式 / 位置或门店                │
└─────────────────────────────────────────────────────────┘
                          │
          ┌───────────────┴───────────────┐
          ▼                               ▼
┌──────────────────────┐      ┌──────────────────────────┐
│ 营养线                 │      │ 门店线                     │
│ ① list-nutrition-foods │      │ ② query-nearby-stores     │
│     ↓                 │      │      ↓                    │
│ 解析为 nutrition.json  │      │ 拿 storeCode               │
│     ↓                 │      │      ↓                    │
│ pick_meals.py 筛出     │      │ ③ query-meals             │
│ 保守/标准/放开 三档     │      │ 拿在售商品 + productCode    │
└──────────┬───────────┘      └────────────┬─────────────┘
           │                               │
           └───────────────┬───────────────┘
                           ▼
              ┌────────────────────────────┐
              │ 两者取交集：营养合理 ∩ 此刻在售 │
              └────────────┬───────────────┘
                           ▼
              ┌────────────────────────────┐
              │ ④ query-store-coupons      │
              │   拿该门店可用券             │
              │        ↓                   │
              │ ⑤ calculate-price          │
              │   逐券试算，取实付最低组合    │
              └────────────┬───────────────┘
                           ▼
              ┌────────────────────────────┐
              │ 输出方案（含热量/蛋白质/钠/实付）│
              │ ⑥ create-order（需用户确认）  │
              └────────────────────────────┘
```

### 关键设计：双线并行再取交集

很多同类工具的失败点是「营养上算得很漂亮，但门店根本买不到」。
本 Skill 把营养筛选与门店查询做成两条独立线，最后取交集，确保输出的每个餐品
都同时满足「营养上合理」与「此刻买得到」。

## 四、真实调用示例

以下为 2026-10-09 的实测记录（Token 已脱敏）。

### 4.1 初始化

```http
POST https://mcp.mcd.cn
Authorization: Bearer $MCD_MCP_TOKEN
Content-Type: application/json
Accept: application/json, text/event-stream

{"jsonrpc":"2.0","id":1,"method":"initialize",
 "params":{"protocolVersion":"2024-11-05","capabilities":{},
           "clientInfo":{"name":"mcd-fitness-guide","version":"1.0"}}}
```

响应：

```json
{"jsonrpc":"2.0","id":1,"result":{
  "capabilities":{"tools":{}},
  "protocolVersion":"2024-11-05",
  "serverInfo":{"name":"mcd-mcp","version":"1.0.0"}}}
```

### 4.2 拉取营养数据

```http
POST https://mcp.mcd.cn
Authorization: Bearer $MCD_MCP_TOKEN

{"jsonrpc":"2.0","id":10,"method":"tools/call",
 "params":{"name":"list-nutrition-foods","arguments":{}}}
```

响应（截取）：

```json
{"success":true,"code":200,"message":"请求成功",
 "data":"[160]{productName,nutritionDescription,energyKj,energyKcal,
          protein,fat,carbohydrate,sodium,calcium}:\n
          猪柳麦满分,null,1288,308,16,16,24,781,213\n
          巨无霸,null,2146,513,27,26,42,961,171\n
          ..."}
```

### 4.3 定位门店

```http
{"jsonrpc":"2.0","id":11,"method":"tools/call",
 "params":{"name":"query-nearby-stores",
           "arguments":{"searchType":2,"city":"北京市",
                        "keyword":"三里屯","beType":1}}}
```

### 4.4 比价

```http
{"jsonrpc":"2.0","id":13,"method":"tools/call",
 "params":{"name":"calculate-price",
           "arguments":{
             "storeCode":"<门店编码>",
             "orderType":1,
             "beType":1,
             "items":[{"productCode":"<商品编码>","quantity":1,
                       "couponId":"<券ID>"}]}}}
```

## 五、踩坑记录（真实遇到并解决）

| # | 现象 | 原因 | 解决 |
|---|---|---|---|
| 1 | 从返回里解析不出营养表 | 返回被包了三层：JSON-RPC 外壳 → `content[].text`（混着大段说明文字）→ `structuredContent.data` | 优先取 `structuredContent.data`，不要用正则从 `text` 里抠 |
| 2 | 按行解析时第一行总失败 | `data` 字符串里**表头与第一条数据在同一行**，只隔一个换行符 | 先把表头用正则切掉再逐行解析，见 `nutrition_parse.py` |
| 3 | 解析出 160 条但只有 158 个名字 | 存在完全重复项（如「小杯玉米杯」出现两次） | 按 `productName` 去重 |
| 4 | 方案里出现「大杯咖啡 + 小杯咖啡」 | 组合枚举没有商品族约束 | 引入 `drink_family()`，同族饮料不重复 |
| 5 | 用 `query-my-coupons` 比价，结果券用不了 | 该接口返回的是「我有什么券」，**不做门店与渠道校验** | 比价必须用 `query-store-coupons` |
| 6 | `query-nearby-stores` 返回 `600014` | `city` / `keyword` 写法不匹配 | 城市名带「市」字（如「北京市」）成功率更高 |
| 7 | 得来速下单缺参数 | `beType=5` 时 `beCode` 必传 | 把 `beCode` 一路带到 `query-meals` / `calculate-price` |

## 六、业务价值

### 6.1 解决的痛点

减脂人群面对麦当劳的真实困境不是「不知道热量」，而是：

1. **热量表是静态的，预算是个人的。** 公开的营养表没人帮你和「今天还剩多少」做减法。
2. **知道热量≠知道怎么点。** 「板烧鸡腿堡 391 kcal」和「我该怎么组合成一顿 550 kcal 的饭」之间隔着计算与取舍。
3. **便宜和低卡常常互相冲突。** 优惠券驱动的点餐天然倾向高热量组合（大杯可乐、大份薯条）。
4. **门店差异导致方案落空。** 网上抄来的「减脂套餐」到了店里可能根本没有。

本 Skill 把**营养数据 + 个人预算 + 门店库存 + 优惠券**四者算在一起，
输出一份「既在预算内、又真能下单、还顺手省钱」的订单。

### 6.2 对麦当劳的价值

| 维度 | 价值 |
|---|---|
| 触达场景 | 把「减脂期不敢进麦当劳」的犹豫客群重新拉回点餐链路 |
| 客单结构 | 引导用户从「大薯+可乐」转向「主餐+无糖+小食」，客单价未必下降但复购率提升 |
| 券核销 | 主动把 `query-store-coupons` 的券用进方案，提高券的核销率 |
| 数据洞察 | 用户主动提供热量预算与蛋白质目标，是极高质量的健康意图信号 |
| 品牌心智 | 让「麦当劳 = 减脂期也能吃的理性选择」，而非「破戒」 |

### 6.3 与官方示例的差异

官方举例「套餐推荐助手」「麦门省钱助手」。本项目的差异点是**引入个人的热量与
蛋白质预算作为约束条件**，把「推荐」变成「在约束下求解」，并且引入了
钠这一常被忽略但健康关联度高的指标。

## 七、安全与合规

- 所有 Token 通过环境变量注入，仓库内**不含任何真实凭证**
- 下单操作（`create-order`）**必须经用户显式确认**，绝不自动执行
- 不采集、不上传任何用户个人信息到第三方
- 输出标注「不构成医疗或营养建议；有疾病史请遵医嘱」
- 仅在用户主动请求时调用，不做后台轮询
