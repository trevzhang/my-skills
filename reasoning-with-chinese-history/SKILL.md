---
name: reasoning-with-chinese-history
description: Use when a user wants to analyze a real-life choice, dilemma, tradeoff, relationship, career move, alliance, retreat, risk, or strategy through verifiable cases from 史记 or 资治通鉴.
---

# 史鉴人生抉择推演

把现实问题与古代案例的“决策结构”比较，而不是用名句、人物标签或结局作类比。语料为可追溯的简体转写本；历史只提供反事实问题和风险镜鉴，不替用户决定。

## 必须执行

1. 确认本技能目录的 `corpus/manifest.json` 存在；`corpus/index/search.sqlite3` 缺失时，在技能目录运行 `python3 scripts/build_index.py --text-root corpus/text --output-dir corpus/index`。语料缺失或构建失败时停止，不凭记忆补案例。
2. 完整阅读 [references/analysis-framework.md](references/analysis-framework.md) 和 [references/output-contract.md](references/output-contract.md)。涉及语料来源、版本或许可时再读 [references/source-policy.md](references/source-policy.md)。
3. 先建立现实“决策卡”。仅当一个缺失事实可能反转分析时，问一个关键问题；否则标明假设继续。
4. 分别围绕人物处境、约束、选项、激励、权力差、可逆性和尾部风险生成检索词。在技能目录运行：

```bash
python3 scripts/search_corpus.py \
  '检索词' --limit 20 --context 2 --json
```

5. 阅读候选段落及上下文，选 2 至 4 个结构相似案例；条件允许时包含结果相反或机制不同的反例。宁缺毋滥。
6. 每条直接引文都在简体转写文件中逐字验证：

```bash
python3 scripts/verify_citations.py \
  --source-file 'shiji/文件.txt' \
  --quote '原文' --start-line 起始行 --end-line 结束行 --json
```

7. 验证失败的文字不得作为原文或证据。按输出契约完成推演，并明确时代差异、证据缺口、隐性代价和止损条件。

## 证据边界

- 严格标注 `史料事实`、`现代释义`、`分析解释`、`推断`。
- 区分事件正文、`臣光曰`、后人注文和篇章标题；不要把评论或注文冒充当事人信息。
- 按当时可知信息评价选择，不因后来成败倒推判断质量。
- 所有引文注明“简体转写本”，不得声称保留了上游繁体字形。
- 不编造动机、未选路线或名句；无法核验时明确说未找到可靠案例。
- 医疗、法律、投资、人身安全等高风险事项只提供思考框架，并建议咨询相应专业人士。
