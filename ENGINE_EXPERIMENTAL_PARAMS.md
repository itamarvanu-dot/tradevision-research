# מנוע — פרמטרים ניסיוניים (maxEntryDist, seasonalLeverage)

לימוד מנוע ה-MovingAverages לקרוא ולאכוף שני פרמטרים אופציונליים, **תוספתי בלבד**: כשהשדות
ריקים/לא-מוגדרים — ההתנהגות **זהה בדיוק** למקור (אין שינוי בלוגיקה הקיימת). ענף `claude-experiments`.

## מה נוסף
- **`maxEntryDist`** (מספר, שבר — 0.01 = 1%): שומר כניסות-רדופות. בכניסה, אם המחיר רחוק יותר מ-
  `maxEntryDist` מה-MA — הכניסה **מדולגת** (לא נפתחת פוזיציה). זה הלבן היחיד שעמד בבקרת-אקראי
  בניתוח (הקטין DD על ETH/XRP). ריק/≤0 = כבוי = התנהגות מקורית.
- **`seasonalLeverage`** (מחרוזת): לוח מינוף עונתי. תומך JSON (`{"6":1.5,"winter":2}`) או
  `key:value,key:value` (`summer:1,winter:2`). מפתחות = מספרי-חודש (1-12) או שמות-עונה
  (winter=12,1,2 / spring=3,4,5 / summer=6,7,8 / autumn|fall=9,10,11). חודש מפורש גובר על עונה.
  המינוף האפקטיבי = `leverage_base × multiplier(month)`. ריק/לא-תקין = מינוף סטטי = מקור.

## איפה ואיך (מינימלי)
- `Workers/experimentalParams.ts` — **מודול טהור, ללא תלויות** עם פונקציות:
  `exceedsMaxEntryDist`, `effectiveLeverage`, `seasonalMultiplier`, `parseSeasonalLeverage`.
  כולן מחזירות את **ערך-המקור המדויק** כשהפרמטר ריק (`exceedsMaxEntryDist→false`,
  `effectiveLeverage→baseLeverage`).
- `Workers/MovingAverages.ts` — שני call-sites ב-`manageEntryOrders` בלבד:
  1. גודל הפוזיציה משתמש ב-`effectiveLeverage(this.bot.leverage, this.bot.seasonalLeverage, month)`
     במקום `this.bot.leverage` (זהה כש-seasonalLeverage ריק).
  2. ענף-שמירה חדש `blockedByEntryGuard` *לפני* ענפי LONG/SHORT הקיימים; כש-maxEntryDist ריק
     הוא תמיד `false` (short-circuit) ולכן ענפי המקור רצים בדיוק כמו קודם.
  + helper `currentEntryMonth()` (חודש UTC מזמן הנר — דטרמיניסטי בסימולציה).
- `Models.ts` — נוספו שני שדות אופציונליים ל-`Bot` (`maxEntryDist?`, `seasonalLeverage?`).
  הם זורמים מהמסמך אל ה-Bot דרך ה-`Object.assign(new Bot(), simulation)` הקיים ב-`Simulator/Simulate.ts`
  (לא נדרש שינוי בטוען). לא מוגדר = undefined = התנהגות מקורית.

## הוכחת זהות (טסטים)
`__tests__/Workers/experimentalParams.test.ts` — **58 טסטים עוברים בכל החבילה** (14 חדשים).
מקטע "IDENTITY when fields are empty/undefined" מוכיח:
- `exceedsMaxEntryDist` מחזיר **false תמיד** עבור כל ערך ריק (undefined/null/0/-1/NaN) × כל מחיר/MA.
- `effectiveLeverage(base, ריק, חודש)` מחזיר **בדיוק `base`** עבור כל base וכל חודש (וגם לקלט לא-תקין).
ובנוסף נבדקת ההתנהגות כשהפרמטרים פעילים (סף מרחק סימטרי, פירוק JSON/k:v, שמות-עונה, חודש גובר על עונה).
המודול עובר `tsc --noEmit --strict` עצמאית.

## איך לאמת בפלטפורמה
מהאתר (הניסיוני או המקורי): ביצירת סימולציה למלא `maxEntryDist` (למשל 0.008–0.01) ו/או
`seasonalLeverage`. השדות נכתבים לכל variation; המנוע יקרא ויאכוף. להריץ קונפיג זהה עם ובלי
`maxEntryDist` ולהשוות עסקאות/DD — צריך לראות פחות עסקאות-רדופות ו-DD נמוך יותר, בלי שינוי בעסקאות
שלא היו רדופות. (אינטגרציית הפלטפורמה: השדות כבר נשמרים מ-CreateSimulationDialog בענף הניסיוני של tradingSite.)

## חוקי הברזל שנשמרו
לא נגעתי בלוגיקת המנוע הקיימת (זהות מוכחת כשריק), לא ב-main/firebase — רק ענף `claude-experiments`,
קבצים חדשים + 2 call-sites מינימליים + 2 שדות אופציונליים.
