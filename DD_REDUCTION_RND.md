# DD_REDUCTION_RND — הקטנת Drawdown בלי לאבד תשואה

מצב: **הורץ על המארח (Windows host), CPU, על נתוני 4-מטבעות מקומיים (2026-06-08).**
ה-baseline אומת, ה-gate (defaults=no-op) עבר, וה-CPU pass רץ כ-**screen**. **השלב המרכזי
שודרג** (לפי כיוון של איתמר): חיפוש-משותף בקנה-מידה מעל כל 5 הרעיונות יחד (`joint_search.py`,
סעיף 6). כל הקוד תחת `bot/claude-experiments/` בלבד (ענף `claude-experiments`, לא נוגע
ב-main/בפלטפורמה).

---

## 0. עקרונות-היסוד של המועצה (מכבדים אותם בכל שורה)

1. **return/DD כמעט אינווריאנטי במינוף.** המינוף הוא "כפתור ווליום" — הורדתו לא משפרת את
   היחס. רק שניים משפרים return/DD: (א) **דה-קורלציה של אשכולות-הפסד**, (ב) **גאומטריית
   התשלום הפר-עסקה** (stop/TP/trail). בחירת-כניסה (AUC≈0.5) — לא חוזרים לזה. לכן אף רעיון
   כאן לא נוגע בכניסות מלבד **size taper** (לא בוחר אם להיכנס — רק כמה, פונקציה רציפה של
   מרחק-מ-MA, שאינו ניבוי).
2. **כלל אימות-העל הקשיח** (`dd_controls.super_gate`) — רעיון עובר רק אם כל אלה מתקיימים:
   - (a) `return/DD` של הרעיון > זה של ה-**baseline** (פורטפוליו 4-מטבעות במשקל שווה);
   - (b) `return/DD` > **baseline של מינוף-ממוצע-זהה** (constant-average-L matched) — אחרת
     זה רק "לסחור פחות"/"להוריד מינוף" בתחפושת ונפסל;
   - (c) **shuffle/block-bootstrap gate**: שיפור ה-DD גדול יותר על **סדר-העסקאות האמיתי**
     מאשר על סדר מעורבב — כלומר הדה-קורלציה אמיתית (תלוית-מבנה), לא מקרית;
   - (d) **הזנב הימני נשמר**: `#trades>5r` של הרעיון ≥ זה של ה-baseline (אם חתכת את
     הזנב — נכשל);
   - (e) **lockbox walk-forward**: אופטימיזציה 2018-2023, הקפאה, מבחן 2024-2026 — ה-OOS
     `return/DD` של הרעיון ≥ זה של ה-baseline;
   - (f) **הכללה על 4 המטבעות** (≥3 מתוך 4), לא רק ETH.

הגייטים יחסיים (רעיון מול baseline תואם), ולכן כיול engine→platform מתבטל בהם. מספרי
engine = לדירוג; אמת-הפלטפורמה מצוטטת בנפרד.

---

## 1. מה מומש (קוד)

| קובץ | תפקיד |
|---|---|
| `engine_v6.py` | מנוע ה-CPU הקנוני, **הורחב** ב-5 הרעיונות כפרמטרים חדשים, **ברירת-מחדל = זהה למנוע הקיים** (הוכחה: `tests/test_defaults_identical.py`). גם: `realized_vol()` (vol ידוע-בכניסה), ספירת `n_trades_gt5r`, מינוף-פר-פוזיציה ו-`risk` (1r) בכל רשומת-עסקה, וחיסול לפי המינוף-בפועל. |
| `dd_controls.py` | הרסן: block-bootstrap/shuffle gate, constant-L matched, פורטפוליו 4-מטבעות, lockbox split, `count_gt5r`, `decorrelation_score`, ו-`super_gate`. |
| `run_dd_experiments.py` | מריץ כל רעיון מול ה-baseline + כל הגייטים, פולט `dd_results.csv`. CPU בלבד (רץ ב-sandbox או ב-Colab). |
| `colab_v6/kernel_ref.py` | `run_config_geom` — מראה pure-python של גאומטריית-היציאה + taper, **חוזה ה-GPU**. |
| `colab_v6/v6_cuda.py` | קרנל **`_SRC_GEOM`** נפרד (opt-in) לזירוז סריקות 1&3 ל-A100; הקרנלים הקיימים לא נגעו. `run_list_geom()`. |
| `colab_v6/run_a100.py` | entrypoint אחד ל-A100: GATE0 (defaults) → GATE1 (GPU==CPU geom) → ניסויים CPU → סריקת-סקייל GPU. |
| `tests/test_defaults_identical.py` | מטמיע את המנוע **המקורי מילה-במילה** ומוכיח שהברירת-מחדל זהה על 4 מטבעות × 8 קונפיגים. |
| `tests/smoke_synthetic.py` | בדיקה מיידית על נתונים סינתטיים (בלי npz): imports, defaults-identical, וכל toggle משנה תוצאה. |

