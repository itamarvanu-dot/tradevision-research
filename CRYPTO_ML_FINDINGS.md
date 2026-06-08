# crypto_ml (elihaidv) — שכפול וניתוח שימושיות

**סטטוס: השכפול הצליח** (איתמר פתח גישה; הריפו ציבורי כעת). מקור:
`https://github.com/elihaidv/crypto_ml`, HEAD `1a5a18a` "Add Trade Entry Decision Model".
שוכפל ל-`C:/Users/admin/tradevision-repos/crypto_ml`. אין דאטה בריפו (`data/*` ב-gitignore;
הקבצים שם הם פוינטרים יחסיים לתיקיות `bot/simulations-outputs/` ו-`bot/spot/`).

## מה יש בריפו — וזה רלוונטי ישירות למשימה 4

זה **בדיוק** מנוע ההצלבות אינדיקטורים×עסקאות שאיתמר ביקש, כבר בנוי חלקית בידי אלי:

### 1. `enter_position_desicsion/` — "Trade Entry Decision Model" (הלב)
`blueprint.md` מנסח את אותה מטרה של איתמר: **מסנן משטר-שוק** שמחליט "האם בכלל לפתוח פוזיציה
עכשיו". פורמליזציה:
- לכל timestamp: `best_return_t = max(PnL/notional)` על כל צירופי ה-TP/SL.
- תווית בינארית: `trade_label = 1` אם `best_return > סף-עלות` (ברירת מחדל 1%).
- פיצ'רים: **רק מצב-שוק** (volatility, ADX, slope, range/trend, candle_return, vol_rank,
  session, direction, dist מ-MAs, rolling win-rate/pnl) — **ללא פרמטרי TP/SL** וללא דליפה עתידית.
- מודל: סיווג בינארי (RandomForest, ובאופציה XGBoost/LightGBM), פיצול **time-series**,
  ניתוח Precision-Recall (precision הוא הקריטי), השוואה ל-baseline "תמיד-נכנס", feature importance.
- `train_model.py` / `predict.py` / `evaluate_model.py` (578 שורות הערכה כולל PnL מדומה עם סף).

### 2. `simulation_adjust_model/` — בניית דאטה מפלטי הסימולציה
- `build_dataset.py`: מפענח את ה-CSV של הפלטפורמה לעסקאות (Execute/StopLoose/Close Position),
  בונה שורה לכל פוזיציה עם: pnl, **MAE** (max adverse excursion), **MFE**, משך, StopLossHit,
  notional, score, ופאנל אינדיקטורים. **אנטי-דליפה נכון**: lookup לאינדיקטורים נעשה על
  השעה הקודמת המעוגלת (`(open-1h).floor('h')`) כדי לא לראות נר עתידי.
- `indicators_calculator.py`: פאנל אינדיקטורים שעתי וקטורי + מחלקת `IndicatorsCache`.
- `score = pnl − 0.7·MAE·notional − ν·StopLossHit` — פונקציית עלות שמענישה גם תנודה-נגדית וגם סטופ.

### 3. `direction_predictor_model/feature_engineering.py` — ספריית פיצ'רים עשירה (TA-Lib)
RSI(14,21), MACD+signal+hist, Bollinger (width, position), Stochastic, Williams %R, ATR, CCI,
ROC(5/10/20), momentum(5/10/20), volume ratio, וקידוד ציקלי לזמן (hour/day sin-cos). תלוי ב-`talib`.

### 4. `utils/indicators.py` + `utils/data_loader.py`
מימושי numpy ל-ADX/ATR/slope/volatility/session, וטוען נתוני 1s יומיים (`SYMBOL/1s/DATE.csv`).

## מה שימושי לנו (ומה לא)
**לאמץ:**
- ה-**framing** של אלי (מסנן EV בינארי, time-split, precision-first, feature importance) — בדיוק
  המסגרת של משימה 4. נבנה עליו.
- לוגיקת **פענוח העסקאות** מה-CSV (Execute→entry, last Execute לפני Close→exit, StopLoose→stop hit)
  — כבר שיכפלנו אותה ב-`download_sims.py`.
- **MAE/MFE לכל עסקה** — מדד מצוין ל"כמה כואב היה" שלא תלוי בקונפיג; שימושי לתיוג מפסידות.
- משמעת **אנטי-דליפה** (lookup על נר קודם בלבד).
- ספריית הפיצ'רים (RSI/MACD/BB/Stoch/ATR/CCI/ROC) — נשתמש בה כבסיס, נוסיף אינטראקציות + משטרים.

**להחליף/להרחיב לצורך משימה 4 (הפער מול מה שאיתמר רוצה):**
1. **גרעיניות התווית.** אלי מתייג לפי *שעה* ולפי "האם איזשהו קונפיג היה מרוויח". איתמר רוצה
   חיזוי לכל **עסקה** בפועל (מפסידה/מרוויחה) על קונפיג נתון (nBnU7jvH v1) — דקדוק עדין יותר.
2. **גרעיניות אינדיקטורים.** הפאנל של אלי שעתי. הבוט נכנס על נר 1m וה-MA על 15m → נחשב
   אינדיקטורים גם ב-15m/1h ונבחן איזו רזולוציה מנבאת.
3. **אינטראקציות + משטרים + אי-לינאריות מפורשות** (ADX×slope, vol-rank×dist-MA, ווליום-נמוך/דשדוש)
   — אלי משאיר את זה ל-RF ללמוד לבד; איתמר ביקש פירוק מפורש.
4. **כלל-הברזל לשחזור צולב** (v1→v0/v2/v3, B4xx/EmFD/UQ5r) — לא קיים אצל אלי; נוסיף אותו כשלב חובה.
5. **מינוף דינמי לפי ביטחון** — מעבר ל-blueprint (שם זה רק on/off); נוסיף שכבת sizing.

## אזהרות תלויות
- `tensorflow` ו-`TA-Lib` ב-requirements. במכונה הזו: numpy/pandas/scipy זמינים; **התקנו
  scikit-learn 1.9.0**. `talib` (C-lib) ו-`tensorflow` עדיין לא — נשתמש במימוש pandas/numpy
  לאינדיקטורים (כמו ב-`indicators_calculator.py`) ולא נחייב את talib, ו-GBM דרך sklearn
  (HistGradientBoosting) במקום xgboost/lightgbm אם לא יותקנו.
- ה-data_loader של אלי מצפה לקבצי 1s מקומיים שאין לנו. אנחנו מושכים את אותו מידע מ-CSV API
  הציבורי (`download_sims.py`), ונשלים OHLC אמיתי מ-Binance לחישוב אינדיקטורים.
