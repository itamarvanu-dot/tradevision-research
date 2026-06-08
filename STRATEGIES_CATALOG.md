# TradeVision — קטלוג האסטרטגיות (כל ה-bot_type_id)

> מסמך מיפוי מקור-אמת. נכתב מקריאה ישירה של קוד הבוט (ענף `claude-experiments`, ללא שינוי מקור).
> מקורות: `Simulator/Simulate.ts` (factory), `Simulator/ValidationSchemas.ts` (סכמות),
> `Workers/*.ts` (הלוגיקה), `Models.ts` (שדות ה-Bot).
> כל המספרים/הלוגיקה כאן הם תיאור הקוד כפי שהוא — לא הערכות ביצועים.

---

## 0. מפת השדרה (איך bot_type_id הופך לאלגוריתם)

ה-factory ב-`Simulate.ts:382-416` (`createPlacer`) ממפה:

| id | שם מחלקה        | קובץ                    | אב (extends)   | שוק     | רעיון בקצרה |
|----|------------------|-------------------------|----------------|---------|-------------|
| 1  | `OrderPlacer`    | `Workers/PlaceOrders.ts`| `BasePlacer`   | ספוט    | גריד/DCA דו-צדדי סביב ספר ההזמנות |
| 2  | `WeightAvg`      | `Workers/WeightAvg.ts`  | `BasePlacer`   | ספוט    | DCA ממוצע-משוקלל (מרטינגייל כלפי מטה) |
| 3  | `FutureTrader`   | `Workers/FuturesTrader.ts`| `BasePlacer` | עתידיים | **אב כל אסטרטגיות העתידיים** — DCA ממונף + TP יחיד + SL + כיוון-MA אופציונלי |
| 4  | `DualBot`        | `Workers/DualBot.ts`    | `FutureTrader` | עתידיים | פוזיציית-ליבה גדולה + מיצוע, סוגריים סימטריים |
| 5  | `DirectionTrader`| `Workers/DirectionTrader.ts`| `FutureTrader`| עתידיים | סטראדל פריצה דו-כיווני (stop משני הצדדים) + היפוך |
| 6  | `Periodically`   | `Workers/Periodically.ts`| `WeightAvg`   | ספוט    | DCA לפי זמן (קונה סכום קבוע כל X שניות) |
| 7  | `SignalingPlacer`| `Workers/SignaligProcessor.ts`| `FutureTrader`| עתידיים | עוקב-איתותים מטלגרם (copy-trading) |
| 8  | `OneStep`        | `Workers/OneStep.ts`    | `FutureTrader` | עתידיים | עסקת-סוגריים יחידה: כניסה אחת + TP + SL, בלי מיצוע |
| 9  | `AviAlgo`        | `Workers/AviAlgo.ts`    | `FutureTrader` | עתידיים | פורץ-מומנטום רב-חלונות (pump/dump) + trailing |
| 10 | `MovingAverages` | `Workers/MovingAverages.ts`| `FutureTrader`| עתידיים | **(הידוע)** חציית MA, reverse-on-cross, סולם TP |

### היררכיית ירושה
```
BasePlacer (אבסטרקטי: place_order, buildHistory, calculatePNL, align, rounding)
├── OrderPlacer (1)          ספוט
├── WeightAvg  (2)           ספוט
│   └── Periodically (6)     ספוט
└── FutureTrader (3)         עתידיים — הליבה המשותפת
    ├── DualBot (4)
    ├── DirectionTrader (5)
    ├── SignalingPlacer (7)
    ├── OneStep (8)
    ├── AviAlgo (9)
    └── MovingAverages (10)
```

