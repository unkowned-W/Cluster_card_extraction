# Prompt patterns and initial evaluation

Use these as **user-facing test prompts** or adapt them to the task. The instruction in `SKILL.md` remains authoritative; prompts do not themselves supply chemical facts.

## Grounded lookup

> 请基于本目录 cards 查找 DOI `{doi}` 中化合物 `{label}` 的合成条件、核数与结构依据。逐项给出 JSON 路径及字段，区分正文/SI 提取与 CIF 推导；缺失条件写“卡片未给出”，不要补全。

## Matched structure audit

> 对 CCDC `{ccdc}` / refcode `{refcode}`，用合成卡、结构卡和 `data/process_csv/project_card_ledger.csv` 核对是否属于同一个具体化合物。说明核数的来源、可用的原子/键数据、候选结构模块的证据等级，以及不能从该 CIF 卡推出的结论。

## Comparative reasoning

> 在本地卡片里选出符合 `{elements_or_motif}` 且总金属核数至少 `{n}` 的实例，比较配体/模板、反应条件、结构描述和性能。每条结论附化合物级来源；解释筛选范围与不可直接比较的测量条件。综述只用于带限定条件的背景解释。

## Hypothesis, not recipe

> 我希望探索 `{target}`。请从卡片寻找最相近的先例，提出 2–3 个有明确证据边界的设计假设、可能失败模式与需要核验的原始文献/CIF 信息。不要把相关性说成因果，也不要保证产物或性能。

## Contradiction / abstention

> 对 `{claim}` 做证据审计：哪些卡片直接支持、哪些只是综述归纳或结构算法提示、哪些与之冲突或缺少必要字段？若无法证实，请明确弃答并给出最小核验清单。

## First-pass evaluation of Cluster_agent

1. Freeze a small test set of questions *before* looking at model answers: identifier lookup; multi-compound DOI disambiguation; missing CIF match; missing atom/bond graph; review scope transfer; cross-card comparison; unsupported synthetic prediction. Include both answerable and deliberately unanswerable items. Avoid putting expected answers inside the query.
2. Run the same questions against a baseline model without this skill and with this skill plus cards, holding model and other settings fixed. Record retrieved paths, response, time, and whether external browsing was used. If browsing differs, do not attribute gains solely to cards.
3. Independently verify sampled assertions against the actual card fields and, where feasible, original article/SI/CIF. Score at the **claim** level: correct compound linkage, synthesis fidelity, structure interpretation, scope-aware review use, citation traceability, calibrated abstention; note hallucinations and overconfident statements separately. Do not score prose fluency as domain knowledge.
4. Report counts/denominators and representative failures; distinguish improved retrieval/grounding from genuine generalization. This is an initial check, not a benchmark proving novel chemistry or experimental reproducibility.

## Ledger-first ligand and analog retrieval

> ???? `{ligand}` ??? Gd ???????????? `--element Gd --reagent` ?????????????????????????? `compound_key` ?? `--similar-to`????????/???/?????????????????????????????????????????????????????

## Missing crystallographic evidence

> ?? `{compound_key}` ?????????? `structure_availability`??? CIF?????? card ??????????????????????????????? CIF ????????/??/???????? CCDC ???????????????? CIF?

