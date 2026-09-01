#!/usr/bin/env python3
"""u4 详情页全量解析：从 data/u4_pages_raw.json 提取
   catalysts / positioning(定位核验·四层筛子) / upgrade_downgrade / valuation / risk
   输出 data/u4_migrate.json：{ code: {catalysts:[...], modules:[{key,title,blocks}] } }
   解析失败自动降级：整段原文作为 text block（内容不丢）。
"""
import json, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------- 工具 ----------

def split_sections(text, markers):
    """按 markers 顺序切出各 section 文本。返回 {marker: seg}，marker 不在则缺。"""
    pos = []
    for m in markers:
        i = text.find(m)
        if i >= 0:
            pos.append((i, m))
    pos.sort()
    out = {}
    for idx, (i, m) in enumerate(pos):
        end = pos[idx + 1][0] if idx + 1 < len(pos) else len(text)
        # 截断尾部导航（"返回列表"/"基础行情数据由" 在最后，通常无碍）
        out[m] = text[i:end]
    return out

def lines(seg):
    return [ln.strip() for ln in seg.split('\n') if ln.strip()]

def table_rows(seg):
    """从文本段提取 tab 表格：返回 (headers, rows) 或 None。"""
    rows = []
    for ln in lines(seg):
        if '\t' in ln:
            rows.append([c.strip() for c in ln.split('\t')])
    if not rows:
        return None
    # 第一行作 header（含'指标'/'区间'/'双条件'/'信号' 等）
    headers = rows[0]
    data = rows[1:]
    # 过滤全空行 / 全 '—' 行
    data = [r for r in data if any(c and c != '—' for c in r)]
    return headers, data

def drop_tail_markers(seg):
    """去掉段尾的 '📡 ...' 来源标注行"""
    out = []
    for ln in lines(seg):
        if ln.startswith('📡') or ln.startswith('依据:') or ln.startswith('📡 数据来源'):
            continue
        out.append(ln)
    return out

# ---------- 催化节点 ----------

DUE_RE = re.compile(r'^20\d{2}([H+\-年]|\s|$|\d)')

def parse_catalysts(seg):
    body = drop_tail_markers(seg)
    entries = []
    cur = None
    for ln in body:
        if DUE_RE.match(ln):
            cur = {'due': ln, 'name': '', 'note': ''}
            entries.append(cur)
        elif cur is not None:
            if not cur['name']:
                cur['name'] = ln
            elif not cur['note']:
                cur['note'] = ln
            else:
                cur['note'] += ' ' + ln
        # cur 为 None 且非日期：段首标题行，忽略
    return entries if entries else None

# ---------- 定位核验（三种形式） ----------

