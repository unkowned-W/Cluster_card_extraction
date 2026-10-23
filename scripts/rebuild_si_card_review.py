"""Rebuild a human SI-gap audit from the current ledger and existing cards."""
import csv
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / 'data' / 'process_csv' / 'si_required.csv'
OUT = ROOT / 'data' / 'card_review.md'
OLD = OUT.read_text(encoding='utf-8') if OUT.exists() else ''
old_decisions = {}
for line in OLD.splitlines():
    match = re.match(r'^\| \d+ \| `([^`]+)` \|', line)
    if match:
        decision = line.rstrip('|').split('|')[-1].strip()
        if decision in {'保留', '复核', '可考虑剔除'}:
            old_decisions[match.group(1).lower()] = decision

with LEDGER.open(encoding='utf-8-sig', newline='') as handle:
    ledger = list(csv.DictReader(handle))
folders = [ROOT / 'documents' / 'md', ROOT / 'data' / 'si_review_pending' / 'si_md']
files = [[p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == '.md' and p.stat().st_size > 0] if folder.is_dir() else [] for folder in folders]

def safe(text):
    return str(text or '').replace('|', '∣').replace('\n', ' ').replace('\r', ' ').strip()

def stem(doi):
    return re.sub(r'[^\w.\-]+', '_', doi.lower(), flags=re.ASCII).strip('._')

def gap_details(card):
    result = []
    for i, c in enumerate(card['list_of_rare_earth_compounds'], 1):
        syn = c['synthesis']
        if syn.get('main_text_has_explicit_synthesis') or syn.get('si_used'):
            continue
        reagents = syn.get('reagents') or []
        bits = []
        if not any(str(r.get('name') or '').strip() for r in reagents):
            bits.append('试剂名')
        if not any(re.search(r'\d', str(r.get('amount') or '')) for r in reagents):
            bits.append('用量')
        if not str(syn.get('procedure') or '').strip():
            bits.append('步骤')
        if not bits:
            bits = ['合成来源/标志']
        result.append((i, c, bits))
    return result

rows = []
reason_counts = Counter()
all_compounds = 0
property_compounds = 0
ccdc_compounds = 0
si_state_counts = Counter()
for item in ledger:
    doi = item['doi']
    card_path = Path(item['card_path'])
    card = json.loads(card_path.read_text(encoding='utf-8-sig'))
    compounds = card['list_of_rare_earth_compounds']
    details = gap_details(card)
    # The validator's reason field is the authoritative exact wording; calculate only for cross-check.
    exact_reasons = item['reason'].split('; ')
    if len(exact_reasons) != len(details):
        raise ValueError(f'Ledger/card mismatch: {doi}: {len(exact_reasons)} vs {len(details)}')
    counts = Counter(bit for _, _, bits in details for bit in bits)
    reason_counts.update(counts)
    all_compounds += len(compounds)
    ccdc = sum(bool(c.get('ccdc_numbers')) for c in compounds)
    prop = sum(bool(c.get('properties', {}).get('reported')) and c.get('properties', {}).get('property_type') in ('magnetic','optical','both') for c in compounds)
    ccdc_compounds += ccdc
    property_compounds += prop
    prefix = stem(doi) + '_si'
    regular, pending = [[p for p in group if p.name.lower().startswith(prefix)] for group in files]
    state = ('常规MD' if regular else '') + ('+待审MD' if pending and regular else '待审MD' if pending else '') or '未见MD'
    si_state_counts[state] += 1
    year = '—'
    meta_path = ROOT / 'documents' / 'metadata' / f'{stem(doi)}.json'
    if meta_path.exists():
        try:
            year = str(json.loads(meta_path.read_text(encoding='utf-8-sig')).get('crossref', {}).get('year') or '—')
        except (ValueError, OSError):
            pass
    rows.append(dict(doi=doi, card=card, compounds=compounds, details=details, exact=exact_reasons,
                     counts=counts, ccdc=ccdc, prop=prop, regular=regular, pending=pending,
                     si_state=state, year=year, decision=old_decisions.get(doi.lower(), '新增·待判')))

