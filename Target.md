聚焦 Extreme-Market Research Agent 的 Codex 实现流程

# Extreme-Market Research Agent

研究目标不是寻找一个适用于全市场的统一 Extreme-Market 模型，而是：

$$ \boxed{ \text{对每个期货品种独立研究其 Extreme Market} } $$

整个研究只回答三个递进问题：

$$ \boxed{ \text{Q1 Extreme-Market Database} \rightarrow \text{Q2 Feature \& Repeatability Structure} \rightarrow \text{Q3 Timing Operator} } $$
## Q1 — Extreme-Market Database
研究问题

- 这个期货品种历史上发生过哪些真正的大涨、大跌和极端行情？

第一阶段先不研究交易规则，而是把历史上的 Extreme-Market Episodes 系统整理出来。

对每个品种建立：

$$ \mathcal D_i^E= \{E_{i,1},E_{i,2},\ldots,E_{i,K_i}\} $$

一个 Episode 是完整的一段极端行情，不能把连续十几天的极端状态算成十几个样本。

Codex负责自动完成：

```

读取该品种全部历史数据
        ↓
扫描历史大涨 / 大跌阶段
        ↓
合并属于同一轮行情的连续触发
        ↓
生成候选 Extreme Episodes
        ↓
自动绘制每个 Episode 完整价格路径
        ↓
学生人工审核
        ↓
建立最终 Extreme-Market Database

```

数据库至少保存：
```
品种
Episode ID
Extreme-Up / Extreme-Down

行情开始时间
加速时间
最高点 / 最低点
行情结束时间

1/5/20/60日收益
整个Episode累计涨跌幅
最大上涨 / 最大下跌
波动率
成交量
持仓量

期限结构
基差/现货
库存
产业链基本面
相关宏观变量

完整价格路径
```
这里有一条重要原则：

- Q1 是历史事实数据库，可以利用事后完整行情确认“这是不是一次真正的 Extreme Market”。

不要强迫数据库标签本身必须实时可交易。

# Q2 — Feature & Repeatability Structure
研究问题

- 这些历史 Extreme Markets 中，有哪些能够在不同事件中反复出现的可观察特征和路径结构？

这是整个研究的核心。

有了数据库以后，Codex 对同一品种的所有 Episodes 进行对齐和比较，例如：

$$ E_{i,1},E_{i,2},...,E_{i,K} $$

研究两类结构。

① 可识别 Feature Structure

允许使用的信息不局限于技术指标，可以包括：

$$ \text{Price} + \text{Volume} + \text{Open Interest} + \text{Term Structure} + \text{Fundamentals} + \text{Macro} $$

例如：

- 不同周期收益与价格加速度；
- 历史价格位置；
- 成交量与持仓变化；
- 波动率；
- 期限结构；
- 现货与基差；
- 库存；
- 开工率、产业利润；
- 供需数据；
- 股指估值、市场宽度、流动性；
- 国债收益率曲线、宏观利率状态等。

不同品种可以使用完全不同的特征。

原油、鸡蛋、白银、沪深300、十年国债，没有必要使用统一 Feature Set。

② Repeatability / Path Structure

更重要的是研究：

Extreme Market 本身的价格路径有没有重复出现的阶段结构？

例如可能发现：

$$ \text{Acceleration} \rightarrow \text{Extreme Trend} \rightarrow \text{High-Level Consolidation} \rightarrow \text{Breakdown} $$

也可能是：

$$ \text{Crash} \rightarrow \text{Capitulation} \rightarrow \text{Stabilization} \rightarrow \text{Recovery} $$

或者：

$$ \text{Extreme} \rightarrow \text{Continuation} \rightarrow \text{More Extreme} $$

Codex需要做的是：
```
Extreme-Market Database
        ↓
Episode 对齐
        ↓
提取价格/量价/基本面/宏观特征
        ↓
比较不同 Episode
        ↓
寻找重复出现的状态和路径
        ↓
排除只解释一个事件的特征
        ↓
形成该品种的
Extreme-Market Structure Report
```
最终这一阶段不是得到一个“预测模型”，而应该得到类似：

该品种的 Extreme Market 通常具有哪几种重复结构；哪些状态能够在历史多个独立 Episode 中重复观察到。

特别注意：

- Q2 中如果某个 Feature 以后准备作为实时识别变量，那么必须保证当时可观测，不能使用未来信息。

# Q3 — Timing Operator
研究问题

- 基于 Q2 找到的可重复 Extreme-Market Structure，应该如何在 Long / Flat / Short 之间切换？

