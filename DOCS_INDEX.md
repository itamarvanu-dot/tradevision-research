# DOCS_INDEX — מפת הפרויקט (project map)

מסמך ניווט מרכזי ל-`tradevision-research`. רוב מסמכי הממצאים כתובים בעברית; הקוד באנגלית.
מתחילים? קראו את [`README.md`](README.md) (איך מריצים את החיפוש), ואז את המפה כאן.

> **מהו הפרויקט:** קוד מחקר לבוט TradeVision (אסטרטגיית הצלבת ממוצעים נעים, `bot_type_id=10`).
> המטרה: להקטין Drawdown בלי לאבד תשואה, ולמצוא קונפיגורציות ששורדות **מחוץ למדגם (OOS)**.
> אין כאן קוד מנוע קנייני — רק פורט מחקרי ב-Python + harness.

---

## 1. מנועים (Engines)

| קובץ | תיאור |
|------|-------|
| `engine_v6.py` | מנוע ה-backtest הראשי על נתוני 1-דקה (CPU/numba). משחזר את מנגנון הפלטפורמה עסקה-מול-עסקה. ראו [`ENGINE_V6_SPEC.md`](ENGINE_V6_SPEC.md), [`ENGINE_MECHANICS.md`](ENGINE_MECHANICS.md). |
| `differential_engine.py` | מנוע דיפרנציאלי (config×year), אנסמבל/רוטציה, מנוע אדפטיבי. ראו [`DIFFERENTIAL_ENGINE_RESEARCH.md`](DIFFERENTIAL_ENGINE_RESEARCH.md). |
| `engine_strategies.py` | מנועי אסטרטגיה נוספים (DT/Avi). |
| `dd_controls.py` | שערי בקרה לניסוי מבוקר (super_gate, block-bootstrap, matched control). |
| `colab_v6/` | מנוע ה-GPU: `v6_cuda.py` (קרנל CuPy), `kernel_ref.py` (ייחוס), `v6_main.py`, `run_a100.py`. |

## 2. חיפוש וסריקה (Search & Scan)

| קובץ | תיאור |
|------|-------|
| `joint_search.py` | החיפוש המרכזי: Sobol GPU על מרחב הפרמטרים → דירוג CPU train→OOS + super_gate. נקודת הכניסה הראשית. |
| `ensemble_search.py` | חיפוש אנסמבל על שורדים. |
| `scan_strategies.py` | סריקת אסטרטגיות. |
| `sweep_equity.py` / `run_matrix.py` | sweep-ים ומטריצות פרמטרים. |
| `run_dd_experiments.py` | הרצת ניסויי הקטנת ה-Drawdown. ראו [`DD_REDUCTION_RND.md`](DD_REDUCTION_RND.md), [`DD_FORENSIC_REPORT.md`](DD_FORENSIC_REPORT.md). |
| `eval_filter.py` | סינון/הערכת תוצאות. |

## 3. נתונים (Data fetchers)

| קובץ | מקור |
|------|------|
| `download_binance.py`, `download_sims.py` | Binance / סימולציות. |
| `fetch_bybit.py`, `fetch_bybit2.py` | Bybit. |
| `fetch_yf.py` | Yahoo Finance (`yfinance`). |

## 4. תיק והון (Portfolio)

`portfolio.py`, `portfolio_metric.py`, `run_portfolio_top.py`, `case_study_portfolio.py`.

## 5. בניית קמפיינים (Campaign builders)

`build_fee_campaigns.py`, `build_trades.py`, `create_top100_campaign.py`,
`create_top1000_campaign.py`, `cat3_balanced.py`.

## 6. אלפא וניתוח (Alpha & analysis)

`analyze_alpha.py`, `analyze_task4.py`, `features_micro.py`.
ראו [`FINDINGS_TASK4.md`](FINDINGS_TASK4.md), [`FINDINGS_TASK4_ALPHA.md`](FINDINGS_TASK4_ALPHA.md), [`FINDINGS_TASK5.md`](FINDINGS_TASK5.md).

## 7. חוצה-נכסים (Cross-asset)

`run_crossasset.py`, `run_crypto_compare.py`.
ראו [`CROSS_ASSET_TEST.md`](CROSS_ASSET_TEST.md), [`CROSS_ASSET_SWEEP.md`](CROSS_ASSET_SWEEP.md), [`CRYPTO_ML_FINDINGS.md`](CRYPTO_ML_FINDINGS.md).

## 8. מעבדה מבוזרת (Lab / distributed)

`lab_worker.py`, `lab_pubsub.py`, `lab_diag.py`. ראו [`LAB_SCALING.md`](LAB_SCALING.md).

## 9. תת-פרויקט: מעבר משטרים (regime_switch/)