def parse_poscheck_frontier(seg):
    """前言卡位：双条件表 + 判定三问 + PGT + 仓位含义"""
    blocks = []
    bl = lines(seg)
    # 首行 '🔭 前瞻卡位' + 等级 + 结论
    verdict_lines = [ln for ln in bl if ln.startswith('——')]
    grade_line = next((ln for ln in bl if ln.startswith('🔭 前瞻卡位')), '')
    level = re.search(r'([ABC] 级)', seg)
    info_text = (grade_line + (f' {level.group(1)}' if level else '')).strip()
    if verdict_lines:
        info_text += ' ' + verdict_lines[0]
    # 后续非结构行拼进结论（到'双条件'前）
    for ln in bl:
        if ln.startswith('双条件') or ln.startswith('🔍 判定三问') or ln.startswith('P ·') or ln.startswith('G ·') or ln.startswith('T ·') or ln.startswith('🎯 仓位'):
            break
        if ln.startswith('——') or ln.startswith('🔭 前瞻卡位') or not ln:
            continue
        info_text += ' ' + ln
    if info_text and info_text != grade_line:
        blocks.append({'type': 'callout', 'tone': 'info', 'text': info_text})

    # 双条件表
    cond_rows = []
    for ln in bl:
        if ln.startswith('双条件'):
            m = re.match(r'(双条件 [①②] .+?)\t', ln)
            if m and '\t' in ln:
                k, v = ln.split('\t', 1)
                cond_rows.append([k.strip(), v.strip()])
    if cond_rows:
        blocks.append({'type': 'table', 'headers': ['双条件', '验证'], 'rows': cond_rows})

    # 判定三问
    for i, ln in enumerate(bl):
        if ln.startswith('🔍 判定三问'):
            nxt = bl[i + 1] if i + 1 < len(bl) else ''
            if nxt and not nxt.startswith(('P ·', 'G ·', 'T ·')):
                blocks.append({'type': 'text', 'text': ln + '\n' + nxt})
            else:
                blocks.append({'type': 'title', 'text': ln})

    # PGT 表
    pgt_rows = []
    for ln in bl:
        if re.match(r'^[PGT] · ', ln):
            cells = [c.strip() for c in ln.split('\t')]
            k = cells[0]
            if len(cells) >= 3:
                pgt_rows.append([k, cells[1], ' '.join(cells[2:])])
            elif len(cells) == 2:
                rest = cells[1]
                row = None
                # 模式1：短判定词 'P 高' 后直接接大写英文/括号起始的依据
                m = re.match(r'^([PGT] [高中低大])(?=[A-Za-z（])', rest)
                if m:
                    row = [k, m.group(1), rest[m.end():].strip()]
                else:
                    # 模式2：判定词含括弧（如 'T 1-2 年（AI 电感）/ 3 年+（SST）'）至 ）+大写英文
                    m = re.match(r'^(.+?）)(?=[A-Z])', rest)
                    if m and len(m.group(1)) <= 40:
                        row = [k, m.group(1), rest[m.end():].strip()]
                if row is None:
                    row = [k, rest, '']
                pgt_rows.append(row)
            else:
                pgt_rows.append([ln, '', ''])
    if pgt_rows:
        # 去掉空 detail 列不必要：保留 3 列（detail 空则显示空）
        blocks.append({'type': 'table', 'headers': ['P/G/T', '判定', '依据'], 'rows': pgt_rows})

    # 仓位含义
    for i, ln in enumerate(bl):
        if ln.startswith('🎯 仓位含义'):
            txt = ln
            nxt = bl[i + 1] if i + 1 < len(bl) else ''
            if nxt and not nxt.startswith(('📡', '🗓', '🔭', '💰', '⚠️')):
                txt += '\n' + nxt
            blocks.append({'type': 'callout', 'tone': 'good', 'text': txt})
    return blocks if blocks else None

def parse_poscheck_core(seg):
    """四层筛子评估（产业主脉）：①..④ 四段 + 综合判定 + 产业定位说明"""
    blocks = []
    bl = lines(seg)
    # 四层筛子：①②③④ 段
    sieves = []
    cur = None
    for ln in bl:
        if re.match(r'^[①②③④] ', ln):
            if cur: sieves.append(cur)
            cur = [ln, '']
        elif cur is not None and not ln.startswith(('综合判定', '产业定位', '📡')):
            cur[1] += ln
    if cur: sieves.append(cur)
    if sieves:
        rows = [[s[0], s[1]] for s in sieves]
        blocks.append({'type': 'table', 'headers': ['筛子', '结论'], 'rows': rows})
    # 综合判定 + 产业定位说明
    for i, ln in enumerate(bl):
        if ln.startswith('综合判定') or ln.startswith('产业定位'):
            txt = ln
            # 后续段落（到下一个 marker）
            j = i + 1
            while j < len(bl) and not bl[j].startswith(('综合判定', '产业定位', '📡', '四层', '💰', '⚠️', '关键财务')):
                txt += '\n' + bl[j]
                j += 1
            if j == i + 1:  # 无后续行时不重复
                pass
            blocks.append({'type': 'text', 'text': txt})
    return blocks if blocks else None

def parse_poscheck_swing(seg):
    """技术短线：被刷掉理由 + 三条判定 + 升级观察"""
    blocks = []
    bl = lines(seg)
    # 首行 '⚡ 技术短线 —— ...'
    first = bl[0] if bl else ''
    if '技术短线' in first or '题材' in first:
        blocks.append({'type': 'callout', 'tone': 'info', 'text': first})
    # 被刷掉理由
    for i, ln in enumerate(bl):
        if '被刷掉理由' in ln:
            nxt = bl[i + 1] if i + 1 < len(bl) else ''
            if nxt:
                blocks.append({'type': 'callout', 'tone': 'warn', 'text': '🚫 ' + ln + '\n' + nxt})
    # 三条判定（tab 表格）：行首特征 '产业是否已验证' / '公司是否卡住位置' / '四层筛子结果'
    tr = table_rows(seg)
    if tr:
        h, rows = tr
        if h and (h[0].startswith('产业是否') or h[0].startswith('公司是否') or h[0].startswith('四层筛子') or '是否' in h[0]):
            blocks.append({'type': 'table', 'headers': h, 'rows': rows})
    # 升级观察
    for i, ln in enumerate(bl):
        if ln.startswith('🔭 升级观察'):
            nxt = bl[i + 1] if i + 1 < len(bl) else ''
            txt = ln + ('\n' + nxt if nxt else '')
            blocks.append({'type': 'text', 'text': txt})
    return blocks if blocks else None

