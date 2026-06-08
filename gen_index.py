#!/usr/bin/env python3
"""Regenerate data/README.md (the simulation archive index) from manifest.json."""
import json, os
from datetime import datetime, timezone

DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data'))
MANIFEST = os.path.join(DATA, 'manifest.json')
README = os.path.join(DATA, 'README.md')

# config notes per simulation (from skill / Itamar). main case study = nBnU7jvH v1.
KNOWN = {
    'nBnU7jvHsHUIj1ucADZS_v1': 'מקרה בוחן ראשי: W2000/tpd0.10/ntp9/lev2/stop0.006/sLTP? — +23,860% עד 02/2023, maxDD 79.9%, ~2,840 עסקאות',
}

def main():
    m = json.load(open(MANIFEST, encoding='utf-8')) if os.path.exists(MANIFEST) else {'series': {}}
    series = m.get('series', {})
    done = {k: v for k, v in series.items() if v.get('done') and not v.get('empty')}
    empty = sorted(k for k, v in series.items() if v.get('empty'))

    lines = []
    lines.append('# ארכיון סימולציות TradeVision — אינדקס\n')
    lines.append(f'נוצר אוטומטית מ-`manifest.json` ({datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}). ')
    lines.append('רענון: `python ../bot/claude-experiments/gen_index.py`.\n')
    lines.append('\n## מקור ופורמט\n')
    lines.append('- API ציבורי: `/api/variations/csv/?simulationId=<id>&variationId=<v>&page=N` (עימוד מ-1).\n')
    lines.append('- הפיד הגולמי ~99.8% שורות `OpenOrder` (ריענון סולם כל נר). שמרנו **רק** את אירועי\n')
    lines.append('  העסקאות (Execute/StopLoose/Close Position) + רפרנס MA/מחיר שעתי + קונפיג מפוענח.\n')
    lines.append('- קבצים (gzip, ב-`raw/`, לא ב-git): `<id>_v<v>_trades.csv.gz`, `<id>_v<v>_ma_hourly.csv.gz`.\n')
    lines.append('- עמודות trades: `timestamp,event_type,side,price,amount,orig_price,orig_amount,balance,'
                 'pos_size,profit,pnl,fee,candle_level,extra1,ma`.\n')

    lines.append('\n## סדרות שהורדו (מזהה → קונפיג → תקופה → היקף)\n')
    lines.append('| מזהה_וריאציה | מטבע-מחיר₀ | תקופה | #עסקאות | #עמודים | אופסטי-סולם (decode) | הערה |\n')
    lines.append('|---|---|---|---|---|---|---|\n')
    for k in sorted(done):
        v = done[k]
        cfg = v.get('config', {}) or {}
        offs = cfg.get('order_offsets_pct', [])
        offs_s = f'{cfg.get("entry_side","?")} {offs[:4]}…{offs[-2:]}' if offs else '—'
        p0 = cfg.get('entry_price', '?')
        note = KNOWN.get(k, '')
        lines.append(f'| `{k}` | {p0} | {v.get("first_date")}→{v.get("last_date")} | '
                     f'{v.get("n_trades")} | {v.get("pages")} | {offs_s} | {note} |\n')

    if empty:
        lines.append('\n## וריאציות ריקות (לא קיימות ב-API)\n')
        lines.append(', '.join(f'`{e}`' for e in empty) + '\n')

    lines.append('\n## שימוש לשחזור צולב (משימה 4)\n')
    lines.append('- תוך-סימולציה: `nBnU7jvH` v0/v2/v3 מול v1.\n')
    lines.append('- בין-סימולציות: v0 של UQ5r / EmFD / B4xx / FQxm / GX5l / f2lt / 8wbn.\n')

    os.makedirs(DATA, exist_ok=True)
    with open(README, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print(f'wrote {README}: {len(done)} done series, {len(empty)} empty')

if __name__ == '__main__':
    main()