מחקר זיהוי משטר שוק (דשדוש/טרנד) והתאמת האלגוריתם. כולל `engine.py`, `ma_scan.py`,
`contexts.py`, `earlywarn.py`, `eventstudy.py`, `persistence_test.py`, `catalog.py`.
ראו [`FINDINGS_REGIME_SWITCH.md`](FINDINGS_REGIME_SWITCH.md), [`ANATOMY_OF_LOSSES.md`](ANATOMY_OF_LOSSES.md).

## 10. בדיקות ואימות (Tests & verification)

| קובץ | מה בודק |
|------|---------|
| `python joint_search.py --selftest` | מיפוי Sobol + split train/oos + חיווט שערים (מיידי, ללא GPU/data). |
| `python joint_search.py --gpu-smoke` | אימות CuPy + הקרנל על ה-GPU. |
| `python tests/smoke_synthetic.py` | מנוע v6 על נתונים סינתטיים — ברירות-מחדל הן no-op, וכל פרמטר חדש משנה תוצאה. |
| `tests/test_defaults_identical.py` | זהות ברירות-מחדל. |
| `verify_var10.py`, `verify_greenmonths.py`, `sanity_maxentrydist.py`, `test_liquidation.py`, `test_strategies_sanity.py` | אימותים ממוקדים. |

---

## כל מסמכי הממצאים (Findings docs)

| מסמך | נושא |
|------|------|
| [`ENGINE_V6_SPEC.md`](ENGINE_V6_SPEC.md) | מפרט מנוע v6 (GPU) — סופי |
| [`ENGINE_MECHANICS.md`](ENGINE_MECHANICS.md) | מנגנון הסימולציה האמיתי של הפלטפורמה |
| [`ENGINE_EXPERIMENTAL_PARAMS.md`](ENGINE_EXPERIMENTAL_PARAMS.md) | פרמטרים ניסיוניים (maxEntryDist, seasonalLeverage) |
| [`CROSSING_ENGINE_DESIGN.md`](CROSSING_ENGINE_DESIGN.md) | מנוע הצלבות אינדיקטורים × עסקאות (משימה 4) |
| [`DD_REDUCTION_RND.md`](DD_REDUCTION_RND.md) | הקטנת Drawdown בלי לאבד תשואה |
| [`DD_FORENSIC_REPORT.md`](DD_FORENSIC_REPORT.md) | ניתוח פורנזי — מקור ה-Drawdown |
| [`DIFFERENTIAL_ENGINE_RESEARCH.md`](DIFFERENTIAL_ENGINE_RESEARCH.md) | מנוע דיפרנציאלי, אנסמבל/רוטציה |
| [`FINDINGS_REGIME_SWITCH.md`](FINDINGS_REGIME_SWITCH.md) | אלגוריתם דיפרנציאלי לפי משטר שוק |
| [`ANATOMY_OF_LOSSES.md`](ANATOMY_OF_LOSSES.md) | האנטומיה של ההפסדים — נתיחה פורנזית |
| [`SPECULATION_CATALOG.md`](SPECULATION_CATALOG.md) | 50 אמונות מסחר מול העסקאות שלנו |
| [`CATALOG_OF_SPECULATIONS.md`](CATALOG_OF_SPECULATIONS.md) | קטלוג ספקולציות (גרסה מוקדמת) |
| [`STRATEGIES_CATALOG.md`](STRATEGIES_CATALOG.md) | קטלוג כל ה-bot_type_id |
| [`STRATEGIES_ANALYSIS.md`](STRATEGIES_ANALYSIS.md) | ניתוח לעומק + הצעות שיפור לכל אסטרטגיה |
| [`FINDINGS_TASK4.md`](FINDINGS_TASK4.md) | הצלבת אינדיקטורים × עסקאות |
| [`FINDINGS_TASK4_ALPHA.md`](FINDINGS_TASK4_ALPHA.md) | פס האלפא (מיקרו-מבנה 1m) |
| [`FINDINGS_TASK5.md`](FINDINGS_TASK5.md) | עיצוב התפלגות ההפסד + מדיניות מינוף/תיק |
| [`CROSS_ASSET_TEST.md`](CROSS_ASSET_TEST.md) | הכללה מעבר לקריפטו |
| [`CROSS_ASSET_SWEEP.md`](CROSS_ASSET_SWEEP.md) | סריקת מיליוני צירופים פר-נכס + lockbox OOS |
| [`CRYPTO_ML_FINDINGS.md`](CRYPTO_ML_FINDINGS.md) | crypto_ml (elihaidv) — שכפול וניתוח |
| [`LAB_SCALING.md`](LAB_SCALING.md) | סקיילינג מעבדה (Pub/Sub fan-out) |
| [`V6_SCAN_RESULTS_2026-06-08.md`](V6_SCAN_RESULTS_2026-06-08.md) | תוצאות סריקת v6 על GPU |