def parse_poscheck(seg):
    # 按特征词判别，顺序重要：
    # 1) swing：段含"被刷掉理由"或标题"只能技术短线"
    if '被刷掉理由' in seg or '只能技术短线' in seg:
        return parse_poscheck_swing(seg)
    # 2) core：四层筛子评估（排除 swing 的"四层筛子结果"——已被上分支拦截）
    if '四层筛子' in seg:
        return parse_poscheck_core(seg)
    # 3) frontier / 其他
    return parse_poscheck_frontier(seg)

# ---------- 升级 / 降级信号 ----------

def parse_updown(seg):
    blocks = []
    bl = drop_tail_markers(seg)
    group = None
    rows_up, rows_down = [], []
    for ln in bl:
        if ln.startswith('⬆️'):
            group = 'up'
            blocks.append({'type': 'title', 'text': ln})
        elif ln.startswith('⬇️'):
            group = 'down'
            blocks.append({'type': 'title', 'text': ln})
        elif group and ln and not ln.startswith(('📡', '判定依据')):
            # 信号：阈值（可能带状态 emoji）
            if '：' in ln:
                k, v = ln.split('：', 1)
                (rows_up if group == 'up' else rows_down).append([k.strip(), v.strip()])
            elif '\t' in ln:
                parts = [c.strip() for c in ln.split('\t')]
                if len(parts) == 2:
                    (rows_up if group == 'up' else rows_down).append(parts)
                elif len(parts) >= 3:
                    (rows_up if group == 'up' else rows_down).append([parts[0], parts[1], ' '.join(parts[2:])])
    if rows_up:
        blocks.append({'type': 'table', 'headers': ['信号', '阈值'], 'rows': rows_up})
    if rows_down:
        blocks.append({'type': 'table', 'headers': ['信号', '阈值'], 'rows': rows_down})
    return blocks if blocks else None

# ---------- 估值分析 ----------

def parse_valuation(seg):
    blocks = []
    bl = lines(seg)
    # 结论 callout
    for ln in bl:
        if ln.startswith('🎯 结论'):
            blocks.append({'type': 'callout', 'tone': 'good', 'text': ln})
            break
    # 当前位置 / 方法
    cur_txt = []
    for ln in bl:
        if ln.startswith(('当前估值位置', '估值方法')):
            cur_txt.append(ln)
    if cur_txt:
        blocks.append({'type': 'text', 'text': '\n'.join(cur_txt)})
    # 子标题 + 正文 + 表格：顺序扫描（容忍 🔍/🔭 等 emoji 差异）
    sub = None  # 当前子标题
    text_buf = []
    tables = []
    for ln in bl:
        if '估值跟踪变量' in ln:
            sub = 'track'
            blocks.append({'type': 'title', 'text': ln})
            continue
        if '合理区间三档' in ln:
            sub = 'zones'
            blocks.append({'type': 'title', 'text': ln})
            continue
        if '合理 TTM 依据' in ln:
            sub = 'ttm'
            blocks.append({'type': 'title', 'text': ln})
            continue
        if '估值锚定' in ln:
            sub = 'anchor'
            blocks.append({'type': 'title', 'text': ln})
            continue
        if sub is None and not ln.startswith(('🎯', '当前估值位置', '估值方法')):
            text_buf.append(ln)
        elif sub == 'ttm' and '\t' not in ln:
            text_buf.append(ln)
    # 合理 TTM 依据正文（子标题后非表格行）
    # 提取 ttm 正文
    ttm_lines = []
    for i, ln in enumerate(bl):
        if '合理 TTM 依据' in ln:
            j = i + 1
            while j < len(bl) and not any(k in bl[j] for k in ('估值锚定', '合理区间', '估值跟踪', '🎯')) and '\t' not in bl[j]:
                ttm_lines.append(bl[j]); j += 1
    if ttm_lines:
        blocks.append({'type': 'text', 'text': '\n'.join(ttm_lines)})
    # 锚定表 / 区间表：整段提取 tab 表格
    tr = table_rows(seg)
    if tr:
        h, rows = tr
        blocks.append({'type': 'table', 'headers': h, 'rows': rows})
    # 跟踪变量
    for i, ln in enumerate(bl):
        if '估值跟踪变量' in ln:
            j = i + 1
            track = []
            while j < len(bl) and not any(k in bl[j] for k in ('📡', '⚠️', '🗓', '🔭', '💰', '关键财务', '估值分析')):
                track.append(bl[j]); j += 1
            if track:
                blocks.append({'type': 'text', 'text': '\n'.join(track)})
    # 兜底：正文缓冲
    if text_buf:
        blocks.append({'type': 'text', 'text': '\n'.join(text_buf)})
    return blocks if blocks else None

