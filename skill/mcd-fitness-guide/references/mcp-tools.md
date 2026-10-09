# 本 Skill 使用的麦当劳 MCP 工具

所有数据一律实时查询，**不凭记忆报数字**。

- MCP Server 地址：`https://mcp.mcd.cn`（Streamable HTTP）
- 鉴权：请求头 `Authorization: Bearer <MCP Token>`
- 限流：600 次/分钟，超限返回 429

## 调用顺序总览

```
list-nutrition-foods            ← ① 营养基线，无入参
        ↓
query-nearby-stores             ← ② 定位真实门店，拿 storeCode
        ↓
query-meals                     ← ③ 拿该门店在售商品与 productCode
        ↓
query-store-coupons             ← ④ 拿「这单能用」的券（不是「我有什么券」）
        ↓
calculate-price                 ← ⑤ 核验真实应付金额
        ↓
create-order                    ← ⑥ 仅在用户明确确认后调用
```

营养层筛选（`scripts/pick_meals.py`）与门店层查询是**两条并行线**，最后取交集。

---

## ① list-nutrition-foods —— 餐品营养信息

**入参**：无（`{}`）

**返回**：`data` 字段是一个表格字符串，形如

```
[160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
  猪柳麦满分,null,1288,308,16,16,24,781,213
  巨无霸,null,2146,513,27,26,42,961,171
```

字段含义：名称、营养描述、能量(kJ)、能量(kcal)、蛋白质(g)、脂肪(g)、碳水(g)、钠(mg)、钙(mg)。

**踩坑点**：

1. 返回被三层包装：JSON-RPC 外壳 → `content[].text`（含大段说明文字）→ `structuredContent.data`（干净表格）。**取 `structuredContent.data`**，不要用正则从 `text` 里抠。
2. `data` 字符串里**表头与第一条数据在同一行**（表头后跟一个换行符），所以不能按「表头独占一行」来解析。参考 `scripts/nutrition_parse.py` 的 `HEADER_RE`。
3. `nutritionDescription` 常见为 `null`；偶有非空（如「能量约鲈鱼1条」）。
4. 有重复项（如「小杯玉米杯」出现两次），需按名称去重。
5. 实测 160 条，去重后 158 条。

---

## ② query-nearby-stores —— 查询附近门店

**入参**：

| 参数 | 必填 | 说明 |
|---|---|---|
| `searchType` | 是 | `2`=按位置搜索；`1`=搜索收藏餐厅 |
| `city` | searchType=2 时必填 | 城市名 |
| `keyword` | searchType=2 时必填 | 位置关键词 |
| `beType` | 是 | `1`=到店自取；`5`=得来速 |

**返回关键字段**：`storeName`、`address`、`distance`、`storeCode`（后续工具入参）、`beCode`（beType=5 时必传）、`reservation`。

**踩坑点**：

- `city` 用「北京市」这种带「市」的写法成功率更高；不匹配时返回 `code=600014 没有查询到该地址`。
- `beType=1`（到店自取）返回的门店**没有 beCode**，后续调用不要传。
- `beType=5`（得来速）必须把 beCode 一路带到 `query-meals` / `calculate-price`。

---

## ③ query-meals —— 查询餐品列表

**入参**：

| 参数 | 必填 | 说明 |
|---|---|---|
| `storeCode` | 是 | 门店编码 |
| `orderType` | 是 | `1`=到店（含自取+得来速）；`2`=外送（含麦乐送+团餐） |
| `beType` | 是 | `1` / `2` / `5` / `6` |
| `beCode` | 得来速/外送/团餐必传 | 从门店接口取 |
| `reservationDate` | 预约场景必传 | 格式 `yyyy-MM-dd HH:mm` |

**传参规则组合**：

| 场景 | orderType | beCode |
|---|---|---|
| 到店自取 (beType=1) | 1 | 不传 |
| 得来速 (beType=5) | 1 | 必传 |
| 麦乐送 (beType=2) | 2 | 必传 |
| 团餐 (beType=6) | 2 | 必传 |

---

## ④ 优惠券：三个工具别搞混

| 工具 | 含义 | 用途 |
|---|---|---|
| `available-coupons` | 麦麦省**可领取**的券 | 引导用户先领券 |
| `query-my-coupons` | 我卡包里**已有**的券 | 查看资产，**不做门店/渠道校验** |
| `query-store-coupons` | **指定门店+订单类型下可用**的券 | 比价时必须用这个 |

**关键**：`query-my-coupons` 返回的券**不承诺可用于当前订单**。要比价，必须用 `query-store-coupons`。

`auto-bind-coupons` 可一键领取麦麦省所有可领券，无入参。

---

## ⑤ calculate-price —— 价格计算

**入参**：

- `storeCode`、`orderType`、`beType`（+ 场景相关 `beCode`）
- `items[]`：`productCode`（必填）、`quantity`（必填，≥1）、`couponId`/`couponCode`（选填，用券时传）
- `reservationDate`（预约场景）

**返回**：商品金额、配送费、优惠金额、**应付总价**。

**用法**：有多张券可选时，**分别算一遍**，取实付最低的组合。

**踩坑点**：`modification`（特制）的 `key` 传参有讲究——选中项用 `selectedKey`，未选中项若 `unselectedKey` 非空则用它。改套餐组合走 `roundList`。

---

## ⑥ create-order —— 创建订单

**仅在用户明确说「下单」后调用。** 调用前必须复述门店、商品、数量、实付金额。

---

## 辅助工具

| 工具 | 用途 |
|---|---|
| `now-time-info` | 拿服务器当前时间，用于判断早餐/正餐时段与预约日期 |
| `campaign-calendar` | 当月营销活动日历 |
| `query-my-account` | 积分余额 |
| `order-list` | 历史订单（可分析用户口味偏好） |
| `query-meal-detail` | 餐品详情与可替换选项，用于定制套餐 |

---

## 错误码

| code | 原因 | 处理 |
|---|---|---|
| 401 | Token 无效/过期/未提供 | 检查 Authorization 头 |
| 429 | 触发限流（>600 次/分） | 降低频率 |
| 600014 | 未查询到该地址 | 换城市/关键词写法 |

---

## 真实调用记录（2026-10-09 实测）

```
POST https://mcp.mcd.cn
Authorization: Bearer <TOKEN>

{"jsonrpc":"2.0","id":10,"method":"tools/call",
 "params":{"name":"list-nutrition-foods","arguments":{}}}

→ {"success":true,"code":200,
   "data":"[160]{productName,nutritionDescription,energyKj,energyKcal,
            protein,fat,carbohydrate,sodium,calcium}:\n  猪柳麦满分,..."}
```

实测 35 个工具可用，`list-nutrition-foods` 返回 160 条营养数据。