### מנגנונים משותפים מ-`BasePlacer` ו-`FutureTrader` (חשוב למנוע backtest)
- **`buildHistory()`** (`BasePlacer:103-159`): משחזר את מצב הפוזיציה מרשימת ההזמנות שמולאו — מאתר `standingBuy`, `lastSell`, `lastBuy`, `myLastOrder`, ו-`positionOrders` עד הזמנת ה-`FIRST`. כך כל איטרציה היא חסרת-מצב (state נבנה מחדש מהזמנות).
- **`calculatePNL()`** (`BasePlacer:160-211`): סוכם pnl פחות עמלה של **0.0002** מהנושיונל (`avgPrice*qty*0.0002`) — זה ה-fee ה"אמיתי" שמופיע בקוד הריצה (בסימולציה ה-orderexecute בד"כ לא גובה — לכן הקליברציה הקבועה fee=0.0002 בסריקות).
- **`positionSide()`** (`Models.ts:111`): בעתידיים — `LONG`/`SHORT`/`BOTH` לפי `mode`+`direction`.
- **`add/sub/minFunc/maxFunc`** (`FutureTrader:123-141`): כל החשבון מודע-כיוון — ב-SHORT הסימנים מתהפכים. זה מאפשר לכל האסטרטגיות לעבוד סימטרית לונג/שורט.
- **`averagePrice(PAIR, SMA)`** vs **`averagePriceQuarter(PAIR, longSMA)`**: שתי ממוצעות שונות. `averagePrice` = ממוצע על `SMA` נרות (רזולוציית tick/דקה); `averagePriceQuarter` = ממוצע על `longSMA` נרות של **רבע-שעה (15ד')** — זו ה-MA של אסטרטגיית 10.
- **`dynamicDirection`** (`FutureTrader:84-100`): אם `direction>1` → הכיוון נקבע דינמית: `direction==2` ⇒ לונג כשמעל ה-MA (`averagePriceQuarter(longSMA)`), אחרת לונג כשמתחת. זהו "מתג כיוון-MA" שזמין לכל אסטרטגיות העתידיים (לא רק 10).

---

## bot_type_id = 1 — `OrderPlacer` (גריד ספוט דו-צדדי)

**קובץ:** `Workers/PlaceOrders.ts` · **אב:** `BasePlacer` · **שוק:** ספוט (buy/sell של node-binance).

### רעיון
Market-maker / גריד ספוט: בכל איטרציה מציב גם הזמנת קנייה וגם הזמנת מכירה סביב ספר ההזמנות, עם פיצול (`split`) למספר הזמנות-משנה במרחקים קבועים, ומיצוע מרטינגייל (`increase_factor`) כשהמגמה ממשיכה לאותו כיוון. למעשה צובר במורד, מוכר במעלה.

### לוגיקה (`place` → `calculatePrice` → `split`)
1. **מחיר בסיס:** `buyPrice` מצד הביד (או אסק אם `buy_side=='sell'`) כפול `(1-buy_percent)`; `sellPrice` מצד האסק כפול `(1+sell_percent)`.
2. **מרחק מהקנייה האחרונה:** אם הייתה קנייה לאחרונה (תוך `last_distance_minutes`) → `buyPrice = min(buyPrice, lastBuy*(1-last_distance))`. `last_buy_dist` תוקע תקרת מכירה ביחס לקנייה האחרונה.
3. **Stop-loss ספוט:** אם `minSellPrice < lastBuy*(1-stop_loose)` → מוכר ב-market (`sellPrice=minSellPrice`).
4. **תקרת SMA:** `maxBuyPrice = min(maxBuyPrice, averagePrice(SMA))` — לא קונה מעל הממוצע; `minSellPrice = max(..., averagePrice(SMA))` — לא מוכר מתחתיו (mean-reversion).
5. **פיצול (`split`)** (`:100-126`): מחלק את הכמות ל-`divide_buy`/`divide_sell` הזמנות-משנה. `qu /= 2^(divide-1)` ואז בכל צעד `qu *= 2`, והמחיר זז ב-`diffrent_buy`/`diffrent_sell` — סולם הזמנות מרטינגייל (כל הזמנה כפולה מקודמתה). `increase_factor^(רצף עסקאות באותו צד)` מגדיל את הבסיס.

### פרמטרים
| פרמטר | משמעות |
|--------|--------|
| `buy_side`/`sell_side` | מאיזה צד בספר ('sell'=אסק, אחרת ביד) |
| `buy_percent`/`sell_percent` | אופסט מהמחיר בספר |
| `amount_percent`/`amount_percent_sell` | גודל קנייה/מכירה (חלק מהיתרה) |
| `divide_buy`/`divide_sell` | לכמה הזמנות-משנה לפצל |
| `diffrent_buy`/`diffrent_sell` | מרווח בין הזמנות-משנה |
| `increase_factor` | מקדם מרטינגייל לפי רצף עסקאות |
| `last_distance`/`last_distance_minutes`/`last_buy_dist` | מרחק/חלון זמן מהעסקה האחרונה |
| `stop_loose` | סטופ ספוט (מכירת market) |
| `SMA` | חלון הממוצע לחסימת קנייה/מכירה |

### רלוונטיות ל-backtest
תלוי **עומק ספר הזמנות** (bids/asks) שאין לנו היסטורית. ניתן לקירוב גס בלבד (מילוי במחיר). אסטרטגיית-ספוט צבירה — לא בעדיפות הסריקה.

---

## bot_type_id = 2 — `WeightAvg` (DCA ממוצע-משוקלל, ספוט)

**קובץ:** `Workers/WeightAvg.ts` · **אב:** `BasePlacer` · **שוק:** ספוט.

### רעיון
DCA קלאסי של מיצוע-כלפי-מטה: קונה מנה, ואם המחיר יורד קונה עוד (כמות גדלה ב-`increase_factor`), וכך הממוצע יורד. כל מנה נמכרת ב-`+take_profit` מעל מחיר הקנייה שלה. וריאנט "אלגו חדש" (`take_profit_position==-1`) ממזג את המנה הישנה והעומדת ל-TP משוקלל אחד.

### לוגיקה
- **כניסה (`placeBuy`):** `fbuyPrice = maxBuyPrice*(1-buy_percent)`. אם ראשונה → קנייה ב-`fbuyPrice`. אם המנה האחרונה הייתה מכירה → `min(lastOrder*(1-take_profit), fbuyPrice)`. אחרת (המשך מיצוע) → `min(lastOrder*(1-last_distance), fbuyPrice)`. אם `SMA` מוגדר → תקרת ממוצע. כמות: ראשונה = `יתרה*amount_percent/buyPrice`; המשך = `lastOrder.origQty*(1+increase_factor)` (מרטינגייל).
- **יציאה (`placeSell`):** מוכר את ה-`standingBuy` ב-`price*(1+take_profit)`; את היתרה ב-`myLastBuyAvg*(1+take_profit_position||take_profit)`. בוריאנט החדש ממזג oldest+standing למחיר משוקלל.
- **SL:** קוד ה-stop_loose **מנוטרל (מוערות)** בספוט — אין סטופ אמיתי כאן.

### פרמטרים
`buy_percent`, `take_profit`, `take_profit_position` (=-1 מפעיל וריאנט חדש), `last_distance`, `increase_factor`, `amount_percent`, `SMA`.

### רלוונטיות ל-backtest
תלוי ספר-הזמנות פחות מ-1, אך עדיין ספוט-צבירה ללא סטופ → אסטרטגיה "תמיד-לונג צוברת". ניתנת לקירוב על מחיר. עדיפות נמוכה.

---

## bot_type_id = 3 — `FutureTrader` (אב העתידיים: DCA ממונף + TP/SL)

**קובץ:** `Workers/FuturesTrader.ts` · **אב:** `BasePlacer` · **שוק:** עתידיים. **זו הליבה שכל 4,5,7,8,9,10 יורשים ממנה.**

### רעיון
סוחר עתידיים ממונף שממצע פוזיציה (DCA/מרטינגייל), עם **TP יחיד** ב-`+take_profit`, **SL קשיח** ב-`-stop_loose`, trailing-stop אופציונלי (`callbackRate`), ובחירת-כיוון אופציונלית לפי MA (`dynamicDirection`).

### לוגיקה
- **`place` (:21-56):** מחשב פוזיציה נוכחית → כיוון → היסטוריה → בודק pause → `placeBuy` → אם יש פוזיציה `placeSell`.
- **כניסה (`placeBuy` :153-215):**
  - ראשונה: `markPrice*(1-buy_percent)`, סימון `FIRST`.
  - אחרי מכירה (TP מולא): כניסה מחדש ב-`lastSell.avgPrice*(1-take_profit)`.
  - המשך מיצוע: `lastOrder.avgPrice*(1-last_distance)`. **מפסיק למצע אם `amount_percent>0.9`.**
  - `buyPrice = minFunc(fbuyPrice, averagePrice(SMA), markPrice)` — לא קונה מעל הממוצע/המחיר.
  - גודל: ראשונה = `balanceLeveraged*amount_percent*increase_first/buyPrice`; המשך = `lastOrder.qty*(1+increase_factor)` (מרטינגייל), חסום ביתרה הפנויה.
- **יציאה (`placeSell` :217-302):**
  - TP יחיד: `entry*(1+take_profit)` כ-`TAKE_PROFIT_MARKET closePosition` (או `TRAILING_STOP_MARKET` אם `callbackRate`).
  - SL: `entry*(1-stop_loose)` כ-`STOP_MARKET closePosition`.
  - אם יש `standingBuy`+`sellAdded` → מוכר מנה בודדת מהקנייה (`placeSellFromBuy`).
- **כיוון דינמי (`calculateDirection` :84-100):** אם `direction>1` → לונג/שורט לפי `markPrice` מול `averagePriceQuarter(longSMA)`.
- **Pause (`checkForPause` :102-115):** אחרי `LAST-SL` ממתין `pause` שניות (קירור).

### פרמטרים
`leverage`, `amount_percent`, `take_profit`, `stop_loose`, `buy_percent`, `last_distance`, `increase_factor`, `increase_first`, `callbackRate`, `SMA`, `longSMA` (לכיוון דינמי), `direction`/`dynamicDirection`, `pause`, `take_profit_position`, `multiassets`, `sellAdded`.

### חוזקה/חולשה (תקציר)
מנוע גמיש מאוד. ברירת-מחדל בלי `dynamicDirection` ובלי direction = **תמיד-לונג עם מיצוע מרטינגייל** — מסוכן בדובי ממושך (מיצוע לתוך נפילה + מינוף). `dynamicDirection` הופך אותו לעוקב-מגמה דו-כיווני (קרוב ברוחו ל-MA-crossover אך עם מיצוע ו-TP יחיד).

---

## bot_type_id = 4 — `DualBot` (ליבה גדולה + מיצוע, סוגריים סימטריים)

**קובץ:** `Workers/DualBot.ts` · **אב:** `FutureTrader`.

### רעיון
פותח **פוזיציית-ליבה גדולה** (`BigPosition`, market, `bigPosition` חלק מהיתרה) ואז ממצע מעליה (`super.placeBuy`). היציאה היא **סוגריים סימטריים** סביב מחיר הכניסה הממוצע של הליבה.

### לוגיקה
- **`placeBuy` (:10-22):** אם אין פוזיציה → market בגודל `balanceLeveraged*bigPosition` עם clientOrderId `BigPosition` → ואז `super.placeBuy()` (המיצוע הרגיל).
- **`placeSell` (:68-109):** מאתר את ה-BigPosition. TP ב-`bigPosition.avgPrice*(1+take_profit_position)` ו-SL ב-`bigPosition.avgPrice*(1-take_profit_position)` — **אותו אחוז לשני הכיוונים** (סוגריים סימטריים), שניהם closePosition. אם יש `standingBuy`+`sellAdded` מוכר מנה בודדת קודם.

### פרמטרים
`bigPosition` (גודל הליבה), `take_profit_position` (חצי-רוחב הסוגריים), + כל פרמטרי `FutureTrader` (leverage, amount_percent, last_distance, increase_factor...).

### רלוונטיות ל-backtest
backtest-able. "Dual" = הרצת צד LONG וצד SHORT במקביל (positionSide מפורש). בלי כיוון דינמי — מהמר על mean-reversion סביב מחיר הליבה.

---

## bot_type_id = 5 — `DirectionTrader` (סטראדל פריצה דו-כיווני)

**קובץ:** `Workers/DirectionTrader.ts` · **אב:** `FutureTrader`.

### רעיון
**סטראדל פריצה:** כשאין פוזיציה מציב שתי הזמנות-stop — BUY-stop מעל וSELL-stop מתחת. מי שנפרץ ראשון קובע כיוון. בפוזיציה: trailing-stop שמתהפך (כמות ×2) ו-stop להיפוך — רוכב על המגמה ומתהפך בקצה.

### לוגיקה
- **`place` (:8-40):** אם flat → `setDirection(false)`+`placeBuy` (לונג-stop), ואז `setDirection(true)`+`placeBuy` (שורט-stop). אם בפוזיציה → `placeSell`.
- **`placeBuy` (:45-64):** `buyPrice = markPrice*(1+buy_percent)` (ראשונה) או `lastOrder*(1+last_distance)`; הזמנת `STOP_MARKET` ב-`max(buyPrice, markPrice)`.
- **`placeSell` (:66-94):** `TRAILING_STOP_MARKET` בכמות **×2** (היפוך מלא) ב-`entry*(1+callbackRate/100)`; ו-`STOP_MARKET` ×2 ב-`entry*(1+take_profit)`. ב-error: SL ב-`entry*(1-stop_loose)`.

### פרמטרים
`buy_percent` (רוחב הסטראדל), `last_distance`, `callbackRate` (הפעלת trailing + סף היפוך), `take_profit`, `stop_loose`, `leverage`, `amount_percent`.

### רלוונטיות ל-backtest
backtest-able ומעניין — אסטרטגיית פריצה/מומנטום שונה מהותית מ-MA. מתאימה למשטר תנודתי/פורץ. דורשת מנוע נפרד (לוגיקת stop דו-כיוונית + היפוך ×2).

---

## bot_type_id = 6 — `Periodically` (DCA לפי זמן)

**קובץ:** `Workers/Periodically.ts` · **אב:** `WeightAvg` · **שוק:** ספוט.

### רעיון
DCA פשוט מבוסס-זמן: כל `seconds` קונה סכום קבוע (≈$12) בראש הספר, בתנאי שזו קנייה ראשונה או שהממוצע מעל המחיר (`myLastBuyAvg > maxBuyPrice`). יורש את מכירת ה-`WeightAvg`.

### לוגיקה
`placeOrder` (:21-26): `place_order(SECOND, 12/maxBuyPrice, maxBuyPrice, side)` כש-`side = isFirst || myLastBuyAvg > maxBuyPrice`.

### פרמטרים
`seconds` (תדירות), `amount_percent`, `take_profit` (מ-WeightAvg), `SMA`.

### רלוונטיות ל-backtest
DCA קלאסי — תמיד-לונג צובר לפי זמן. backtest-able בקלות אך תלוי-תקופה (במגמת-על עולה תמיד מנצח). עדיפות נמוכה כאסטרטגיה אקטיבית.

---

## bot_type_id = 7 — `SignalingPlacer` (עוקב-איתותים מטלגרם)

**קובץ:** `Workers/SignaligProcessor.ts` · **אב:** `FutureTrader`.

### רעיון
**Copy-trading:** מנתח הודעות איתות מערוצי טלגרם (regex לפורמטים ספציפיים) → `Signaling` עם מטבע, כיוון, טווח כניסה, **6 יעדי TP**, סטופ, מינוף. נכנס בכניסת האיתות, יוצא מדורג על 6 היעדים (חצי פוזיציה בכל יעד), סטופ מטפס ככל שיעדים נפגעים, וסוגר אחרי 3 ימים.

### לוגיקה
- `SignaligProcessor.proccessTextSignal`: התאמת regex → בניית Signaling → `placeOrders`.
- `SignalingPlacer.placeOrder` (:111-230): כניסת `FIRST` ב-`min(enter[0], price)`; יציאות `EXIT1..6` ב-`takeProfits[exitNum]` (חצי פוזיציה כל פעם); `LASTTP`/`LASTSL`. סטופ נע לפי `exitNum` (enter[1] → enter[0] → takeProfits[exitNum-2]). סגירה אחרי 3 ימים.

### פרמטרים
`signalings` (מערך איתותים — חובה), `direction`, `leverage`. הפרמטרים מגיעים **מהאיתות עצמו**, לא מהמשתמש.

### רלוונטיות ל-backtest
**לא backtest-able** — תלוי באיתותים חיצוניים מטלגרם שאינם נתון היסטורי. **מוחרג מהסריקה.** (נכלל בקטלוג לשלמות בלבד.)

---

## bot_type_id = 8 — `OneStep` (עסקת-סוגריים יחידה)

**קובץ:** `Workers/OneStep.ts` · **אב:** `FutureTrader`.

### רעיון
הגרסה הפשוטה ביותר: **כניסה אחת, TP אחד, SL אחד — בלי מיצוע ובלי הוספות.** "צעד אחד".

### לוגיקה
- **`placeBuy` (:8-42):** רק כשאין פוזיציה. `buyPrice = min(markPrice*(1-buy_percent), averagePrice(SMA))` — limit מתחת למחיר/הממוצע (mean-reversion entry).
- **`placeSell` (:44-74):** TP ב-`entry*(1+take_profit)` (`TAKE_PROFIT_MARKET closePosition`); SL ב-`entry*(1-stop_loose)` (`STOP_MARKET closePosition`).

### פרמטרים
`buy_percent` (עומק כניסת limit), `SMA`, `take_profit`, `stop_loose`, `leverage`, `amount_percent`, `direction`.

### רלוונטיות ל-backtest
backtest-able ונקי — עסקת bracket בודדת. ברירת-מחדל תמיד-לונג; עם `dynamicDirection` הופך לעוקב-מגמה bracket. נקודת-ייחוס טובה (baseline) למול MA. דורש מנוע פשוט.

---

## bot_type_id = 9 — `AviAlgo` (פורץ-מומנטום רב-חלונות)

**קובץ:** `Workers/AviAlgo.ts` · **אב:** `FutureTrader`.

### רעיון
זיהוי **פרץ-מומנטום** על נתוני מחיר ב-1 שנייה: מגדיר רצף "חלונות" (`levelsSeconds`/`levelsRaise`). אם **בכל** החלונות העוקבים השינוי ≥ סף → pump → LONG; אם בכולם ≤ -סף → dump → SHORT; אחרת אין עסקה. נכנס ב-stop ורוכב עם trailing-stop.

### לוגיקה
- **`parseLevels` (:60-75):** מפענח `levelsSeconds`/`levelsRaise` (CSV) ל-`LevelRaise[]` + `lastLevel`.
- **`placeFirstOrder` (:18-58):** עובר על החלונות; מחשב שינוי `(end-start)/start` בכל חלון; `pump` נשאר true רק אם כל חלון ≥ `raise`, `dump` רק אם כל חלון ≤ `-raise`. כיוון = `pump?LONG:dump?SHORT:-1`. אם -1 → לא נכנס. כניסה `STOP_MARKET` ב-`prices[0]*(1+lastLevel.raise)`.
- **`place` (:77-100):** אם flat → `placeFirstOrder`; אם בפוזיציה → `TRAILING_STOP_MARKET` ב-markPrice עם `callbackRate`.

### פרמטרים
`levelsSeconds` (חלונות זמן, CSV), `levelsRaise` (ספי שינוי %, CSV), `callbackRate` (trailing), `leverage`, `amount_percent`.

### רלוונטיות ל-backtest
backtest-able אך **דורש רזולוציה גבוהה (1ש'/1ד')** לזיהוי הפרץ. שונה מהותית מ-MA — מתאים למשטר ברייקאאוט/וולטילי. דורש מנוע נפרד (חלונות מומנטום + trailing).

---

## bot_type_id = 10 — `MovingAverages` (האלוף הידוע — לעיון)

**קובץ:** `Workers/MovingAverages.ts` · **אב:** `FutureTrader`. מתועד במלואו ב-`ENGINE_MECHANICS.md`/`ENGINE_V6_SPEC.md` + סקיל. בקצרה:
- כיוון לפי נר רבע-שעה מול `averagePriceQuarter(longSMA)`; `waitForClose` דורש שהנר הקודם חתך והנוכחי "ניקה" את ה-MA.
- כניסת market; סולם TP של `tp_count` מנות במרווחי `tp_difference`; SL ב-`stop_loose` שמטפס ל-MA אחרי `stopLooseTP` מנות; **reverse-on-cross**.
- פרמטרי-ניסוי שלנו (claude-experiments, no-op-by-default): `maxEntryDist` (שומר-קרבה-ל-MA), `seasonalLeverage` — ראו `experimentalParams.ts` + `ENGINE_EXPERIMENTAL_PARAMS.md`.

---

## סיכום: מה נכנס לסריקה (task 3-4)

| id | אסטרטגיה | סריקה? | סיבה |
|----|----------|--------|------|
| 1 | OrderPlacer | קירוב בלבד | תלוי ספר-הזמנות; ספוט-צבירה |
| 2 | WeightAvg | קירוב בלבד | DCA ספוט ללא סטופ |
| 3 | FutureTrader | **כן** | אב גמיש; עם dynamicDirection ≈ עוקב-מגמה ממונף |
| 4 | DualBot | **כן** | ליבה+מיצוע סימטרי |
| 5 | DirectionTrader | **כן (מנוע חדש)** | סטראדל פריצה — משטר שונה מ-MA |
| 6 | Periodically | קירוב בלבד | DCA-זמן תמיד-לונג |
| 7 | SignalingPlacer | **לא** | תלוי איתותים חיצוניים |
| 8 | OneStep | **כן** | bracket יחיד — baseline נקי |
| 9 | AviAlgo | **כן (מנוע חדש)** | פורץ-מומנטום — משטר שונה מ-MA |
| 10 | MovingAverages | (קיים) | האלוף הנוכחי |

**מועמדים עיקריים לסריקה כמותית:** 5 (DirectionTrader), 8 (OneStep), 9 (AviAlgo), 3/4 (FutureTrader/DualBot עם כיוון-MA). אלו מציעים *רעיונות-מסחר נבדלים* מ-MA: פריצה (5,9), bracket יחיד (8), ומיצוע ממונף (3,4) — בדיוק החומר לתיק-על רב-משטרי (task 6).