# ---------- 风险提示 ----------

def parse_risk(seg):
    blocks = []
    bl = drop_tail_markers(seg)
    cur = None
    for ln in bl:
        if ln.startswith('⚠️') or ln == '风险':
            if cur is not None:
                blocks.append({'type': 'callout', 'tone': 'warn', 'text': cur})
            cur = ''
        elif cur is not None and ln:
            cur += ln if not cur else ' ' + ln
    if cur is not None:
        blocks.append({'type': 'callout', 'tone': 'warn', 'text': cur})
    return blocks if blocks else None

# ---------- 拐点核验（产业爆发型核验，core 变体标题） ----------

def parse_poscheck_inflection(seg):
    """拐点核验 · 为什么是产业爆发型：产业爆发判定 + 里程碑表（title 由 module 级取原文）"""
    blocks = []
    bl = lines(seg)
    sub = next((ln for ln in bl if ln.startswith('🔥')), None)
    verdict = next((ln for ln in bl if ln.startswith('——')), None)
    info = []
    if sub:
        info.append(sub)
    if verdict:
        info.append(verdict)
    if info:
        blocks.append({'type': 'callout', 'tone': 'good', 'text': ' '.join(info)})
    tr = table_rows(seg)
    if tr:
        blocks.append({'type': 'table', 'headers': tr[0], 'rows': tr[1]})
    return blocks if blocks else None


# ---------- 兑现跟踪表 ----------

def parse_tracking_table(seg):
    """📊 兑现跟踪表：跟踪指标表 + 事件时间线（日期/事件成对）"""
    blocks = []
    bl = lines(seg)
    blocks.append({'type': 'title', 'text': bl[0] if bl else '📊 兑现跟踪表'})
    tr = table_rows(seg)
    if tr:
        blocks.append({'type': 'table', 'headers': tr[0], 'rows': tr[1]})
    # 时间线：表格之后、📡 之前，日期行开头（20xx / Hx）与事件行成对
    date_re = re.compile(r'^(20\d{2}|[12]0\d{2}?|[0-9]H\d|H\d)')
    tl = []
    cur = None
    for ln in bl:
        if ln.startswith('📡') or '\t' in ln:
            continue
        if cur is not None and date_re.match(ln):
            tl.append(cur); cur = [ln, '']
        elif date_re.match(ln):
            cur = [ln, '']
        elif cur is not None and not cur[1]:
            cur[1] = ln
        elif cur is not None:
            cur[1] += ' ' + ln
    if cur:
        tl.append(cur)
    if tl:
        blocks.append({'type': 'title', 'text': '🗓 事件时间线'})
        blocks.append({'type': 'table', 'headers': ['时间', '事件'], 'rows': tl})
    return blocks if blocks else None


# ---------- 证伪线 · 形态切换 ----------

def parse_falsify(seg):
    """🚨 证伪线 · 形态切换：触发线（信号:阈值）+ 形态切换说明"""
    blocks = []
    bl = drop_tail_markers(seg)
    t0 = bl[0] if bl else ''
    blocks.append({'type': 'title', 'text': t0})
    for ln in bl:
        if '任一触发' in ln:
            blocks.append({'type': 'callout', 'tone': 'warn', 'text': ln})
            break
    rows = []
    for ln in bl:
        if '：' in ln and not ln.startswith(('🚨', '🔄', '📡', '证伪线', '形态切换')):
            k, v = ln.split('：', 1)
            rows.append([k.strip(), v.strip()])
    if rows:
        blocks.append({'type': 'table', 'headers': ['证伪信号', '触发阈值'], 'rows': rows})
    for i, ln in enumerate(bl):
        if ln.startswith('🔄'):
            txt = ln
            j = i + 1
            while j < len(bl) and not bl[j].startswith('📡'):
                txt += '\n' + bl[j]
                j += 1
            blocks.append({'type': 'text', 'text': txt})
    return blocks if blocks else None