### מיפוי הרעיונות → פרמטרים (כולם ברירת-מחדל no-op)

1. **גאומטריית יציאה אסימטרית** — `stop_loose` (סריקה רחבה); `trail_mode='atr'` +
   `trail_mult` (chandelier-trail לפי `vol` במקום אל ה-MA, אחרי ה-`stopLooseTP`-th TP);
   `runner_frac` (משאיר 10-20% מהפוזיציה אחרי ה-TP האחרון על trail רופף לתפיסת זנב).
2. **stop ממוקד-תנודתיות + סיכון-דולרי-קבוע** — `stop_k` (`eff_stop = stop_k·vol_at_entry`);
   `risk_frac` + `max_lev` (גודל-פוזיציה לסיכון-דולרי קבוע, מנרמל יחידת-הפסד באשכולות
   ה-whipsaw עתירי-התנודתיות).
3. **size taper רציף לפי מרחק-מ-MA** — `taper_ref, taper_near_mult, taper_far_mult`
   (גודל=f(dist); `size_cap>1` לכניסות חזקות; ה-guard הבינארי הוא המקרה `taper_far_mult=0`).
4. **אנטי-מרטינגייל על עקומת-ההון** — `lever_boost, dd_trigger, boost_decay` (מגדיל מינוף
   ב-DD מהשיא במקום להקטין, מנצל mean-reversion שבועי), `liq_guard` (תקרת-מינוף קשיחה כך
   שמחיר-החיסול נשאר מעבר לסטופ — שימוש מכוון במבנה-החיסול כרצפה).
5. **vol-targeting איטי של מינוף** (red-flagged) — `vol_target` + `vol_slow` + clamp.

הערה אדריכלית: רעיונות 1&3 (גאומטריה פר-פוזיציה) רצים גם ב-GPU (קרנל GEOM) לסריקות-ענק.
רעיונות 2/4/5 (תלויי-עקומת-הון/סדרתיים) רצים ב-CPU בלבד בספירות-קונפיג מתונות — שם ממילא
רצים הגייטים (bootstrap/lockbox). זה מתועד ולא "פינה שנחתכה".

---

## 2. ה-baseline (חובה — הרצפה המתמטית)

**פורטפוליו 4-מטבעות (BTC/ETH/XRP/BNB) במשקל שווה**, על קונפיג האלוף
`longSMA2600 / tpd0.18 / ntp15 / lev1 / stop0.006 / sLTP2`. כל רעיון נמדד כשיפור *מעל*
הפורטפוליו, **לא** מעל ETH-בודד. שאלת-בונוס (נמדדת ב-`decorrelation_score`): האם יותר
מטבעות במשקל שווה מורידים את הקורלציה הממוצעת בין סדרות-החודשים (= דה-קורלציה אמיתית)?

---

## 3. תוצאות ה-baseline + ה-screen (CPU, נתונים מקומיים)

> **לא ממציאים מספרים.** הערכים מ-`dd_screen.log`/`dd_results.csv` של ההרצה ב-2026-06-08
> (יחידות-engine; פלטפורמה ≈ engine ÷ 10). ה-screen ב-`--quick` הוא לאימות-אפקט+נכונות-גייט
> בלבד — **לא הדירוג הסופי** (זה החיפוש המשותף, סעיף 6).

### baseline (פורטפוליו 4-מטבעות, W2600/tpd0.18/ntp15/lev1/stop0.006/sLTP2) — אומת
| מדד | ערך |
|---|---|
| growth (×) | **55.7** |
| maxDD% | **16.2** |
| return/DD | **344.5** |
| % חודשים-ירוקים | **58** |
| חודש גרוע ביותר | **−15%** |
| קורלציה ממוצעת בין-מטבעות (decorr score) | **0.204** |