形式上：

$$ T_i^E(X_{0:t},F_{0:t}) \rightarrow \{-1,0,+1\} $$

其中：

$$ +1=\text{Long},\qquad 0=\text{Flat},\qquad -1=\text{Short}. $$

这里不预设 Extreme-Up 就必须做空，也不预设 Extreme-Down 就必须做多。

例如一次暴涨行情完全可能：

$$ +1\rightarrow0\rightarrow-1 $$

即：

先继续参与上涨 → 高位退出 → 后续再参与下跌。

Codex可以根据 Q2 的结构，自主实现和测试：
```
技术指标
多周期规则
价格路径
几何形态
基本面状态
多变量规则
机器学习 / AI
```
但最终必须形成一个明确、可执行、无未来信息的 Long / Flat / Short Operator。

# Codex 的完整自动研究循环
python环境："D:\Anaconda3\envs\ExtremeMarket"

建议一个品种一个 Codex Task，共享统一代码库，但各品种拥有自己的研究目录：
```
ExtremeMarketAgent/

├── AGENTS.md
├── data/
│
├── src/
│   ├── database/
│   ├── feature_analysis/
│   ├── path_analysis/
│   ├── timing/
│   └── backtest/
│
├── instruments/
│   ├── 原油/
│   ├── 白银/
│   ├── 碳酸锂/
│   └── ...
│
└── reports/
```
每个品种固定执行：
```
                品种 i
                  │
                  ▼
      Q1 Extreme-Market Database
                  │
                  ▼
     Historical Extreme Episodes
                  │
                  ▼
 Q2 Feature & Repeatability Structure
                  │
          ┌───────┴───────┐
          ↓               ↓
 Observable Features   Path Structure
          └───────┬───────┘
                  ▼
        Repeatable Structure
                  │
                  ▼
       Q3 Timing Operator
                  │
                  ▼
        Long / Flat / Short
                  │
                  ▼
          Episode Backtest
                  │
                  ▼
           Return Process
```
# 给 Codex 的核心研究规则

AGENTS.md 最重要的是写清楚下面这些规则：
```
Objective:
Build an instrument-specific Extreme-Market research system.

The project contains exactly three research stages:

1. Extreme-Market Database
2. Feature & Repeatability Structure
3. Timing Operator

Each futures instrument must be researched independently.

Do NOT require one Extreme-Market definition,
one feature set, or one timing operator to generalize
across all futures instruments.

Price, volume, open interest, term structure,
fundamental information, industry data and
relevant macroeconomic information may all be used.

Stage 1 may use ex-post information to construct
and verify historical Extreme-Market Episodes.

Stage 2 and Stage 3 must explicitly distinguish
historical labels from information observable in real time.

All executable rules must contain no future information.

Preserve all failed experiments.

Do not hide negative results.

Do not optimize only for total return or Sharpe ratio.

The final conclusions must be supported by
multiple independent Extreme-Market Episodes
whenever sufficient historical episodes exist.
```
# 每个品种最终交付

学生最后不应该只交一张收益曲线，而应该交三个部分：
```
01_Extreme_Market_Database/
    extreme_episodes.csv
    episode_charts/

02_Repeatability_Structure/
    feature_analysis.csv
    path_analysis/
    repeatability_report.pdf

03_Timing_Operator/
    operator_definition.md
    code/
    episode_backtests.csv
    equity_curve.png
    validation_report.pdf
```
这样以后所有品种最后可以组成一个：


# 全期货品种

按截至 2026年10月 已上市的常规期货品种口径，我建议按产业知识体系划成三组，共 88 个品种。上期所及上期能源目前有25个期货品种；郑商所当前品种体系包括27个期货品种；广期所目前上市铂、钯、多晶硅、碳酸锂、工业硅；中金所现有四个股指期货和四个国债期货。大商所在既有21个品种基础上又上市原木和纯苯。

## 农业、软商品与林纸（29个）

黄大豆1号、黄大豆2号、玉米、玉米淀粉、豆粕、豆油、棕榈油、鸡蛋、粳米、生猪、纤维板、胶合板、原木、普通小麦、优质强筋小麦、棉花、白糖、菜籽油、早籼稻、油菜籽、菜籽粕、粳稻、晚籼稻、棉纱、苹果、红枣、花生、纸浆、胶版印刷纸。

这一组重点可以收集天气、季节性、库存、产量、种植/养殖周期、进口、基差、加工利润等数据，但每个品种独立研究。
