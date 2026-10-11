# ADR-020：集中度 lens 默认 OFF（concentration 改为 opt-in）

**日期**：2026-06-25
**状态**：accepted
**取代/延续**：ADR-013（trim-concentration-override）、ADR-019（移除 solvency 自动兜底，集中度只由 lens 控制）、ADR-017（config-via-API 提供运行时覆盖）

## Context

集中度（concentration）视角的隐含前提是：**用户把全部净资产都录进了 openInvest**，所以"单资产占持仓 X%"等于"单资产占身家 X%"。

实际上 openInvest 的持仓多是**自选 / watchlist**——用户只录了想跟踪的几个标的，没把所有钱写进来（例：用户只录了一个小额账户，主要净资产不在系统里）。在这个前提下，"持仓集中度 = 风险 → 建议减仓"对默认用户就是**错的**。

过去几轮一直在修集中度的**算法**让它"算得更对"：
- ADR-019 / #84：移除 solvency 自动兜底（"兜底足→集中度不算险"在 parse 层反转 CIO，prompt 不知情，自相矛盾）。
- #89：NaN 价不再污染总资产/集中度。

但这些都是在修一个**前提就错**的功能，只会不断冒新 bug。最新一例（2026-06-25）：某持仓的委员会凌晨跑时，另一只海外市场持仓（非 CNY 腿）无新鲜报价，按 #89 被剔出 `total_assets_cny` → 该持仓的集中度被动虚高（= 该持仓/(该持仓+现金)，缺报价的那只不在分母）→ 驱动了一个本不该有的大额 `TRIM`。

## Decision

**`core/config/tunable.py: concentration_lens_enabled` 默认 `True → False`。** 集中度从"默认开、人人得想办法关"改为 **opt-in**：

- **默认（False）**：不因持仓集中度建议减仓——`TRIM_REASON=concentration` 无条件 force-HOLD，Risk/CIO prompt 压掉超配规则。仍保留**波动 / 回撤 / 止损 / 估值 / 压力测试 / 现金流动性**风险维度。
- **想要的人**（把全部净资产录入系统、确实关心组合集中度）显式开启：`/api/config` 设 `verdict.concentration_lens_enabled=true`，或 env `INVEST_VERDICT_CONCENTRATION_LENS_ENABLED=true`。

既有的 3 层 disable 实现（`capabilities/committee/risk_officer.py` + `capabilities/committee/cio.py` prompt 软抑制 + `core/committee/cio_parse.py` Sanity 4 硬 force-HOLD）**不变**——只是默认值翻了。

## Consequences

- 默认用户不再收到"集中度超配 → 减仓"建议；不会再因 watchlist 被当净资产而误判。
- #89 的 NaN-leg 集中度误算对默认用户**不再有 verdict 影响**（lens off 时该数字不驱动任何决策）。它仅作为 opt-in 用户的已知边界保留——后续可单独修（缺价腿用 last close / 均价计入分母，而非整条剔除），但不再是反复打补丁的压力点。
- 行为变更：相关测试改为显式开 lens 才测 on-path；`test_concentration_lens_off_by_default_forces_hold` 守新默认。

## 修订（2026-10-11）：lens 关时压力测试用绝对金额，仍不给占比

插件实测（虚构用户：¥50,000 现金 + ¥10,000 基金，真实占比 16.7%）发现：lens 关时 `portfolio_summary_text` 不给该持仓的任何市值数字，而 Risk 模板要求填 `WORST_CASE_LOSS_PCT_AT_-20`（"该资产跌 20%，整体损失百分比"，本质是占比 × 20%）。模型只能自算，编出"约占总资产 1.7%"，CIO 照抄成"仓位仅占 1.7%"。

改为：

- `portfolio_summary_text` 两种 lens 都给该持仓的 **CNY 市值**和**现价再跌 10% / 20% / 35% 的损失金额**（确定性计算）；lens 关时**仍不渲染占比**。
- Risk 模板最坏情景字段改为 `WORST_CASE_LOSS_CNY_AT_-20`，照抄上述金额。
- 模板里只在 lens 开时成立的规则用 `<!-- lens:concentration -->` 包住（Risk 两轮的集中度关注项 / `CONCENTRATION_PCT` 字段 / `>60%` 规则 / 分母修正，CIO 规则 4），`capabilities.loader.apply_lens_blocks` 在 lens 关时整块删掉。实测只在前面加"忽略下方集中度规则"挡不住：给了市值后 Risk 照模板字段自算 16.7%、写"远低于 25-35% 上限"，CIO 引为"仓位仅 16.7%"。
- 确定性兜底：lens 关时 `debate` 把 Risk 输出里的 `CONCENTRATION_PCT` 行删掉再交给 CIO（`cio_parse._strip_concentration_if_lens_off`）。散文里的占比删不掉，靠 prompt。
- lens 关指令：Risk 不得提及、估算或换算占比，ONE_LINER 的建仓上限按子弹表述；CIO 不得提及、估算或引用占比（包括 Risk 报告里出现的）。
- 该腿汇率不可用时市值 / 集中度 / 压力测试都标"暂不可计算"——此前 lens 开会渲染伪造的 `集中度 0.0%`。
- Sanity 4（lens 关 + `TRIM_REASON=concentration` → force-HOLD）不变。

**为什么不改成"lens 关也渲染真实占比、只标注仅作背景"**（openInvest#356 初版）：本 ADR 的前提是用户录入的常是部分资产，占比不等于身家占比。该方案的插件实测里，65% 画像下 Risk 仍套用 `>60%` 规则写"偏高，优先分散"，CIO 写"降到 50% 以下"，裁决由 ACCUMULATE 变 HOLD——默认用户的加仓被一个本 ADR 认定无意义的数字压住；cron 路径还有 #89 的缺价腿分母问题，渲染出来的占比会虚高。绝对金额对部分录入的用户同样成立，不需要分母。