### screen מלא — 11 ווריאנטים (`dd_results.csv`, base retDD 344.48, base OOS retDD 8.0, #>5r base 264)
`--quick`, פורטפוליו 4-מטבעות, יחידות-engine. **כל ה-11 נכשלו ב-super_gate — וזו התוצאה הנכונה**:
קונפיג-בודד פר-רעיון לא שורד את כל הגייטים. אבל יש אות-OOS אמיתי במקומות (ראה הדגשות):

| רעיון | ווריאנט | port retDD | port DD% | #>5r | shuffle | **OOS retDD** | cross-coin | PASS |
|---|---|---|---|---|---|---|---|---|
| 1 | stop0.0045 | 294 | 15.9 | 281 | **True** | 8.68 | 1/4 | ✗ |
| 1 | stop0.008 | 353 | 18.0 | 251 | False | 7.28 | 2/4 | ✗ |
| 1 | atrtrail1.0 | 86 | 24.8 | 264 | False | 5.07 | 0/4 | ✗ |
| 1 | **runner0.15** | **387** | 16.2 | 264 | False | 8.03 | 3/4 | ✗ |
| 1 | runner0.15+atr1 | 86 | 24.8 | 264 | False | 5.07 | 0/4 | ✗ |
| 2 | **volstop_k1.0** | 50 | 23.3 | 284 | **True** | **13.59** | 1/4 | ✗ |
| 2 | risk0.02+volstop1 | 50 | 23.3 | 284 | **True** | **13.59** | 1/4 | ✗ |
| 3 | taper r0.01 n1.25 f0.5 | 354 | 22.4 | 264 | False | 5.79 | 2/4 | ✗ |
| 4 | **boost1.5@dd0.1** | **834** | 24.7 | 264 | False | 5.41 | 3/4 | ✗ |
| 5 | **vtarget lo0.7 hi1.5** | **699** | 16.7 | 264 | False | **11.30** | 4/4 | ✗ |

**קריאת ה-screen (אמיתית, לא ממציאים):**
- כל רעיון **מחווט ומשנה תוצאה** (retDD נע 50→834) וכל ששת הגייטים נקראים
  (`chk_beats_baseline/beats_matched_constL/shuffle_order_real/right_tail_preserved/lockbox_oos/cross_coin`).
- **אות-OOS אמיתי קיים אך מבודד:** idea2 (vol-stop) נותן **OOS retDD 13.59 > base 8.0 וגם עובר
  shuffle**, אך נכשל ב-cross-coin (1/4) וב-port retDD (50) — כלומר טוב על מטבע, לא מכליל. idea5
  נותן OOS 11.3 ו-4/4 cross אך נכשל ב-shuffle (לא דה-קורלציה אמיתית — בעיקר מינוף-מוסווה).
  idea1 runner מרים retDD ל-387 ב-DD זהה אך לא עובר shuffle.
- **המסקנה המתודולוגית:** האות מפוזר בין רעיונות שונים ותלוי-אינטראקציה (vol-stop נותן OOS,
  runner מרים retDD ללא תוספת-DD, lev נמוך נותן הכללה) — **בדיוק מה שחיפוש-משותף אמור לאחד**.
  אף tweak בודד לא עובר הכול → הדירוג עובר לחיפוש המשותף (סעיף 6).

### היפותזות וכשל-צפוי (לבדיקה מול המספרים)
- **1 — ההימור הראשון.** אין "קיר חיזוי" (הפסד=פרמטר נשלט). `runner` + chandelier-trail
  אמורים להקטין דימום-לעסקה **ולהאריך את הזנב הימני** (לכן `#>5r` צריך לעלות, לא לרדת).
- **2 — ה-DD נוצר באשכולות whipsaw (ספט 2021).** `risk_frac` מקבע את ההפסד-לעסקה ביחידות-
  דולר → אמור להחליק דווקא שם. סכנה: כשה-stop קטן מאוד הגודל מתנפח — `max_lev`/`liq_guard`
  חוסמים; בדוק שהמינוף-בפועל לא קופץ.
- **3 — הכללה של ה-maxEntryDist הבינארי.** אמור לשמר תשואה (`size_cap>1` לכניסות חזקות) תוך
  גיזום שבריריות. אם רק מוריד מינוף-ממוצע → ייפול ב-matched-L.