# ---------- 主流程 ----------

def migrate_one(code, text):
    secs = split_sections(text, [
        '催化节点时间表', '四层筛子评估', '拐点核验', '定位核验 · 为什么',
        '兑现跟踪表', '证伪线 · 形态切换', '升级 / 降级信号',
        '估值分析', '⚠️ 风险提示',   # 只用 '估值分析'（'💰 估值分析' 会与子串冲突自截断）
    ])
    out = {'catalysts': None, 'modules': []}

    if '催化节点时间表' in secs:
        cats = parse_catalysts(secs['催化节点时间表'])
        if cats:
            out['catalysts'] = cats

    # 定位核验（四层筛子 / 定位核验 / 拐点核验）：'定位核验 · 为什么' 是 section 标题 marker，优先；
    # '四层筛子评估' 可能出现在正文链接词中（如 swing 升级观察），只作兜底
    pos_seg = secs.get('定位核验 · 为什么') or secs.get('四层筛子评估') or secs.get('拐点核验')
    if pos_seg:
        t0 = lines(pos_seg)[0]
        blocks = None
        if '拐点核验' in pos_seg:
            blocks = parse_poscheck_inflection(pos_seg)
        else:
            blocks = parse_poscheck(pos_seg)
        if blocks:
            out['modules'].append({'key': 'positioning_check', 'title': t0, 'blocks': blocks})

    if '升级 / 降级信号' in secs:
        blocks = parse_updown(secs['升级 / 降级信号'])
        if blocks:
            out['modules'].append({'key': 'upgrade_downgrade', 'title': '🔭 升级 / 降级信号', 'blocks': blocks})

    if '兑现跟踪表' in secs:
        blocks = parse_tracking_table(secs['兑现跟踪表'])
        if blocks:
            out['modules'].append({'key': 'tracking_table', 'title': '📊 兑现跟踪表', 'blocks': blocks})

    if '证伪线 · 形态切换' in secs:
        blocks = parse_falsify(secs['证伪线 · 形态切换'])
        if blocks:
            out['modules'].append({'key': 'falsify_line', 'title': '🚨 证伪线', 'blocks': blocks})

    if '升级 / 降级信号' in secs:
        blocks = parse_updown(secs['升级 / 降级信号'])
        if blocks:
            out['modules'].append({'key': 'upgrade_downgrade', 'title': '🔭 升级 / 降级信号', 'blocks': blocks})

    val_seg = secs.get('估值分析')
    if val_seg:
        blocks = parse_valuation(val_seg)
        if blocks:
            out['modules'].append({'key': 'valuation', 'title': '💰 估值分析', 'blocks': blocks})

    if '⚠️ 风险提示' in secs:
        blocks = parse_risk(secs['⚠️ 风险提示'])
        if blocks:
            out['modules'].append({'key': 'risk', 'title': '⚠️ 风险提示', 'blocks': blocks})

    return out

def main():
    raw = json.load(open(os.path.join(ROOT, 'data', 'u4_pages_raw.json')))
    wl = {r['code'].split('.')[0]: r for r in json.load(open(os.path.join(ROOT, 'data', 'u4_watchlist.json')))}
    out = {}
    summary = {'催化': 0, '定位': 0, '升级降级': 0, '兑现跟踪': 0, '证伪线': 0, '估值': 0, '风险': 0}
    for code, pg in raw.items():
        if pg.get('url') == 'ERR':
            continue
        m = migrate_one(code, pg['text'])
        out[code] = m
        if m['catalysts']: summary['催化'] += 1
        for mod in m['modules']:
            summary[{'positioning_check': '定位', 'upgrade_downgrade': '升级降级',
                     'tracking_table': '兑现跟踪', 'falsify_line': '证伪线',
                     'valuation': '估值', 'risk': '风险'}.get(mod['key'], '?')] += 1
    json.dump(out, open(os.path.join(ROOT, 'data', 'u4_migrate.json'), 'w'), ensure_ascii=False)
    print('解析完成:', sum(1 for c in out), '只')
    print('命中统计:', summary)

if __name__ == '__main__':
    main()