lines = [
    '# SI 合成缺口与 card 人工审阅（工作台账快照）', '',
    f'数据快照：{date.today().isoformat()}；来源为 `data/process_csv/si_required.csv`、对应 `data/extracted_cards/*.json`、本地元数据缓存及 SI Markdown 文件清单。'
    '主题按 **card 标题**概括；并未逐篇阅读 PDF/SI 正文。缺本地元数据缓存不作为 card 缺陷。**未修改或删除 card。**', '',
    f'当前 ledger **{len(rows)} 篇**，card 共 **{all_compounds} 个化合物**，其中 **{sum(len(r["details"]) for r in rows)} 个**仍被标记合成缺口。'
    f'带 CCDC 编号的 card 化合物 {ccdc_compounds} 个，标记磁/光性质的 {property_compounds} 个。'
    '历史初筛决定仅保留作人工参考，不代表当前结论。', '',
    '## 如何解读“缺失原因”', '',
    '| 当前 card/校验器观察到的缺项 | 涉及化合物数 | 人工核查要点 |',
    '|---|---:|---|',
    f'| 试剂用量 | {reason_counts["用量"]} | 区分原文/SI 真未写用量、写在表格/图片中未提取、以及仅引用了文献通法。 |',
    f'| 试剂名称 | {reason_counts["试剂名"]} | 检查是否只写“按类似方法”而没有明确该化合物所用原料，或名称在图/表中。 |',
    f'| 制备步骤 | {reason_counts["步骤"]} | 检查是否仅有晶体数据/表征，或者合成步骤位于 SI/其他文献。 |',
    f'| 合成来源/标志 | {reason_counts["合成来源/标志"]} | card 已有试剂、数字和过程，但 `main_text_has_explicit_synthesis=false` 且 `si_used=false`；核对其来源标志或共用/类比步骤，不能等同“没有合成”。 |',
    '',
    '**统计项可以重叠**：一个化合物可同时缺试剂名、用量和步骤。`x/y` 是 ledger 中缺口化合物数 / 该篇 card 的化合物数，'
    '不是 card 完整度百分比。尤其“缺明确原文合成”是来源标志/校验规则问题，不代表文本一定没有数字步骤。'
    '已经 `si_used=true` 且达到校验条件的化合物不在此 ledger 缺口内。', '',
    'SI MD 可用性（按文件名匹配、仅检查非空，**不代表内容有合成信息**）：' + '；'.join(f'{k} {v} 篇' for k,v in si_state_counts.items()) + '。', '',
    '## 全部文献总览', '',
    '| # | DOI | 年 | card 标题（研究主题） | 合成缺口 | 具体缺项（化合物数） | CCDC | 磁/光 | SI MD | 历史初筛 |',
    '|---:|---|---:|---|---:|---|---:|---:|---|---|'
]
for i,r in enumerate(rows,1):
    c = r['counts']
    shorthand = '、'.join(f'{key}{c[key]}' for key in ('用量','试剂名','步骤','合成来源/标志') if c[key])
    lines.append(f'| {i} | `{safe(r["doi"])}` | {r["year"]} | {safe(r["card"].get("title"))} | '
                 f'{len(r["details"])}/{len(r["compounds"])} | {shorthand} | {r["ccdc"]} | {r["prop"]} | {r["si_state"]} | {r["decision"]} |')

lines += ['', '## 逐篇核查线索', '',
          '下列内容逐个列出 **当前 ledger 仍失败**的化合物；“记录线索”仅取已有 card 合成过程开头，'
          '用于帮助定位，不是原文引述，也不证明 SI 无信息。空白记为「card 未记录」。'
          '标签可能重复或为空，因此附 card 中的 1-based 序号。`data/process_csv/si_required.csv` 中的具体英文 reason 与此处按 card 实时计算的缺项一一对应。', '']
for r in rows:
    lines.append(f'### `{safe(r["doi"])}` — {safe(r["card"].get("title"))}')
    lines.append(f'缺口 {len(r["details"])}/{len(r["compounds"])}；SI MD：{r["si_state"]}。')
    if r['regular'] or r['pending']:
        sources = [f'`{p.relative_to(ROOT)}`' for p in [*r['regular'], *r['pending']]]
        lines.append('SI 文件：' + '、'.join(sources) + '。')
    lines.append('')
    lines.append('| card 序号/标签 | ledger 具体原因 | card 中的记录线索 | 人工核查重点 |')
    lines.append('|---|---|---|---|')
    for (idx,c,bits), reason in zip(r['details'],r['exact']):
        procedure = re.sub(r'\s+', ' ', str(c['synthesis'].get('procedure') or '')).strip()
        snippet = procedure[:115] + ('…' if len(procedure)>115 else '') if procedure else 'card 未记录'
        if '合成来源/标志' in bits:
            priority = '核对步骤来源于原文还是 SI；检查类比步骤与 `si_used` 标志'
        elif '步骤' in bits:
            priority = '查 SI/原文实验节是否有独立或共用制备步骤'
        elif '试剂名' in bits:
            priority = '核对原料名及数值是否在 SI 表格/图像或共用步骤'
        else:
            priority = '核对用量是否在 SI 表格/图像、原文或被引用的通法'
        label = c.get('compound_label') or c.get('formula') or c.get('compound_name') or '(无标签)'
        lines.append(f'| {idx}: {safe(label)} | {safe(reason.partition(": ")[2] or reason)} | {safe(snippet)} | {priority} |')
    lines.append('')
lines += ['## 优先人工复核的特殊情况', '',
          '- `10.1002/anie.198910331`：历史审阅发现本地 Crossref 与 card 标题不同，优先核对 DOI 与 card 对应关系。',
          '- `10.1071/ch21336`：历史审阅发现元数据/card 标题中的 `I3` / `I12` 化学式差异，需核对原文。',
          '- 先核查「合成来源/标志」与“已在 card 记录数值步骤”但仍在 ledger 的条目，避免把标志/归属错误误判成无合成。',
          '- SI MD 的存在只代表文件可读，不保证对应产物的用量/合成被写出；不要仅凭此报告删除 card。', '']
intro = ['# Card 缺陷与人工审查', '', '以下 SI 工作台账段落是基于现有 card 的合成缺口线索；末尾完整性审计段需有 structures.csv 才能重新生成。均非论文/SI 原文人工复核。', '', '---', '']
if '<!-- integrity-audit:start -->' in OLD and '<!-- integrity-audit:end -->' in OLD:
    lines.extend(['', OLD[OLD.index('<!-- integrity-audit:start -->'):].strip(), ''])
OUT.write_text('\n'.join(intro + lines), encoding='utf-8')
print(f'Wrote {OUT}: {len(rows)} papers, {sum(len(r["details"]) for r in rows)} gaps, {len(lines)} lines')
print('Missing-field counts:', dict(reason_counts), 'SI:', dict(si_state_counts))