- **4 — הלא-שגרתי.** מנצל mean-reversion שבועי מתועד. **כשל-צפוי: DD שלא מתאושש (regime
  break).** `run_a100` בודק אותו על ה-DD-ים העמוקים ביותר + זנב סינתטי-יורד, וחייב לנצח גם
  baseline של timing-אקראי במינוף-ממוצע-זהה. `liq_guard` הוא הרצפה הקשיחה.
- **5 — red-flagged.** סביר שייפול ב-constant-average-L + bootstrap. נבדק רק כדי לסגור את
  השאלה.

---

## 4. מצב ההרצה (הורץ על המארח)

הורץ על ה-**Windows host** (לא ה-cowork sandbox שנפל ב-disk-full, לא Colab) על נתוני
4-מטבעות מקומיים שנמצאו ב-`data/binance/{BTC,ETH,XRP,BNB}USDT_1m.npz` (2018-05→2026-04,
~4.2M דקות/מטבע). היה צריך להתקין `numba` (חסר). מה שרץ:
- **`tests/smoke_synthetic.py` → ALL PASS** (אחרי תיקון-כיול: ה-synth מעולם לא הורץ והניב 9
  trades<סף, ו-anti-mart לא נורה כי DD<5%; תיקנתי את ה-synth ל-160K נרות + הורדתי את
  `dd_trigger` בבדיקת-ה-toggle כך שהיא נורית על DD~0.4%). defaults-identical + כל 5 הרעיונות
  מחווטים ומשנים תוצאה.
- **`tests/test_defaults_identical.py` (GATE 0) על נתונים אמיתיים → PASS** על 4 מטבעות ×
  8 קונפיגים (legacy-engine מילה-במילה == engine_v6 בברירת-מחדל). ההרחבות הן no-op מוכח.
- **`run_dd_experiments.py --idea all --quick` (screen) → `dd_results.csv`** (סעיף 3).
- GATE 1 (GPU==CPU geom) ו-STAGE 3 (סריקת-GPU) **דולגו** — אין GPU/cupy על המארח (כצפוי;
  הם רצים על A100).

### איך מריצים שוב
```bash
# CPU host (כמו שרץ): screen + gate
DATA_DIR=/path/to/data/binance python run_dd_experiments.py --idea all --quick --out .
DATA_DIR=/path/to/data/binance python tests/test_defaults_identical.py
python tests/smoke_synthetic.py            # מיידי, בלי נתונים
# A100 (Colab) — הריצה המלאה כולל החיפוש המשותף (סעיף 6):
#   !pip -q install cupy-cuda12x ; mount drive ; %cd .../bot/claude-experiments
#   import colab_v6.run_a100 as R; R.main()    # GATE0→GATE1→screen→GPU-scale→STAGE4 joint
```

---

## 5. המלצה — מסגרת

ההמלצה הסופית (אילו פרמטרים להוסיף לבוט) נחתמת רק על הפרמטרים ש**עברו את אימות-העל
מחוץ-למדגם** — והם נבחרים מהחיפוש המשותף (סעיף 6), לא מה-screen.
- כל פרמטר ששרד נוסף כברירת-מחדל no-op לבוט (אפס סיכון רגרסיה), ומופעל רק בערך-המנצח.
- כל המספרים (return, DD, return/DD, #>5r) מול ה-baseline (retDD **344.5**) ומול matched-L,
  לא מול ETH-בודד.
- **עדות תומכת מהמנוע הדיפרנציאלי** (`DIFFERENTIAL_ENGINE_RESEARCH.md`): רווחי-OOS של
  קונפיג-בודד שבירים (המנוע האדפטיבי נכשל ב-lockbox, F&G חסר-ערך) → מחזק שהדירוג חייב להיות
  OOS+gate, ושאנסמבל-סטטי של ~4 קונפיגים (DD 18→13, חודשים-ירוקים 61→70) הוא רובסטי.

---

## 6. השלב המרכזי — חיפוש משותף בקנה-מידה (`joint_search.py`)

**הרציונל (כיוון של איתמר):** לא לבדוק רעיונות אחד-אחד על מעט קונפיגים — זה לא רואה
**אינטראקציות בין-רעיונות** (למשל runner + vol-stop + lev-נמוך יחד) ולא את **האופטימום
הגלובלי**. במקום זה: חיפוש אחד משותף מעל **6 פרמטרי-בסיס × כל 5 הרעיונות יחד**.

**הקומבינטוריקה (חושב, לא הערכה):**
- בסיס: W(41)·tpd(29)·ntp(15)·lev(5)·stop(18)·sltp(4) = **6.42M**.
- רעיונות: trail(40)·vol-stop/risk(40)·taper(36)·anti-mart(32)·vol-target(5) = **9.22M**.
- **factorial מלא = 5.92×10¹³ (59 טריליון)** מעל ~21 ממדים → בלתי-אפשרי לספירה מלאה (אפילו
  ב-10⁷ cfg/s ≈ 70 יום). **חובה דגימה.**

**אסטרטגיית דגימה:**
1. **Sobol (scrambled QMC)** מעל קוביית-יחידה 21-ממדית → מיפוי לפרמטרים (log ל-stop/risk,
   עיגול-שלם ל-ntp/sltp, choice ל-trail_mode, סף on/off לשערי כל רעיון; "off"=ברירת-מחדל
   no-op → החיפוש מכסה גם את הבסיס הטהור וכל תת-קבוצת-רעיונות). `scipy.stats.qmc` (1.17.1).
2. **N~10⁸–10⁹** דגימות בשלב הסריקה הגס (Stage A) — **על TRAIN 2018-2023 בלבד**.
3. **עידון מקומי** (Stage D): Sobol שני בתוך תיבה מכווצת (frac 0.25) סביב השורדים → 2-3 סבבים.

**הצינור (anti-overfit — הליבה):**
- **Stage A** (GPU/CPU): דגום N, נקד על TRAIN, שמור top-K (לפי portfolio return/DD, כל
  4 המטבעות נסחרים).
- **Stage B** (CPU): נקד-מחדש את ה-top-K על **held-out 2024-2026**.
- **Stage C** (CPU): `dd_controls.super_gate` על המובילים-ב-OOS — shuffle/block-bootstrap
  (שיפור-DD גדול יותר על סדר אמיתי מ-shuffled), constant-avg-L matched, #trades>5r,
  ו-≥3/4-coin generalisation.
- **המנצח = השורד-מחוץ-למדגם, לא בעל המספר הכי-גבוה ב-TRAIN.**

**ETA ל-A100** (נרות 30-דק', TRAIN ≈105K נרות/קונפיג): מקצב ה-numba הידוע (~2.2K cfg/s/core
CPU) → A100 מתפרס ל-~10⁶–10⁷ cfg/s → **10⁹ דגימות ב-~2–17 דק' compute** + recompute של MA
לכל W + re-score של השורדים. סבב מלא נכנס בסשן Colab בודד. **הקצב נמדד בשיגור הראשון.** אם זול
— מרחיבים ל-10⁹⁺ וסבב-עידון נוסף.

**מצב המנוע:** ה-harness מאומת (`joint_search.py --selftest` → PASS: מיפוי Sobol בטווח, כל
רעיון נדלק, חלוקת train/oos = 72/28 חודשים, תיבת-עידון תקינה). הסקורר הוא `engine_v6.run_engine`
(כל 5 הרעיונות, מאומת default-identical). שולב כ-STAGE 4 ב-`run_a100.py`.

**הרחבת-קרנל ל-GPU (מתועד, לא מומצא):** קרנל ה-GEOM ב-`v6_cuda` כבר נושא בסיס + רעיונות 1&3
(trail/runner/taper) → סריקת-Sobol 11-ממדית (בסיס+1&3) רצה על A100 **היום**. כדי לקפל את
רעיונות 2/4/5 לקרנל-יחיד: להוסיף knobs סקלריים פר-קונפיג (stop_k, risk_frac+max_lev;
lever_boost+dd_trigger+boost_decay+running-peak; vol_target_lo/hi מול vol_slow המשותף) —
זול, הקרנל כבר מריץ את עקומת-ההון סדרתית. אז **להריץ מחדש GATE 1 (GPU==CPU geom) מורחב**
לפני אמון במספרי-GPU. לסריקת-TRAIN-בלבד: להעביר אינדקס-נר-אחרון (<2024).

*(נחתם 2026-06-08. הרצה: `DATA_DIR=… python joint_search.py --n 200000 --topk 200 --rounds 2`
או `run_a100.main()` כולל STAGE 4. סגירת ראנטיים בסיום.)*
