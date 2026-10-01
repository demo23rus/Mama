(function () {
  "use strict";

  var API_BASE = "/api/miniapp";
  var ICONS = "assets/mama_3d_v1/icons/";
  var HERO = "assets/mama_3d_v2/hero/hero-welcome-3d.webp";
  // Home, Assistant and Trackers shortcuts use the v2 asset set; remaining screens keep v1 via ICONS.
  var ICONS_HOME = "assets/mama_3d_v2/icons/";
  // Pastel icon pack v1 (lighter WebP assets) — filenames are prefixed "mama_" so callers can tell
  // them apart from legacy "icon-*-3d.webp" assets and route to the right base path.
  var ICONS_EMBLEM = "assets/emblems/mama/";

  // Home: only quick core actions (day-to-day taps), no catalog/section links.
  var HOME_CARDS = [
    { key: "ai-question", title: "Вопрос специалисту", icon: "mama_specialist_light.webp", tone: "blue", action: { type: "ai-question" } },
    { key: "sleep", title: "Сон", icon: "mama_sleep_light.webp", tone: "pink", action: { type: "sleep-tracker" } },
    { key: "feeding", title: "Питание", icon: "mama_feeding_light.webp", tone: "blue", action: { type: "feeding-tracker" } },
    { key: "symptoms", title: "Самочувствие", icon: "mama_wellbeing_light.webp", tone: "pink", action: { type: "symptoms-tracker" } },
    { key: "mom-support", title: "Поддержка мамы", icon: "mama_mom_support_light.webp", tone: "blue", action: { type: "stub", stub: "mom-support" } }
  ];

  // Trackers: real/planned tracker sections only (logging & records), no consultation topics.
  var TRACKER_ITEMS = [
    { key: "sleep", title: "Сон", icon: "mama_sleep_light.webp", action: { type: "sleep-tracker" } },
    { key: "feeding", title: "Питание", icon: "mama_feeding_light.webp", action: { type: "feeding-tracker" } },
    { key: "symptoms", title: "Самочувствие", icon: "mama_wellbeing_light.webp", action: { type: "symptoms-tracker" } },
    { key: "growth", title: "Рост и вес", icon: "mama_growth_weight_light.webp", action: { type: "growth-tracker" } },
    { key: "vaccinations", title: "Прививки", icon: "mama_vaccines_light.webp", action: { type: "vaccines-tracker" } },
    { key: "baby-diary", title: "Дневник малыша", icon: "mama_baby_diary_light.webp", action: { type: "diary-tracker" } }
  ];

  // Assistant: consultation/AI topics only, no tracker logging.
  var ASSISTANT_SHORTCUTS = [
    { key: "emergency", title: "Экстренная помощь", icon: "mama_emergency_light.webp", action: { type: "emergency" } },
    { key: "tantrum", title: "Истерики и эмоции", icon: "mama_tantrums_emotions_light.webp", action: { type: "tantrum-emotions" } },
    { key: "kindergarten", title: "Садик", icon: "mama_kindergarten_light.webp", action: { type: "kindergarten" } },
    { key: "school", title: "Школа", icon: "mama_school_light.webp", action: { type: "school" } },
    { key: "mom-support", title: "Поддержка мамы", icon: "mama_mom_support_light.webp", action: { type: "stub", stub: "mom-support" } },
    { key: "ai-question", title: "Вопрос специалисту", icon: "mama_specialist_light.webp", action: { type: "ai-question" } },
    { key: "child", title: "Ребёнок", icon: "mama_child_light.webp", action: { type: "child-hub" } },
    { key: "photo-analysis", title: "Фотоанализ", icon: "mama_photo_analysis_light.webp", action: { type: "photo-analysis" } }
  ];

  // ===== Фотоанализ (реальный сценарий photo_menu/photo_analysis/photo_uzi/photo_med_preg/
  // photo_skin/photo_stool/photo_food/photo_package/handle_photo из mama_bot.py, через единый
  // POST /api/miniapp/photo/analyze — та же двухступенчатая проверка соответствия фото типу и
  // те же формулировки и safety-дисклеймеры, что в Telegram). =====
  var MINIAPP_PHOTO_MAX_BYTES = 8 * 1024 * 1024;
  var PHOTO_ANALYSIS_TYPES = [
    { key: "analysis", title: "Анализы", sub: "Результаты лабораторных анализов", icon: "mama_photo_labs_light.webp", hint: "Отправь фото результатов анализов. Я расшифрую показатели понятным языком.\n⚠️ Интерпретацию подтверждает только врач." },
    { key: "uzi", title: "УЗИ", sub: "Заключение УЗИ", icon: "mama_photo_ultrasound_light.webp", hint: "Отправь фото заключения УЗИ. Я объясню показатели понятным языком.\n⚠️ Интерпретацию подтверждает только врач." },
    { key: "med_preg", title: "Лекарство при беременности", sub: "Можно ли принимать при беременности", icon: "mama_photo_medicine_pregnancy_light.webp", hint: "Отправь фото упаковки лекарства. Я скажу можно ли его принимать при беременности.\n⚠️ Решение принимает только врач." },
    { key: "skin", title: "Сыпь / кожа", sub: "Кожа или сыпь малыша", icon: "mama_photo_skin_rash_light.webp", hint: "Отправь фото кожи или сыпи малыша. Я опишу что вижу и подскажу на что это похоже.\n⚠️ Это не замена осмотру педиатра — только ориентир." },
    { key: "stool", title: "Стул малыша", sub: "Цвет и консистенция стула", icon: "mama_photo_baby_stool_light.webp", hint: "Отправь фото стула малыша. Я оценю цвет и консистенцию — это важный показатель здоровья.\n⚠️ При любых сомнениях — к педиатру." },
    { key: "food", title: "Еда", sub: "Подходит ли еда по возрасту малыша", icon: "mama_food_photoanalysis_light.webp", hint: "Отправь фото еды или блюда. Я скажу подходит ли это по возрасту малыша." },
    { key: "package", title: "Упаковка смеси", sub: "Состав смеси или лекарства", icon: "mama_photo_formula_package_light.webp", hint: "Отправь фото упаковки смеси или лекарства. Я расшифрую состав и скажу на что обратить внимание." }
  ];

  var STUBS = {
    "mom-support": { title: "Поддержка мамы", icon: "mama_mom_support_light.webp" },
    growth: { title: "Рост и вес", icon: "icon-symptoms-3d.webp" },
    "baby-diary": { title: "Дневник малыша", icon: "mama_history_light.webp" }
  };

  // ===== Поддержать проект (реальный donate/support-flow, эквивалент donate_menu из
  // mama_bot.py/mama_max_bot.py) — суммы и границы своей суммы совпадают с Telegram/MAX ботами. =====
  var DONATE_AMOUNTS = [
    { amount: 99, variant: "99", label: "99 ₽ — Сказать спасибо" },
    { amount: 199, variant: "199", label: "199 ₽ — Поддержать развитие" },
    { amount: 499, variant: "499", label: "499 ₽ — Большое спасибо" },
    { amount: 990, variant: "990", label: "990 ₽ — Помочь проекту расти" }
  ];
  var DONATE_MIN_AMOUNT = 10;
  var DONATE_MAX_AMOUNT = 100000;

  var SCHOOL_TOPIC_PREFIX = "Тема: Школа (адаптация, уроки, оценки, тревожность, отношения с учителем и одноклассниками). Вопрос: ";

  var TANTRUM_EMOTIONS_OPTIONS = [
    { key: "tantrum", title: "Истерики ребёнка", sub: "Почему это происходит и что делать прямо сейчас", icon: "mama_child_tantrum_light.webp", endpoint: "/tantrums" },
    { key: "emotions", title: "Эмоции мамы", sub: "Поддержка, выгорание и тревожность — с научной точки зрения", icon: "mama_mom_psychologist_light.webp", endpoint: "/emotions" }
  ];

  var BREASTFEEDING_OPTIONS = [
    { key: "start", title: "Начало ГВ", sub: "Первое прикладывание, захват груди, позиции, признаки хватает ли молока", icon: "mama_breastfeeding_light.webp", endpoint: "/content/breastfeeding?topic=start" },
    { key: "pump", title: "Сцеживание", sub: "Как увеличить лактацию и правильно расцедить", icon: "mama_breastfeeding_light.webp", endpoint: "/content/breastfeeding?topic=pump" },
    { key: "lactostaz", title: "Лактостаз", sub: "Уплотнения, первая помощь, когда срочно к врачу", icon: "mama_breastfeeding_light.webp", endpoint: "/content/breastfeeding?topic=lactostaz" },
    { key: "food", title: "Питание мамы", sub: "Что есть и пить при ГВ по рекомендациям ВОЗ", icon: "mama_breastfeeding_light.webp", endpoint: "/content/breastfeeding?topic=food" },
    { key: "nofood", title: "Что нельзя при ГВ", sub: "Алкоголь, кофеин, лекарства — и популярные мифы", icon: "mama_breastfeeding_light.webp", endpoint: "/content/breastfeeding?topic=nofood" },
    { key: "formula", title: "Смесь и докорм", sub: "Переход на смесь и смешанное вскармливание без чувства вины", icon: "mama_breastfeeding_light.webp", endpoint: "/content/breastfeeding?topic=formula" }
  ];

  var RECOVERY_OPTIONS = [
    { key: "natural", title: "После естественных родов", sub: "Первые сутки, швы, лохии, восстановление матки, когда вставать и ходить", icon: "mama_mom_recovery_light.webp", endpoint: "/content/recovery?topic=natural" },
    { key: "caesar", title: "После кесарева", sub: "Уход за швом, ограничения, обезболивание, восстановление тканей", icon: "mama_mom_recovery_light.webp", endpoint: "/content/recovery?topic=caesar" },
    { key: "sport", title: "Возвращение к спорту", sub: "Кегель, диастаз, постепенный план по неделям и месяцам", icon: "mama_mom_recovery_light.webp", endpoint: "/content/recovery?topic=sport" },
    { key: "intimate", title: "Интимная жизнь", sub: "Когда можно, дискомфорт, контрацепция при ГВ — деликатно и по науке", icon: "mama_mom_recovery_light.webp", endpoint: "/content/recovery?topic=intimate" },
    { key: "hair", title: "Волосы и восстановление", sub: "Почему выпадают волосы после родов и что реально помогает", icon: "mama_mom_recovery_light.webp", endpoint: "/content/recovery?topic=hair" },
    { key: "diastaz", title: "Диастаз", sub: "Самопроверка, запрещённые и полезные упражнения, бандаж", icon: "mama_mom_recovery_light.webp", endpoint: "/content/recovery?topic=diastaz" }
  ];

  // ===== Ребёнок (каталог в «Помощник») — те же 14 сценариев mama_dev/mama_games/
  // mama_games_more/mama_books/mama_books_more/mama_health/mama_meds/mama_teeth/mama_food/
  // mama_recipes/mama_recipes_more/mama_routine/mama_sleep/mama_family из Telegram, через единый
  // GET /content/child?topic=. "games"/"books"/"recipes" дополнительно имеют moreEndpoint —
  // кнопка "Ещё" вызывает *_more (games_more/books_more/recipes_more), как в Telegram.
  // "sleep" — контентный AI-раздел "Сон ребёнка" (не путать с трекером «Сон» на Home/Трекерах).
  var CHILD_OPTIONS = [
    { key: "development", title: "Развитие", icon: "mama_games_development_light.webp", endpoint: "/content/child?topic=development" },
    { key: "games", title: "Игры", icon: "mama_games_development_light.webp", endpoint: "/content/child?topic=games", moreEndpoint: "/content/child?topic=games_more" },
    { key: "books", title: "Книги", icon: "mama_books_light.webp", endpoint: "/content/child?topic=books", moreEndpoint: "/content/child?topic=books_more" },
    { key: "health", title: "Здоровье", icon: "mama_health_light.webp", endpoint: "/content/child?topic=health" },
    { key: "meds", title: "Лекарства", icon: "mama_medicines_light.webp", endpoint: "/content/child?topic=meds" },
    { key: "teeth", title: "Зубы", icon: "mama_teeth_light.webp", endpoint: "/content/child?topic=teeth" },
    { key: "food", title: "Питание", icon: "mama_feeding_light.webp", endpoint: "/content/child?topic=food" },
    { key: "recipes", title: "Рецепты", icon: "mama_recipes_light.webp", endpoint: "/content/child?topic=recipes", moreEndpoint: "/content/child?topic=recipes_more" },
    { key: "routine", title: "Режим дня", icon: "mama_sleep_routine_light.webp", endpoint: "/content/child?topic=routine" },
    { key: "sleep", title: "Сон ребёнка", icon: "mama_sleep_light.webp", endpoint: "/content/child?topic=sleep" },
    { key: "family", title: "Семья", icon: "mama_family_light.webp", endpoint: "/content/child?topic=family" },
    { key: "firstdays", title: "Первые дни с малышом", icon: "mama_first_days_light.webp", screen: "firstdays-hub" }
  ];

  // ===== Первые дни с малышом (хаб в каталоге «Ребёнок») — те же сценарии fd_pediatr/fd_doctors/
  // fd_svid/fd_massage/fd_swim из mama_bot.py (Telegram), через единый GET /content/firstdays?topic=.
  // "sadik" НЕ дублирует fd_sadik — ведёт на уже рабочий экран "kindergarten"
  // (/api/miniapp/kindergarten), как в Telegram-каталоге "Первые дни с малышом".
  var FIRSTDAYS_OPTIONS = [
    { key: "pediatrician", title: "Педиатр", icon: "mama_pediatrician_light.webp", endpoint: "/content/firstdays?topic=pediatrician" },
    { key: "doctors", title: "Врачи по месяцам", icon: "mama_doctors_monthly_light.webp", endpoint: "/content/firstdays?topic=doctors" },
    { key: "documents", title: "Документы и свидетельство", icon: "mama_documents_light.webp", endpoint: "/content/firstdays?topic=documents" },
    { key: "sadik", title: "Садик", icon: "mama_kindergarten_light.webp", screen: "kindergarten" },
    { key: "massage", title: "Массаж", icon: "mama_massage_light.webp", endpoint: "/content/firstdays?topic=massage" },
    { key: "swimming", title: "Плавание", icon: "mama_swimming_light.webp", endpoint: "/content/firstdays?topic=swimming" }
  ];

  // Первые 6 — единый GET /content/benefits?topic=, последний ("personal") — POST /benefits/personal
  // с текстовым полем, как ben_personal/ben_personal_answer в Telegram.
  var BENEFITS_OPTIONS = [
    { key: "birth", title: "При рождении ребёнка", sub: "Единовременное пособие — размер, документы, сроки", icon: "mama_benefits_light.webp", endpoint: "/content/benefits?topic=birth" },
    { key: "15", title: "До 1,5 лет", sub: "Ежемесячное пособие по уходу за ребёнком", icon: "mama_benefits_light.webp", endpoint: "/content/benefits?topic=15" },
    { key: "3", title: "До 3 лет", sub: "Путинские выплаты и региональные пособия", icon: "mama_benefits_light.webp", endpoint: "/content/benefits?topic=3" },
    { key: "matcap", title: "Материнский капитал", sub: "Размер, на что потратить, как оформить через Госуслуги", icon: "mama_benefits_light.webp", endpoint: "/content/benefits?topic=matcap" },
    { key: "decree", title: "Декретные выплаты", sub: "Пособие по беременности и родам", icon: "mama_benefits_light.webp", endpoint: "/content/benefits?topic=decree" },
    { key: "multi", title: "Многодетная семья", sub: "Федеральные и региональные льготы многодетным", icon: "mama_benefits_light.webp", endpoint: "/content/benefits?topic=multi" },
    { key: "personal", title: "Персональный разбор", sub: "Опиши ситуацию — подберём все положенные выплаты", icon: "mama_benefits_light.webp" }
  ];

  // ===== Беременность (preg_week/preg_baby/preg_checklist/preg_shop из mama_bot.py) =====
  // "week" — реальный расчёт срока (не AI), остальные три — тот же OpenAI pipeline,
  // что и в Telegram-сценариях, через единый GET /pregnancy/<key>.
  var PREGNANCY_OPTIONS = [
    { key: "week", title: "Мой срок", sub: "Текущая неделя беременности и триместр", icon: "mama_pregnancy_light.webp", endpoint: "/pregnancy/week" },
    { key: "baby", title: "Как развивается малыш", sub: "Размер, органы, сенсорное и нейроразвитие на этой неделе", icon: "mama_pregnancy_light.webp", endpoint: "/pregnancy/baby" },
    { key: "checklist", title: "Чек-лист", sub: "Анализы, визиты к врачу и что сделать на этом сроке", icon: "mama_pregnancy_light.webp", endpoint: "/pregnancy/checklist" },
    { key: "shop", title: "Что купить", sub: "Список покупок для мамы, роддома и малыша", icon: "mama_pregnancy_light.webp", endpoint: "/pregnancy/shop" }
  ];

  var HISTORY_FILTERS = [
    { key: "", label: "Все" },
    { key: "sleep", label: "Сон" },
    { key: "feeding", label: "Питание" },
    { key: "symptoms", label: "Самочувствие" },
    { key: "diary", label: "Дневник" },
    { key: "growth", label: "Рост" },
    { key: "vaccines", label: "Прививки" }
  ];

  var PERSONAL_REVIEW_PRICE = 690;

  // ===== Поддержка мамы: хаб разделов (cat_mom в mama_bot.py) =====
  // "mom-emotions" уже работает через /api/miniapp/emotions (mama_emotions).
  // "breastfeeding" работает через /api/miniapp/content/breastfeeding (bf_start/bf_pump/bf_lactostaz/bf_food/bf_nofood/bf_formula).
  // "recovery" работает через /api/miniapp/content/recovery (rec_natural/rec_caesar/rec_sport/rec_intimate/rec_hair/rec_diastaz).
  // "benefits" работает через /api/miniapp/content/benefits (ben_birth/ben_15/ben_3/ben_matcap/ben_decree/ben_multi)
  // и /api/miniapp/benefits/personal (ben_personal/ben_personal_answer).
  // Остальные разделы: backend ещё не перенесён — pending-экран называет конкретную функцию mama_bot.py.
  var MOM_SUPPORT_SECTIONS = [
    { key: "mom-emotions", title: "Эмоции мамы", sub: "Послеродовая депрессия, выгорание, тревожность — с научной точки зрения", icon: "mama_mom_psychologist_light.webp", screen: "mom-emotions" },
    { key: "breastfeeding", title: "Грудное вскармливание", sub: "Захват груди, режим кормлений, лактостаз, питание при ГВ", icon: "mama_breastfeeding_light.webp", screen: "breastfeeding" },
    { key: "recovery", title: "Восстановление мамы", sub: "Здоровье и восстановление организма после родов", icon: "mama_mom_recovery_light.webp", screen: "recovery" },
    { key: "psycho", title: "Мамин психолог", sub: "Личный разговор о твоём состоянии", icon: "mama_mom_psychologist_light.webp", screen: "psycho-chat" },
    { key: "benefits", title: "Пособия и выплаты", sub: "Какие выплаты положены и как их оформить", icon: "mama_benefits_light.webp", screen: "benefits" },
    { key: "personal-review", title: "Личный разбор ситуации", sub: "Автор проекта лично изучит ситуацию и запишет подробный голосовой ответ", icon: "mama_personal_review_light.webp", screen: "pr-form", price: PERSONAL_REVIEW_PRICE }
  ];

  var CHANNEL_URL = "https://t.me/yamama_ai";
  var MINIAPP_ASK_QUESTION_MAX_LEN = 2000;
  var MINIAPP_SYMPTOM_MAX_LEN = 500;
  var MINIAPP_DIARY_MAX_LEN = 2000;
  var MINIAPP_PSYCHO_MAX_LEN = 2000;
  var MINIAPP_EMERGENCY_MAX_LEN = 2000;
  var MINIAPP_FEEDBACK_MAX_LEN = 3000;

  // ===== Обратная связь (перенос support_menu/support_write/review_write/suggestion_write
  // из mama_bot.py) через /api/miniapp/feedback/{support,review,suggestion} =====
  var FEEDBACK_TOPICS = [
    { key: "support", title: "Написать в поддержку", sub: "Опиши проблему — команда поддержки ответит в ближайшее время", icon: "mama_feedback_light.webp", endpoint: "/feedback/support", placeholder: "Опиши проблему подробно" },
    { key: "review", title: "Оставить отзыв", sub: "Расскажи, что нравится или что можно улучшить", icon: "mama_feedback_light.webp", endpoint: "/feedback/review", placeholder: "Напиши свой отзыв о боте" },
    { key: "suggestion", title: "Предложить идею", sub: "Что добавить или улучшить в Мамином помощнике", icon: "mama_feedback_light.webp", endpoint: "/feedback/suggestion", placeholder: "Напиши свою идею — что добавить или улучшить" }
  ];

  var SAFETY_KEYWORDS = [
    "суицид", "самоубийств", "покончить с собой", "покончу с собой", "не хочу жить",
    "хочу умереть", "убить себя", "убью себя", "причиню вред ребен", "причиню себе вред",
    "изобьет", "изобью", "избивает", "избил", "ударил ребен", "ударила ребен",
    "насилие над ребен", "домашнее насилие", "жестокое обращение", "угрожает жизни",
    "нет сил жить", "хочу навредить"
  ];

  function hasSafetyRisk(text) {
    var t = (text || "").toLowerCase();
    return SAFETY_KEYWORDS.some(function (kw) { return t.indexOf(kw) !== -1; });
  }

  var state = {
    screen: "home",
    historyFilter: "",
    stubKey: null,
    momPendingKey: null,
    today: { loading: true, error: "", notApplicable: false, data: null, advice: { loading: false, error: "", answer: "" } },
    momEmotions: { loading: false, error: "", answer: "" },
    psychoChat: {
      items: [],
      loaded: false,
      loading: false,
      loadError: "",
      text: "",
      sending: false,
      sendError: "",
      clearConfirm: false,
      clearLoading: false,
      clearError: ""
    },
    prForm: { situation_text: "", preferred_reply: "telegram", email: "", consent: false, disclaimer_ack: false },
    prReviewId: null,
    prStatusTimer: null,
    donate: { phase: "pick", amount: null, variant: null, customInput: "", customError: "", payLoading: false, payError: "" },
    aiQuestionFrom: "home",
    aiQuestion: { text: "", answer: "", loading: false, error: "" },
    schoolFrom: "home",
    school: { text: "", answer: "", loading: false, error: "" },
    tantrumEmotionsFrom: "assistant",
    tantrumEmotions: { choice: null, loading: false, error: "", answer: "" },
    breastfeeding: { choice: null, loading: false, error: "", answer: "" },
    recovery: { choice: null, loading: false, error: "", answer: "" },
    childHubFrom: "assistant",
    child: { choice: null, loading: false, error: "", answer: "", moreLoading: false, moreError: "" },
    firstdays: { choice: null, loading: false, error: "", answer: "" },
    pregnancy: { loading: true, notApplicable: false, loadError: "", weeks: null, days: null, weeksText: "", choice: null, choiceLoading: false, choiceError: "", answer: "" },
    benefits: { choice: null, loading: false, error: "", answer: "", personalText: "", personalAnswer: "", personalLoading: false, personalError: "" },
    kindergartenFrom: "assistant",
    kindergarten: { loading: false, error: "", answer: "" },
    feedback: { kind: null, text: "", loading: false, error: "", success: false, successMessage: "" },
    resetMe: { confirm: false, loading: false, error: "", success: false },
    emergencyFrom: "assistant",
    emergency: {
      loading: false,
      loaded: false,
      loadError: "",
      intro: "",
      footer: "",
      guides: [],
      view: "list",
      guideKey: null,
      other: { text: "", answer: "", loading: false, error: "" }
    },
    photoAnalysisFrom: "assistant",
    photoAnalysis: { type: null, fileName: "", previewUrl: "", file: null, loading: false, error: "", answer: "", match: null, message: "" },
    sleepTrackerFrom: "home",
    sleepTracker: {
      entries: [],
      entriesLoading: false,
      entriesError: "",
      actionLoading: null,
      actionError: "",
      actionMessage: "",
      analyzeLoading: false,
      analyzeError: "",
      analyzeAnswer: ""
    },
    feedingTrackerFrom: "home",
    feedingTracker: {
      side: null,
      duration: "",
      saveLoading: false,
      saveError: "",
      saveMessage: "",
      entries: [],
      entriesLoading: false,
      entriesError: "",
      analyzeLoading: false,
      analyzeError: "",
      analyzeAnswer: ""
    },
    symptomsTrackerFrom: "home",
    symptomsTracker: {
      text: "",
      saveLoading: false,
      saveError: "",
      saveMessage: "",
      entries: [],
      entriesLoading: false,
      entriesError: "",
      analyzeLoading: false,
      analyzeError: "",
      analyzeAnswer: ""
    },
    diaryTrackerFrom: "trackers",
    diaryTracker: {
      text: "",
      saveLoading: false,
      saveError: "",
      saveMessage: "",
      entries: [],
      entriesLoading: false,
      entriesError: ""
    },
    growthTrackerFrom: "home",
    growthTracker: {
      height: "",
      weight: "",
      saveLoading: false,
      saveError: "",
      saveMessage: "",
      entries: [],
      entriesLoading: false,
      entriesError: "",
      analyzeLoading: false,
      analyzeError: "",
      analyzeAnswer: ""
    },
    vaccinesTrackerFrom: "home",
    vaccinesTracker: {
      items: [],
      itemsLoading: false,
      itemsError: "",
      createLoading: false,
      createError: "",
      createMessage: "",
      doneLoadingId: null,
      doneError: "",
      infoOpenId: null,
      infoLoading: false,
      infoError: "",
      infoAnswer: ""
    },
    cfFrom: "feeding-tracker",
    cf: {
      view: "hub",
      catalog: null,
      catalogLoading: false,
      catalogError: "",
      my: null,
      myLoading: false,
      myError: "",
      ageTier: null,
      openCategory: null,
      openFood: null,
      markLoadingKey: null,
      markErrorKey: "",
      markError: "",
      reactionDraft: {}
    }
  };

  function esc(value) {
    var div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
  }

  // ===== Platform adapter (Telegram WebApp / MAX WebApp) =====
  // Единая точка platform-specific кода: остальной app.js работает только через Platform.*,
  // не обращаясь к window.Telegram/window.WebApp напрямую.
  var Platform = (function () {
    var tgApp = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
    var maxApp = window.WebApp || null;
    var hash = window.location.hash.indexOf("#") === 0 ? window.location.hash.slice(1) : window.location.hash;
    var hasTgLaunchData = !!(tgApp && tgApp.initData) || hash.indexOf("tgWebAppData") !== -1;
    var hasMaxLaunchData = !!(maxApp && maxApp.initData);
    var name = hasTgLaunchData ? "telegram" : (hasMaxLaunchData ? "max" : "none");
    var nativeApp = name === "max" ? maxApp : (name === "telegram" ? tgApp : null);

    function ready() {
      if (!nativeApp) return;
      try { if (typeof nativeApp.ready === "function") nativeApp.ready(); } catch (e) { /* not fatal for standalone browser testing */ }
      try { if (typeof nativeApp.expand === "function") nativeApp.expand(); } catch (e) { /* not fatal */ }
    }

    function getInitData() {
      if (nativeApp && nativeApp.initData) return nativeApp.initData;
      if (hash.indexOf("tgWebAppData") === -1) return "";
      var params = new URLSearchParams(hash);
      return params.get("tgWebAppData") || "";
    }

    function getPlatform() { return name; }

    function showBackButton() {
      try { if (nativeApp && nativeApp.BackButton) nativeApp.BackButton.show(); } catch (e) { /* not fatal */ }
    }

    function hideBackButton() {
      try { if (nativeApp && nativeApp.BackButton) nativeApp.BackButton.hide(); } catch (e) { /* not fatal */ }
    }

    function onBackButton(cb) {
      try { if (nativeApp && nativeApp.BackButton) nativeApp.BackButton.onClick(cb); } catch (e) { /* not fatal */ }
    }

    function openLink(url) {
      try {
        if (nativeApp && typeof nativeApp.openLink === "function") { nativeApp.openLink(url); return; }
      } catch (e) { /* fall through to window.open */ }
      window.open(url, "_blank");
    }

    return {
      ready: ready,
      getInitData: getInitData,
      getPlatform: getPlatform,
      showBackButton: showBackButton,
      hideBackButton: hideBackButton,
      onBackButton: onBackButton,
      openLink: openLink
    };
  })();
  Platform.ready();

  function apiGet(path) {
    var initData = Platform.getInitData();
    var headers = { Accept: "application/json", "X-Miniapp-Platform": Platform.getPlatform() };
    if (initData) headers["X-Init-Data"] = initData;
    return fetch(API_BASE + path, { headers: headers, cache: "no-store" }).then(function (res) {
      if (res.status === 401) {
        var err = new Error("unauthorized");
        err.code = 401;
        throw err;
      }
      if (!res.ok) {
        return res.json().catch(function () { return {}; }).then(function (body) {
          var err2 = new Error(body.detail || ("http_" + res.status));
          err2.code = res.status;
          throw err2;
        });
      }
      return res.json();
    });
  }

  function apiPost(path, payload) {
    var initData = Platform.getInitData();
    var headers = { Accept: "application/json", "Content-Type": "application/json", "X-Miniapp-Platform": Platform.getPlatform() };
    if (initData) headers["X-Init-Data"] = initData;
    return fetch(API_BASE + path, { method: "POST", headers: headers, body: JSON.stringify(payload || {}), cache: "no-store" }).then(function (res) {
      if (res.status === 401) {
        var err = new Error("unauthorized");
        err.code = 401;
        throw err;
      }
      if (!res.ok) {
        return res.json().catch(function () { return {}; }).then(function (body) {
          var err2 = new Error(body.detail || ("http_" + res.status));
          err2.code = res.status;
          throw err2;
        });
      }
      return res.json();
    });
  }

  // multipart/form-data POST (фото для /photo/analyze) — не проставляет Content-Type вручную,
  // чтобы браузер сам выставил boundary; авторизация та же, что и в apiGet/apiPost.
  function apiPostForm(path, formData) {
    var initData = Platform.getInitData();
    var headers = { Accept: "application/json", "X-Miniapp-Platform": Platform.getPlatform() };
    if (initData) headers["X-Init-Data"] = initData;
    return fetch(API_BASE + path, { method: "POST", headers: headers, body: formData, cache: "no-store" }).then(function (res) {
      if (res.status === 401) {
        var err = new Error("unauthorized");
        err.code = 401;
        throw err;
      }
      if (!res.ok) {
        return res.json().catch(function () { return {}; }).then(function (body) {
          var err2 = new Error(body.detail || ("http_" + res.status));
          err2.code = res.status;
          throw err2;
        });
      }
      return res.json();
    });
  }

  // ===== Router =====
  function navigate(screen, extra) {
    if (state.screen === "pr-status" && screen !== "pr-status" && state.prStatusTimer) {
      clearTimeout(state.prStatusTimer);
      state.prStatusTimer = null;
    }
    state.screen = screen;
    if (extra && extra.historyFilter !== undefined) state.historyFilter = extra.historyFilter;
    if (extra && extra.stubKey !== undefined) state.stubKey = extra.stubKey;
    if (extra && extra.momPendingKey !== undefined) state.momPendingKey = extra.momPendingKey;
    if (extra && extra.aiQuestionFrom !== undefined) state.aiQuestionFrom = extra.aiQuestionFrom;
    if (extra && extra.schoolFrom !== undefined) state.schoolFrom = extra.schoolFrom;
    if (extra && extra.tantrumEmotionsFrom !== undefined) state.tantrumEmotionsFrom = extra.tantrumEmotionsFrom;
    if (extra && extra.kindergartenFrom !== undefined) state.kindergartenFrom = extra.kindergartenFrom;
    if (extra && extra.childHubFrom !== undefined) state.childHubFrom = extra.childHubFrom;
    if (extra && extra.emergencyFrom !== undefined) state.emergencyFrom = extra.emergencyFrom;
    if (extra && extra.photoAnalysisFrom !== undefined) state.photoAnalysisFrom = extra.photoAnalysisFrom;
    if (extra && extra.sleepTrackerFrom !== undefined) state.sleepTrackerFrom = extra.sleepTrackerFrom;
    if (extra && extra.feedingTrackerFrom !== undefined) state.feedingTrackerFrom = extra.feedingTrackerFrom;
    if (extra && extra.symptomsTrackerFrom !== undefined) state.symptomsTrackerFrom = extra.symptomsTrackerFrom;
    if (extra && extra.growthTrackerFrom !== undefined) state.growthTrackerFrom = extra.growthTrackerFrom;
    if (extra && extra.diaryTrackerFrom !== undefined) state.diaryTrackerFrom = extra.diaryTrackerFrom;
    if (extra && extra.vaccinesTrackerFrom !== undefined) state.vaccinesTrackerFrom = extra.vaccinesTrackerFrom;
    if (extra && extra.cfFrom !== undefined) state.cfFrom = extra.cfFrom;
    var params = new URLSearchParams(window.location.search);
    params.set("screen", screen);
    var newUrl = window.location.pathname + "?" + params.toString() + window.location.hash;
    window.history.replaceState(null, "", newUrl);
    render();
  }

  function runAction(action) {
    if (!action) return;
    if (action.type === "history") navigate("history", { historyFilter: action.filter || "" });
    else if (action.type === "ai-question") navigate("ai-question", { aiQuestionFrom: state.screen });
    else if (action.type === "school") navigate("school", { schoolFrom: state.screen });
    else if (action.type === "tantrum-emotions") navigate("tantrum-emotions", { tantrumEmotionsFrom: state.screen });
    else if (action.type === "kindergarten") navigate("kindergarten", { kindergartenFrom: state.screen });
    else if (action.type === "child-hub") {
      state.child = { choice: null, loading: false, error: "", answer: "", moreLoading: false, moreError: "" };
      navigate("child-hub", { childHubFrom: state.screen });
    }
    else if (action.type === "emergency") navigate("emergency", { emergencyFrom: state.screen });
    else if (action.type === "photo-analysis") {
      state.photoAnalysis = { type: null, fileName: "", previewUrl: "", file: null, loading: false, error: "", answer: "", match: null, message: "" };
      navigate("photo-analysis", { photoAnalysisFrom: state.screen });
    }
    else if (action.type === "sleep-tracker") navigate("sleep-tracker", { sleepTrackerFrom: state.screen });
    else if (action.type === "feeding-tracker") navigate("feeding-tracker", { feedingTrackerFrom: state.screen });
    else if (action.type === "symptoms-tracker") navigate("symptoms-tracker", { symptomsTrackerFrom: state.screen });
    else if (action.type === "growth-tracker") navigate("growth-tracker", { growthTrackerFrom: state.screen });
    else if (action.type === "diary-tracker") navigate("diary-tracker", { diaryTrackerFrom: state.screen });
    else if (action.type === "vaccines-tracker") navigate("vaccines-tracker", { vaccinesTrackerFrom: state.screen });
    else if (action.type === "pregnancy") {
      state.pregnancy = { loading: true, notApplicable: false, loadError: "", weeks: null, days: null, weeksText: "", choice: null, choiceLoading: false, choiceError: "", answer: "" };
      navigate("pregnancy");
    }
    else if (action.type === "stub" && action.stub === "mom-support") navigate("mom-support");
    else if (action.type === "stub" && action.stub === "donate") {
      state.donate = { phase: "pick", amount: null, variant: null, customInput: "", customError: "", payLoading: false, payError: "" };
      navigate("donate");
    }
    else if (action.type === "stub") navigate("stub", { stubKey: action.stub });
  }

  function updateBottomNav() {
    var activeMap = { home: "home", assistant: "assistant", trackers: "trackers", history: "history", profile: "profile", stub: null };
    var active = activeMap[state.screen];
    var items = document.querySelectorAll(".bottomnav__item");
    items.forEach(function (btn) {
      btn.classList.toggle("is-active", btn.getAttribute("data-route") === active);
    });
  }

  // ===== Renderers =====
  function cardHtml(item) {
    var isEmblem = item.icon.indexOf("mama_") === 0;
    return (
      '<button class="shortcut" data-action-card="' + esc(item.key) + '" type="button">' +
      '<img class="shortcut__art' + (isEmblem ? " shortcut__art--pastel" : "") + '" src="' + (isEmblem ? ICONS_EMBLEM : ICONS_HOME) + item.icon + '" alt="" loading="lazy">' +
      '<span class="shortcut__label">' + esc(item.title) + "</span>" +
      "</button>"
    );
  }

  function rowCardHtml(item) {
    return (
      '<button class="row-card" data-action-row="' + esc(item.key) + '" type="button">' +
      '<img class="row-card__icon" src="' + ICONS + item.icon + '" alt="" loading="lazy">' +
      '<span><p class="row-card__title">' + esc(item.title) + "</p>" +
      (item.sub ? '<p class="row-card__sub">' + esc(item.sub) + "</p>" : "") +
      "</span></button>"
    );
  }

  function renderHome(root) {
    root.innerHTML =
      '<div class="screen" id="homeScreen">' +
      '<div class="hero">' +
      '<img class="hero__image" src="' + HERO + '" alt="" loading="eager">' +
      '<div class="hero__text">' +
      '<p class="hero__greeting" id="heroGreeting">Привет!</p>' +
      '<p class="hero__title">Чем помочь сегодня?</p>' +
      "</div>" +
      "</div>" +
      '<button class="today-banner" id="todayBanner" type="button">' +
      '<span class="today-banner__date">СЕГОДНЯ · ' + esc(formatTodayDateShort()) + '</span>' +
      '<span class="today-banner__headline" id="todayBannerHeadline">Загружаю…</span>' +
      '<span class="today-banner__meta" id="todayBannerMeta"></span>' +
      '<span class="today-banner__cta">Что важно сегодня →</span>' +
      "</button>" +
      '<div class="shortcut-grid">' + HOME_CARDS.map(cardHtml).join("") + "</div>" +
      "</div>";

    root.querySelectorAll("[data-action-card]").forEach(function (el) {
      var item = HOME_CARDS.filter(function (c) { return c.key === el.getAttribute("data-action-card"); })[0];
      el.addEventListener("click", function () { runAction(item.action); });
    });

    var todayBannerEl = document.getElementById("todayBanner");
    if (todayBannerEl) {
      todayBannerEl.addEventListener("click", function () {
        state.today = { loading: true, error: "", notApplicable: false, data: null, advice: { loading: false, error: "", answer: "" } };
        navigate("today");
      });
    }
    loadHomeTodayBanner();

    apiGet("/home").then(function (data) {
      var greeting = document.getElementById("heroGreeting");
      if (greeting) greeting.textContent = data.name ? "Привет, " + data.name + "!" : "Привет!";
      var badge = document.getElementById("statusBadge");
      if (badge && data.status_message) badge.textContent = data.status_message;
    }).catch(function () { /* keep default greeting when not authorized yet */ });

    // Раздел "Беременность" виден на Home только профилям mode="pregnant" — HOME_CARDS
    // статичен и не включает функции ребёнка вместо него для этого профиля.
    apiGet("/profile").then(function (data) {
      if (!data || data.mode !== "pregnant") return;
      var grid = root.querySelector(".shortcut-grid");
      if (!grid || grid.querySelector('[data-action-card="pregnancy"]')) return;
      var card = { key: "pregnancy", title: "Беременность", icon: "mama_pregnancy_light.webp", action: { type: "pregnancy" } };
      grid.insertAdjacentHTML("afterbegin", cardHtml(card));
      var el = grid.querySelector('[data-action-card="pregnancy"]');
      if (el) el.addEventListener("click", function () { runAction(card.action); });
    }).catch(function () { /* keep default grid when profile unavailable */ });
  }

  // ===== Сегодня (широкая плашка на Home + отдельный экран). Те же данные, что и в
  // трекерах/профиле, через GET /today — без новых таблиц. AI-совет — только по кнопке на
  // экране "Сегодня" через GET /today/advice, никогда автоматически при открытии =====
  function formatTodayDateShort() {
    try {
      return new Date().toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
    } catch (e) {
      return "";
    }
  }

  function todaySummaryText(data) {
    if (!data) return { headline: "", meta: "" };
    if (data.mode === "pregnant") {
      var weeks = data.pregnancy_weeks, days = data.pregnancy_days;
      var headline = (weeks != null && days != null) ? weeks + " нед. " + days + " дн. беременности" : "Беременность";
      return { headline: headline, meta: data.trimester || "" };
    }
    var headline2 = "Малышу: " + (data.child_age_label || "");
    var parts = [];
    if (data.sleep_count_24h) parts.push("Сон " + data.sleep_count_24h);
    if (data.feeding_count_24h) parts.push("Кормление " + data.feeding_count_24h);
    if (data.symptoms_count_24h) parts.push("Самочувствие " + data.symptoms_count_24h);
    var meta2;
    if (parts.length) {
      meta2 = parts.join(" · ");
      if (data.nearest_vaccine) meta2 += " · 💉 " + data.nearest_vaccine.vaccine;
    } else if (data.nearest_vaccine) {
      meta2 = "💉 " + data.nearest_vaccine.vaccine + " — " + data.nearest_vaccine.scheduled_date;
    } else {
      meta2 = "Сегодня пока нет новых записей";
    }
    return { headline: headline2, meta: meta2 };
  }

  function loadHomeTodayBanner() {
    apiGet("/today").then(function (data) {
      var banner = document.getElementById("todayBanner");
      if (!banner) return;
      if (!data || data.registered === false || !data.mode) {
        banner.style.display = "none";
        return;
      }
      var summary = todaySummaryText(data);
      var headlineEl = document.getElementById("todayBannerHeadline");
      var metaEl = document.getElementById("todayBannerMeta");
      if (headlineEl) headlineEl.textContent = summary.headline;
      if (metaEl) metaEl.textContent = summary.meta;
    }).catch(function () {
      var banner = document.getElementById("todayBanner");
      if (banner) banner.style.display = "none";
    });
  }

  function renderToday(root) {
    var t = state.today;
    root.innerHTML =
      '<div class="screen">' +
      backButtonHtml("home") +
      '<div class="today-scene" id="todayScreen">' +
      '<p class="section-heading" style="margin:0 0 2px;text-align:center">Сегодня</p>' +
      '<div id="todayBody"></div>' +
      "</div></div>";
    bindBack(root);
    if (t.loading) loadToday(root);
    renderTodayBody(root, root.querySelector("#todayBody"));
  }

  function loadToday(root) {
    apiGet("/today").then(function (data) {
      if (state.screen !== "today") return;
      state.today.loading = false;
      state.today.error = "";
      state.today.notApplicable = !data || data.registered === false || !data.mode;
      state.today.data = data;
      renderToday(root);
    }).catch(function (err) {
      if (state.screen !== "today") return;
      state.today.loading = false;
      if (err && err.code === 401) {
        state.today.error = "Открой мини-приложение из бота «Мамин помощник», чтобы увидеть раздел.";
      } else {
        state.today.error = "Не получилось загрузить раздел. Попробуй ещё раз чуть позже.";
      }
      renderToday(root);
    });
  }

  function renderTodayBody(root, body) {
    if (!body) return;
    var t = state.today;

    if (t.loading) {
      body.innerHTML = '<div class="state-message"><p class="state-message__title">Сегодня</p><p>Загружаю…</p></div>';
      return;
    }

    if (t.error) {
      body.innerHTML =
        '<div class="pr-error">' + esc(t.error) + "</div>" +
        '<button class="btn-primary" id="todayRetryLoad" type="button">Попробовать ещё раз</button>';
      body.querySelector("#todayRetryLoad").addEventListener("click", function () {
        state.today.loading = true;
        renderTodayBody(root, body);
        loadToday(root);
      });
      return;
    }

    if (t.notApplicable) {
      body.innerHTML =
        '<div class="state-message"><p class="state-message__title">Заполни профиль</p>' +
        "<p>Расскажи, беременна ты или уже растишь малыша — тогда здесь появится персональная сводка на сегодня.</p></div>";
      return;
    }

    var data = t.data || {};
    var html = '<p class="ai-q-hint" style="margin:0">' + esc(data.date || formatTodayDateShort()) + "</p>";

    if (data.mode === "pregnant") {
      var weeks = data.pregnancy_weeks, days = data.pregnancy_days;
      html +=
        '<div class="today-note"><b>' +
        (weeks != null && days != null ? esc(weeks + " нед. " + days + " дн.") : "Срок неизвестен") +
        "</b>" + (data.trimester ? "<br>" + esc(data.trimester) : "") + "</div>" +
        '<button class="btn-primary" id="todayBabyBtn" type="button">Что происходит с малышом →</button>';
    } else {
      html += '<div class="today-note"><b>' + esc(data.child_age_label || "") + "</b></div>";
      var hasAny = !!(data.sleep_count_24h || data.feeding_count_24h || data.symptoms_count_24h || data.last_growth || data.nearest_vaccine || data.last_diary);
      if (!hasAny) {
        html += '<div class="today-note">Сегодня пока нет новых записей</div>';
      } else {
        html +=
          '<div class="today-stat-grid">' +
          '<div class="today-stat"><span class="today-stat__value">' + (data.sleep_count_24h || 0) + '</span><span class="today-stat__label">Сон · 24ч</span></div>' +
          '<div class="today-stat"><span class="today-stat__value">' + (data.feeding_count_24h || 0) + '</span><span class="today-stat__label">Питание · 24ч</span></div>' +
          '<div class="today-stat"><span class="today-stat__value">' + (data.symptoms_count_24h || 0) + '</span><span class="today-stat__label">Самочувствие · 24ч</span></div>' +
          "</div>";
        if (data.last_growth) {
          html += '<div class="today-note">Последний рост/вес: ' + esc(data.last_growth.height) + " см, " + esc(data.last_growth.weight) + " кг</div>";
        }
        if (data.nearest_vaccine) {
          html += '<div class="today-note">💉 Ближайшая прививка: ' + esc(data.nearest_vaccine.vaccine) + " — " + esc(data.nearest_vaccine.scheduled_date) + "</div>";
        }
        if (data.last_diary) {
          html += '<div class="today-note">Дневник: ' + esc(data.last_diary.entry) + "</div>";
        }
        if (data.complementary_food && data.complementary_food.tried_count) {
          var cf = data.complementary_food;
          html += '<div class="today-note">🥣 Прикорм · попробовано ' + cf.tried_count + " продукт" + cfPluralSuffix(cf.tried_count) + "</div>";
          if (cf.last_food) {
            html += '<div class="today-note">Последний: ' + esc(cf.last_food) + (cf.last_food_status && CF_STATUS_EMOJI[cf.last_food_status] ? " " + CF_STATUS_EMOJI[cf.last_food_status] : "") + "</div>";
          }
          html += '<button class="btn-primary" id="todayCfBtn" type="button">Открыть прикорм →</button>';
        }
      }
    }

    html += '<div id="todayAdviceBody"></div>';
    body.innerHTML = html;

    if (data.mode === "pregnant") {
      var babyBtn = body.querySelector("#todayBabyBtn");
      if (babyBtn) babyBtn.addEventListener("click", function () { runAction({ type: "pregnancy" }); });
    }
    var todayCfBtn = body.querySelector("#todayCfBtn");
    if (todayCfBtn) todayCfBtn.addEventListener("click", function () { openComplementaryFeeding(); });

    renderTodayAdvice(body.querySelector("#todayAdviceBody"));
  }

  function renderTodayAdvice(adviceBody) {
    if (!adviceBody) return;
    var a = state.today.advice;

    if (a.answer) {
      adviceBody.innerHTML =
        '<p class="section-heading" style="margin:10px 2px 2px">Что важно сегодня</p>' +
        '<div class="ai-q-answer">' + esc(a.answer).replace(/\n/g, "<br>") + "</div>" +
        '<button class="btn-primary" id="todayAdviceAgain" type="button">Обновить совет</button>';
      adviceBody.querySelector("#todayAdviceAgain").addEventListener("click", function () {
        state.today.advice = { loading: false, error: "", answer: "" };
        renderTodayAdvice(adviceBody);
      });
      return;
    }

    if (a.loading) {
      adviceBody.innerHTML = '<button class="btn-primary" id="todayAdviceBtn" type="button" disabled>Думаю…</button>';
      return;
    }

    adviceBody.innerHTML =
      (a.error ? '<div class="pr-error">' + esc(a.error) + "</div>" : "") +
      '<button class="btn-primary" id="todayAdviceBtn" type="button">Что важно сегодня?</button>';
    adviceBody.querySelector("#todayAdviceBtn").addEventListener("click", function () {
      state.today.advice.loading = true;
      state.today.advice.error = "";
      renderTodayAdvice(adviceBody);
      apiGet("/today/advice").then(function (data) {
        state.today.advice.loading = false;
        state.today.advice.answer = (data && data.answer) || "";
        renderTodayAdvice(adviceBody);
      }).catch(function (err) {
        state.today.advice.loading = false;
        if (err && err.code === 401) {
          state.today.advice.error = "Открой мини-приложение из бота «Мамин помощник».";
        } else if (err && err.code === 400) {
          state.today.advice.error = "Сначала заполни профиль.";
        } else {
          state.today.advice.error = "Не получилось получить совет. Попробуй ещё раз чуть позже.";
        }
        renderTodayAdvice(adviceBody);
      });
    });
  }

  function renderTrackerShell(root) {
    root.innerHTML =
      '<div class="screen">' +
      '<div class="trackers-scene" id="trackersScreen">' +
      '<p class="section-heading">Трекеры</p>' +
      '<div class="shortcut-grid">' + TRACKER_ITEMS.map(cardHtml).join("") + "</div>" +
      "</div></div>";
    root.querySelectorAll("[data-action-card]").forEach(function (el) {
      var item = TRACKER_ITEMS.filter(function (c) { return c.key === el.getAttribute("data-action-card"); })[0];
      el.addEventListener("click", function () { runAction(item.action); });
    });
  }

  function renderAssistantShell(root) {
    root.innerHTML =
      '<div class="screen">' +
      '<div class="assistant-scene" id="assistantScreen">' +
      '<p class="section-heading">Помощник</p>' +
      '<div class="shortcut-grid">' + ASSISTANT_SHORTCUTS.map(cardHtml).join("") + "</div>" +
      "</div></div>";
    root.querySelectorAll("[data-action-card]").forEach(function (el) {
      var item = ASSISTANT_SHORTCUTS.filter(function (c) { return c.key === el.getAttribute("data-action-card"); })[0];
      el.addEventListener("click", function () { runAction(item.action); });
    });
  }

  function backButtonHtml(toScreen) {
    return '<button class="btn-back" data-back="' + esc(toScreen) + '" type="button">← Назад</button>';
  }

  // ===== Садик (реальный AI-сценарий fd_sadik из Telegram) =====
  function renderKindergarten(root) {
    root.innerHTML =
      '<div class="screen">' +
      backButtonHtml(state.kindergartenFrom || "assistant") +
      '<div class="ai-q-scene" id="kindergartenScreen">' +
      '<img class="ai-q-icon" src="' + ICONS_EMBLEM + 'mama_kindergarten_light.webp" alt="" loading="lazy">' +
      '<p class="section-heading" style="margin:0 0 2px;text-align:center">Садик</p>' +
      '<p class="ai-q-hint">Когда вставать в очередь, как записаться через Госуслуги, какие документы нужны и что делать, если отказали 💕</p>' +
      '<div id="kindergartenBody"></div>' +
      "</div></div>";
    bindBack(root);
    renderKindergartenBody(root, root.querySelector("#kindergartenBody"));
  }

  function renderKindergartenBody(root, body) {
    if (!body) return;
    var k = state.kindergarten;

    if (k.loading) {
      body.innerHTML = '<div class="state-message"><p class="state-message__title">Садик</p><p>Готовлю рекомендации…</p></div>';
      return;
    }

    if (k.error) {
      body.innerHTML =
        '<div class="pr-error">' + esc(k.error) + "</div>" +
        '<button class="btn-primary" id="kdgRetry" type="button">Попробовать ещё раз</button>';
      body.querySelector("#kdgRetry").addEventListener("click", function () {
        state.kindergarten.loading = true;
        state.kindergarten.error = "";
        renderKindergartenBody(root, body);
        requestKindergartenAnswer(root);
      });
      return;
    }

    if (k.answer) {
      body.innerHTML =
        '<div class="ai-q-answer">' + esc(k.answer).replace(/\n/g, "<br>") + "</div>" +
        '<button class="btn-primary" id="kdgAgain" type="button">Получить ещё раз</button>';
      body.querySelector("#kdgAgain").addEventListener("click", function () {
        state.kindergarten.loading = true;
        state.kindergarten.error = "";
        state.kindergarten.answer = "";
        renderKindergartenBody(root, body);
        requestKindergartenAnswer(root);
      });
      return;
    }

    body.innerHTML = '<button class="btn-primary" id="kdgStart" type="button">Получить рекомендации</button>';
    body.querySelector("#kdgStart").addEventListener("click", function () {
      state.kindergarten.loading = true;
      state.kindergarten.error = "";
      renderKindergartenBody(root, body);
      requestKindergartenAnswer(root);
    });
  }

  function requestKindergartenAnswer(root) {
    apiPost("/kindergarten", {}).then(function (data) {
      if (state.screen !== "kindergarten") return;
      state.kindergarten.loading = false;
      state.kindergarten.answer = (data && data.answer) || "";
      renderKindergartenBody(root, root.querySelector("#kindergartenBody"));
    }).catch(function (err) {
      if (state.screen !== "kindergarten") return;
      state.kindergarten.loading = false;
      if (err && err.code === 401) {
        state.kindergarten.error = "Открой мини-приложение из бота «Мамин помощник», чтобы получить рекомендации.";
      } else {
        state.kindergarten.error = "Не получилось получить ответ. Попробуй ещё раз чуть позже.";
      }
      renderKindergartenBody(root, root.querySelector("#kindergartenBody"));
    });
  }

  // ===== Экстренная помощь (реальный сценарий emergency/EMERGENCY_GUIDES/em_other/
  // emergency_other_answer из mama_bot.py). Статичные темы отдаёт GET /emergency/guides без AI
  // (тексты не меняются, показываются как есть); "Другая ситуация" — тот же AI-сценарий, что
  // em_other/emergency_other_answer в Telegram, через POST /emergency/ask. =====
  function renderEmergency(root) {
    root.innerHTML =
      '<div class="screen">' +
      '<button class="btn-back" id="emBack" type="button">← Назад</button>' +
      '<div class="ai-q-scene" id="emergencyScreen">' +
      '<img class="ai-q-icon" src="' + ICONS_EMBLEM + 'mama_emergency_light.webp" alt="" loading="lazy">' +
      '<p class="section-heading" style="margin:0 0 2px;text-align:center">Экстренная помощь</p>' +
      '<div class="pr-safety-banner">При непосредственной угрозе жизни звони 112 или в скорую — не жди ответа в мини-приложении.</div>' +
      '<div id="emergencyBody"></div>' +
      "</div></div>";

    root.querySelector("#emBack").addEventListener("click", function () {
      if (state.emergency.view !== "list") {
        state.emergency.view = "list";
        state.emergency.guideKey = null;
        state.emergency.other = { text: "", answer: "", loading: false, error: "" };
        renderEmergency(root);
      } else {
        navigate(state.emergencyFrom || "assistant");
      }
    });

    renderEmergencyBody(root, root.querySelector("#emergencyBody"));
  }

  function renderEmergencyBody(root, body) {
    if (!body) return;
    var e = state.emergency;

    if (!e.loaded && !e.loading && !e.loadError) {
      state.emergency.loading = true;
      requestEmergencyGuides(root);
      e = state.emergency;
    }

    if (e.loading) {
      body.innerHTML = '<div class="state-message"><p class="state-message__title">Экстренная помощь</p><p>Загружаем темы…</p></div>';
      return;
    }

    if (e.loadError) {
      body.innerHTML =
        '<div class="pr-error">' + esc(e.loadError) + "</div>" +
        '<button class="btn-primary" id="emRetry" type="button">Попробовать ещё раз</button>';
      body.querySelector("#emRetry").addEventListener("click", function () {
        state.emergency.loading = true;
        state.emergency.loadError = "";
        renderEmergencyBody(root, body);
        requestEmergencyGuides(root);
      });
      return;
    }

    if (e.view === "guide") {
      var guide = e.guides.filter(function (g) { return g.key === e.guideKey; })[0];
      if (!guide) {
        state.emergency.view = "list";
        renderEmergencyBody(root, body);
        return;
      }
      body.innerHTML =
        '<p class="ai-q-hint" style="font-weight:700">' + esc(guide.title) + "</p>" +
        '<div class="ai-q-answer">' + esc(guide.text).replace(/\n/g, "<br>") + "</div>" +
        (e.footer ? '<p class="ai-q-hint">' + esc(e.footer) + "</p>" : "") +
        '<button class="btn-primary" id="emGuideBack" type="button">← К списку тем</button>';
      body.querySelector("#emGuideBack").addEventListener("click", function () {
        state.emergency.view = "list";
        state.emergency.guideKey = null;
        renderEmergencyBody(root, body);
      });
      return;
    }

    if (e.view === "other") {
      renderEmergencyOtherBody(root, body);
      return;
    }

    body.innerHTML =
      (e.intro ? '<p class="ai-q-hint">' + esc(e.intro) + "</p>" : "") +
      '<div class="row-list">' +
      e.guides.map(function (g) {
        return (
          '<button class="row-card" data-em-guide="' + esc(g.key) + '" type="button">' +
          '<img class="row-card__icon" src="' + ICONS_EMBLEM + 'mama_emergency_light.webp" alt="" loading="lazy">' +
          "<span><p class=\"row-card__title\">" + esc(g.title) + "</p></span></button>"
        );
      }).join("") +
      '<button class="row-card" data-em-other="1" type="button">' +
      '<img class="row-card__icon" src="' + ICONS_EMBLEM + 'mama_specialist_light.webp" alt="" loading="lazy">' +
      "<span><p class=\"row-card__title\">✍️ Другая ситуация</p></span></button>" +
      "</div>";

    body.querySelectorAll("[data-em-guide]").forEach(function (el) {
      el.addEventListener("click", function () {
        state.emergency.view = "guide";
        state.emergency.guideKey = el.getAttribute("data-em-guide");
        renderEmergencyBody(root, body);
      });
    });
    var otherBtn = body.querySelector("[data-em-other]");
    if (otherBtn) {
      otherBtn.addEventListener("click", function () {
        state.emergency.view = "other";
        renderEmergencyBody(root, body);
      });
    }
  }

  function requestEmergencyGuides(root) {
    apiGet("/emergency/guides").then(function (data) {
      if (state.screen !== "emergency") return;
      state.emergency.loading = false;
      state.emergency.loaded = true;
      state.emergency.intro = (data && data.intro) || "";
      state.emergency.footer = (data && data.footer) || "";
      state.emergency.guides = (data && data.guides) || [];
      renderEmergencyBody(root, root.querySelector("#emergencyBody"));
    }).catch(function (err) {
      if (state.screen !== "emergency") return;
      state.emergency.loading = false;
      state.emergency.loadError = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы получить темы."
        : "Не получилось загрузить темы. Попробуй ещё раз чуть позже.";
      renderEmergencyBody(root, root.querySelector("#emergencyBody"));
    });
  }

  function renderEmergencyOtherBody(root, body) {
    var o = state.emergency.other;

    if (o.answer) {
      body.innerHTML =
        '<div class="ai-q-answer">' + esc(o.answer).replace(/\n/g, "<br>") + "</div>" +
        '<button class="btn-primary" id="emOtherAgain" type="button">Описать ещё раз</button>';
      body.querySelector("#emOtherAgain").addEventListener("click", function () {
        state.emergency.other = { text: "", answer: "", loading: false, error: "" };
        renderEmergencyBody(root, body);
      });
      return;
    }

    body.innerHTML =
      '<p class="ai-q-hint">Опиши ситуацию: возраст, что произошло, температура, как дышит и реагирует, когда началось. При потере сознания, судорогах или нарушении дыхания не жди ответа — звони 112.</p>' +
      '<label class="pr-field">' +
      '<span class="pr-field__label">Опиши ситуацию</span>' +
      '<textarea id="emOtherInput" class="pr-textarea" rows="5" maxlength="' + MINIAPP_EMERGENCY_MAX_LEN + '" placeholder="Опиши ситуацию одним сообщением"' + (o.loading ? " disabled" : "") + ">" + esc(o.text) + "</textarea>" +
      "</label>" +
      (o.error ? '<div class="pr-error">' + esc(o.error) + "</div>" : "") +
      '<button class="btn-primary" id="emOtherSubmit" type="button"' + (o.loading ? " disabled" : "") + ">" + (o.loading ? "Думаю…" : "Получить рекомендации") + "</button>";

    var textarea = body.querySelector("#emOtherInput");
    var submitBtn = body.querySelector("#emOtherSubmit");
    textarea.addEventListener("input", function () { state.emergency.other.text = textarea.value; });

    submitBtn.addEventListener("click", function () {
      var situation = (textarea.value || "").trim();
      if (!situation) {
        state.emergency.other.error = "Опиши ситуацию перед отправкой.";
        renderEmergencyBody(root, body);
        return;
      }
      state.emergency.other.text = situation;
      state.emergency.other.loading = true;
      state.emergency.other.error = "";
      renderEmergencyBody(root, body);

      apiPost("/emergency/ask", { situation: situation }).then(function (data) {
        if (state.screen !== "emergency") return;
        state.emergency.other.loading = false;
        state.emergency.other.answer = (data && data.answer) || "";
        renderEmergencyBody(root, root.querySelector("#emergencyBody"));
      }).catch(function (err) {
        if (state.screen !== "emergency") return;
        state.emergency.other.loading = false;
        if (err && err.code === 401) {
          state.emergency.other.error = "Открой мини-приложение из бота «Мамин помощник», чтобы получить рекомендации.";
        } else if (err && err.code === 400) {
          state.emergency.other.error = "Опиши ситуацию перед отправкой.";
        } else {
          state.emergency.other.error = "Не получилось получить ответ. Попробуй ещё раз чуть позже.";
        }
        renderEmergencyBody(root, root.querySelector("#emergencyBody"));
      });
    });
  }

  function photoTypeRowHtml(item) {
    var isEmblem = item.icon.indexOf("mama_") === 0;
    return (
      '<button class="row-card" data-photo-type="' + esc(item.key) + '" type="button">' +
      '<img class="row-card__icon" src="' + (isEmblem ? ICONS_EMBLEM : ICONS) + item.icon + '" alt="" loading="lazy">' +
      '<span><p class="row-card__title">' + esc(item.title) + "</p>" +
      '<p class="row-card__sub">' + esc(item.sub) + "</p></span></button>"
    );
  }

  function renderPhotoAnalysis(root) {
    var p = state.photoAnalysis;

    if (!p.type) {
      root.innerHTML =
        '<div class="screen">' +
        backButtonHtml(state.photoAnalysisFrom || "assistant") +
        '<div class="assistant-scene" id="photoAnalysisScreen">' +
        '<p class="section-heading">Фотоанализ</p>' +
        '<p class="ai-q-hint">Выбери что нужно проанализировать 👇</p>' +
        '<div class="row-list">' + PHOTO_ANALYSIS_TYPES.map(photoTypeRowHtml).join("") + "</div>" +
        "</div></div>";
      bindBack(root);
      root.querySelectorAll("[data-photo-type]").forEach(function (el) {
        el.addEventListener("click", function () {
          var key = el.getAttribute("data-photo-type");
          state.photoAnalysis = { type: key, fileName: "", previewUrl: "", file: null, loading: false, error: "", answer: "", match: null, message: "" };
          renderPhotoAnalysis(root);
        });
      });
      return;
    }

    var opt = PHOTO_ANALYSIS_TYPES.filter(function (o) { return o.key === p.type; })[0];
    var optIsEmblem = opt.icon.indexOf("mama_") === 0;
    root.innerHTML =
      '<div class="screen">' +
      '<button class="btn-back" id="photoBack" type="button">← Назад</button>' +
      '<div class="ai-q-scene" id="photoAnalysisDetail">' +
      '<img class="ai-q-icon" src="' + (optIsEmblem ? ICONS_EMBLEM : ICONS_HOME) + opt.icon + '" alt="" loading="lazy">' +
      '<p class="section-heading" style="margin:0 0 2px;text-align:center">' + esc(opt.title) + "</p>" +
      '<p class="ai-q-hint">' + esc(opt.hint).replace(/\n/g, "<br>") + "</p>" +
      '<div id="photoAnalysisBody"></div>' +
      "</div></div>";

    root.querySelector("#photoBack").addEventListener("click", function () {
      if (p.previewUrl) { try { URL.revokeObjectURL(p.previewUrl); } catch (e) { /* not fatal */ } }
      state.photoAnalysis = { type: null, fileName: "", previewUrl: "", file: null, loading: false, error: "", answer: "", match: null, message: "" };
      renderPhotoAnalysis(root);
    });

    renderPhotoAnalysisBody(root, root.querySelector("#photoAnalysisBody"));
  }

  function renderPhotoAnalysisBody(root, body) {
    if (!body) return;
    var p = state.photoAnalysis;
    var opt = PHOTO_ANALYSIS_TYPES.filter(function (o) { return o.key === p.type; })[0];
    if (!opt) return;

    if (p.loading) {
      body.innerHTML = '<div class="state-message"><p class="state-message__title">' + esc(opt.title) + "</p><p>Анализирую фото…</p></div>";
      return;
    }

    if (p.answer || p.match === false) {
      var resultHtml = p.match === false
        ? '<div class="pr-error">' + esc(p.message || opt.hint) + "</div>"
        : '<div class="ai-q-answer">' + esc(p.answer).replace(/\n/g, "<br>") + "</div>";
      body.innerHTML =
        resultHtml +
        '<button class="btn-primary" id="photoAnother" type="button">Выбрать другое фото</button>';
      body.querySelector("#photoAnother").addEventListener("click", function () {
        if (state.photoAnalysis.previewUrl) { try { URL.revokeObjectURL(state.photoAnalysis.previewUrl); } catch (e) { /* not fatal */ } }
        state.photoAnalysis.fileName = "";
        state.photoAnalysis.previewUrl = "";
        state.photoAnalysis.file = null;
        state.photoAnalysis.answer = "";
        state.photoAnalysis.match = null;
        state.photoAnalysis.message = "";
        state.photoAnalysis.error = "";
        renderPhotoAnalysisBody(root, body);
      });
      return;
    }

    body.innerHTML =
      '<label class="photo-pick" for="photoFileInput">' +
      (p.previewUrl
        ? '<img class="photo-pick__preview" src="' + p.previewUrl + '" alt="">'
        : '<span class="photo-pick__placeholder">📷 Выбрать фото</span>') +
      "</label>" +
      '<input type="file" accept="image/*" id="photoFileInput" class="photo-pick__input">' +
      (p.error ? '<div class="pr-error">' + esc(p.error) + "</div>" : "") +
      '<button class="btn-primary" id="photoAnalyzeBtn" type="button"' + (p.file ? "" : " disabled") + ">Проанализировать</button>";

    var fileInput = body.querySelector("#photoFileInput");
    fileInput.addEventListener("change", function () {
      var file = fileInput.files && fileInput.files[0];
      if (!file) return;
      if (!/^image\//.test(file.type)) {
        state.photoAnalysis.error = "Выбери файл изображения.";
        renderPhotoAnalysisBody(root, body);
        return;
      }
      if (file.size > MINIAPP_PHOTO_MAX_BYTES) {
        state.photoAnalysis.error = "Файл слишком большой. Выбери фото поменьше.";
        renderPhotoAnalysisBody(root, body);
        return;
      }
      if (state.photoAnalysis.previewUrl) { try { URL.revokeObjectURL(state.photoAnalysis.previewUrl); } catch (e) { /* not fatal */ } }
      state.photoAnalysis.file = file;
      state.photoAnalysis.fileName = file.name || "";
      state.photoAnalysis.previewUrl = URL.createObjectURL(file);
      state.photoAnalysis.error = "";
      renderPhotoAnalysisBody(root, body);
    });

    var analyzeBtn = body.querySelector("#photoAnalyzeBtn");
    analyzeBtn.addEventListener("click", function () {
      if (!state.photoAnalysis.file) return;
      state.photoAnalysis.loading = true;
      state.photoAnalysis.error = "";
      renderPhotoAnalysisBody(root, body);

      var formData = new FormData();
      formData.append("type", p.type);
      formData.append("image", state.photoAnalysis.file);

      apiPostForm("/photo/analyze", formData).then(function (data) {
        if (state.screen !== "photo-analysis" || state.photoAnalysis.type !== p.type) return;
        state.photoAnalysis.loading = false;
        if (data && data.match === false) {
          state.photoAnalysis.match = false;
          state.photoAnalysis.message = data.message || "Это фото не подходит для выбранного типа анализа.";
        } else if (data && data.ok === false) {
          state.photoAnalysis.error = data.message || "Не получилось проанализировать фото. Попробуй ещё раз.";
        } else {
          state.photoAnalysis.match = true;
          state.photoAnalysis.answer = (data && data.answer) || "";
        }
        renderPhotoAnalysisBody(root, root.querySelector("#photoAnalysisBody"));
      }).catch(function (err) {
        if (state.screen !== "photo-analysis" || state.photoAnalysis.type !== p.type) return;
        state.photoAnalysis.loading = false;
        if (err && err.code === 401) {
          state.photoAnalysis.error = "Открой мини-приложение из бота «Мамин помощник», чтобы проанализировать фото.";
        } else if (err && err.code === 400) {
          state.photoAnalysis.error = "Не получилось загрузить фото. Попробуй выбрать другое изображение.";
        } else {
          state.photoAnalysis.error = "Не получилось проанализировать фото. Попробуй ещё раз чуть позже.";
        }
        renderPhotoAnalysisBody(root, root.querySelector("#photoAnalysisBody"));
      });
    });
  }

  // ===== Сон (реальный трекер: sleep_start/sleep_end/sleep_analyze из Telegram) =====
  function renderSleepTracker(root) {
    root.innerHTML =
      '<div class="screen">' +
      backButtonHtml(state.sleepTrackerFrom || "home") +
      '<div class="ai-q-scene" id="sleepTrackerScreen">' +
      '<img class="ai-q-icon" src="' + ICONS_EMBLEM + 'mama_sleep_light.webp" alt="" loading="lazy">' +
      '<p class="section-heading" style="margin:0 0 2px;text-align:center">Сон</p>' +
      '<p class="ai-q-hint">Отмечай, когда малыш засыпает и просыпается, — здесь появится дневник сна 💕</p>' +
      '<div class="sleep-actions">' +
      '<button class="btn-primary sleep-actions__btn" id="sleepStartBtn" type="button">😴 Уснул</button>' +
      '<button class="btn-primary sleep-actions__btn" id="sleepEndBtn" type="button">🌅 Проснулся</button>' +
      "</div>" +
      '<div id="sleepActionMsg"></div>' +
      '<p class="section-heading" style="margin:6px 0 0">Последние записи</p>' +
      '<div id="sleepEntries" class="history-list"><div class="state-message">Загружаем записи…</div></div>' +
      '<div id="sleepAnalyzeBlock"></div>' +
      "</div></div>";

    bindBack(root);
    root.querySelector("#sleepStartBtn").addEventListener("click", function () { submitSleepAction(root, "start"); });
    root.querySelector("#sleepEndBtn").addEventListener("click", function () { submitSleepAction(root, "end"); });

    renderSleepActionMsg(root);
    loadSleepEntries(root);
    renderSleepAnalyzeBlock(root);
  }

  function submitSleepAction(root, action) {
    if (state.sleepTracker.actionLoading) return;
    state.sleepTracker.actionLoading = action;
    state.sleepTracker.actionError = "";
    state.sleepTracker.actionMessage = "";
    renderSleepActionMsg(root);
    apiPost("/sleep/log", { action: action }).then(function () {
      if (state.screen !== "sleep-tracker") return;
      state.sleepTracker.actionLoading = null;
      state.sleepTracker.actionMessage = action === "start" ? "😴 Записала — малыш уснул!" : "🌅 Записала — малыш проснулся!";
      renderSleepActionMsg(root);
      loadSleepEntries(root);
    }).catch(function (err) {
      if (state.screen !== "sleep-tracker") return;
      state.sleepTracker.actionLoading = null;
      state.sleepTracker.actionError = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы сохранить запись."
        : "Не получилось сохранить запись. Попробуй ещё раз чуть позже.";
      renderSleepActionMsg(root);
    });
  }

  function renderSleepActionMsg(root) {
    var el = root.querySelector("#sleepActionMsg");
    if (!el) return;
    var s = state.sleepTracker;
    if (s.actionError) el.innerHTML = '<p class="pr-error">' + esc(s.actionError) + "</p>";
    else if (s.actionMessage) el.innerHTML = '<p class="sleep-confirm">' + esc(s.actionMessage) + "</p>";
    else el.innerHTML = "";
  }

  function loadSleepEntries(root) {
    state.sleepTracker.entriesLoading = true;
    state.sleepTracker.entriesError = "";
    renderSleepEntries(root);
    apiGet("/history/recent").then(function (data) {
      if (state.screen !== "sleep-tracker") return;
      state.sleepTracker.entriesLoading = false;
      state.sleepTracker.entries = (data.items || []).filter(function (it) { return it.type === "sleep"; });
      renderSleepEntries(root);
    }).catch(function (err) {
      if (state.screen !== "sleep-tracker") return;
      state.sleepTracker.entriesLoading = false;
      state.sleepTracker.entriesError = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы увидеть записи."
        : "Не получилось загрузить записи.";
      renderSleepEntries(root);
    });
  }

  function renderSleepEntries(root) {
    var el = root.querySelector("#sleepEntries");
    if (!el) return;
    var s = state.sleepTracker;
    if (s.entriesLoading) {
      el.innerHTML = '<div class="state-message">Загружаем записи…</div>';
      return;
    }
    if (s.entriesError) {
      el.innerHTML = '<div class="state-message"><p class="state-message__title">Не получилось загрузить</p><p>' + esc(s.entriesError) + "</p></div>";
      return;
    }
    if (!s.entries.length) {
      el.innerHTML = '<div class="state-message">Записей нет. Нажимай кнопки, когда малыш засыпает и просыпается!</div>';
      return;
    }
    el.innerHTML = s.entries.slice(0, 6).map(sleepEntryHtml).join("");
  }

  function sleepEntryHtml(item) {
    var emoji = item.detail === "уснул" ? "😴" : "🌅";
    return (
      '<div class="history-row">' +
      "<div><p class=\"history-row__label\">" + emoji + " " + esc(item.detail || "") + "</p></div>" +
      '<span class="history-row__time">' + esc(formatDate(item.created_at)) + "</span>" +
      "</div>"
    );
  }

  function renderSleepAnalyzeBlock(root) {
    var el = root.querySelector("#sleepAnalyzeBlock");
    if (!el) return;
    var s = state.sleepTracker;

    if (s.analyzeLoading) {
      el.innerHTML = '<div class="state-message"><p class="state-message__title">Анализ сна</p><p>Анализирую сон…</p></div>';
      return;
    }

    if (s.analyzeError) {
      el.innerHTML =
        '<div class="pr-error">' + esc(s.analyzeError) + "</div>" +
        '<button class="btn-primary" id="sleepAnalyzeRetry" type="button">Попробовать ещё раз</button>';
      el.querySelector("#sleepAnalyzeRetry").addEventListener("click", function () { requestSleepAnalyze(root); });
      return;
    }

    if (s.analyzeAnswer) {
      el.innerHTML =
        '<div class="ai-q-answer">' + esc(s.analyzeAnswer).replace(/\n/g, "<br>") + "</div>" +
        '<button class="btn-primary" id="sleepAnalyzeAgain" type="button">Получить ещё раз</button>';
      el.querySelector("#sleepAnalyzeAgain").addEventListener("click", function () { requestSleepAnalyze(root); });
      return;
    }

    el.innerHTML = '<button class="btn-primary" id="sleepAnalyzeStart" type="button">📊 AI-разбор сна</button>';
    el.querySelector("#sleepAnalyzeStart").addEventListener("click", function () { requestSleepAnalyze(root); });
  }

  function requestSleepAnalyze(root) {
    state.sleepTracker.analyzeLoading = true;
    state.sleepTracker.analyzeError = "";
    state.sleepTracker.analyzeAnswer = "";
    renderSleepAnalyzeBlock(root);
    apiGet("/sleep/analyze").then(function (data) {
      if (state.screen !== "sleep-tracker") return;
      state.sleepTracker.analyzeLoading = false;
      state.sleepTracker.analyzeAnswer = (data && data.answer) || "";
      renderSleepAnalyzeBlock(root);
    }).catch(function (err) {
      if (state.screen !== "sleep-tracker") return;
      state.sleepTracker.analyzeLoading = false;
      if (err && err.code === 401) {
        state.sleepTracker.analyzeError = "Открой мини-приложение из бота «Мамин помощник», чтобы получить разбор.";
      } else if (err && err.code === 400) {
        state.sleepTracker.analyzeError = "Нужно больше записей для анализа. Фиксируй сон несколько дней!";
      } else {
        state.sleepTracker.analyzeError = "Не получилось получить ответ. Попробуй ещё раз чуть позже.";
      }
      renderSleepAnalyzeBlock(root);
    });
  }

  // ===== Питание (реальный трекер: feed_left/feed_right/feed_bottle/feed_duration/feed_stats из Telegram) =====
  var FEEDING_SIDE_OPTIONS = [
    { key: "left", label: "Левая грудь", emoji: "🤱" },
    { key: "right", label: "Правая грудь", emoji: "🤱" },
    { key: "bottle", label: "Бутылочка", emoji: "🍼" }
  ];

  function renderFeedingTracker(root) {
    root.innerHTML =
      '<div class="screen">' +
      backButtonHtml(state.feedingTrackerFrom || "home") +
      '<div class="ai-q-scene" id="feedingTrackerScreen">' +
      '<img class="ai-q-icon" src="' + ICONS_EMBLEM + 'mama_feeding_light.webp" alt="" loading="lazy">' +
      '<p class="section-heading" style="margin:0 0 2px;text-align:center">Питание</p>' +
      '<p class="ai-q-hint">Отмечай каждое кормление — здесь появится дневник питания 💕</p>' +
      '<button class="cf-entry" id="cfEntryBtn" type="button">' +
      '<img class="cf-entry__icon" src="' + ICONS_EMBLEM + 'mama_complementary_feeding_light.webp" alt="" loading="lazy">' +
      '<span><p class="cf-entry__title">🥣 Прикорм 6+</p>' +
      '<p class="cf-entry__sub">Что давать, как вводить и что малыш уже попробовал</p></span>' +
      "</button>" +
      '<div id="feedingSideBody"></div>' +
      '<p class="section-heading" style="margin:6px 0 0">Последние записи</p>' +
      '<div id="feedingEntries" class="history-list"><div class="state-message">Загружаем записи…</div></div>' +
      '<div id="feedingAnalyzeBlock"></div>' +
      "</div></div>";

    bindBack(root);
    var cfEntryBtn = root.querySelector("#cfEntryBtn");
    if (cfEntryBtn) cfEntryBtn.addEventListener("click", function () { openComplementaryFeeding(); });
    renderFeedingSideBody(root, root.querySelector("#feedingSideBody"));
    loadFeedingEntries(root);
    renderFeedingAnalyzeBlock(root);
  }

  function renderFeedingSideBody(root, body) {
    if (!body) return;
    var f = state.feedingTracker;

    if (!f.side) {
      body.innerHTML =
        '<div class="sleep-actions">' +
        '<button class="btn-primary sleep-actions__btn" data-feed-side="left" type="button">🤱 Левая грудь</button>' +
        '<button class="btn-primary sleep-actions__btn" data-feed-side="right" type="button">🤱 Правая грудь</button>' +
        "</div>" +
        '<button class="btn-primary" data-feed-side="bottle" type="button" style="margin-top:10px">🍼 Бутылочка</button>' +
        (f.saveMessage ? '<p class="sleep-confirm">' + esc(f.saveMessage) + "</p>" : "");
      body.querySelectorAll("[data-feed-side]").forEach(function (el) {
        el.addEventListener("click", function () {
          state.feedingTracker.side = el.getAttribute("data-feed-side");
          state.feedingTracker.duration = "";
          state.feedingTracker.saveError = "";
          state.feedingTracker.saveMessage = "";
          renderFeedingSideBody(root, body);
        });
      });
      return;
    }

    var opt = FEEDING_SIDE_OPTIONS.filter(function (o) { return o.key === f.side; })[0];
    body.innerHTML =
      '<p class="ai-q-hint" style="margin:0 0 8px">' + esc(opt.emoji + " " + opt.label) + "</p>" +
      '<label class="pr-field">' +
      '<span class="pr-field__label">Сколько минут кормила?</span>' +
      '<input type="number" inputmode="numeric" min="1" max="600" id="feedDurationInput" class="pr-input" placeholder="Например, 15" value="' + esc(f.duration) + '"' + (f.saveLoading ? " disabled" : "") + ">" +
      "</label>" +
      (f.saveError ? '<div class="pr-error">' + esc(f.saveError) + "</div>" : "") +
      '<button class="btn-primary" id="feedSaveBtn" type="button"' + (f.saveLoading ? " disabled" : "") + ">" + (f.saveLoading ? "Сохраняю…" : "Сохранить") + "</button>" +
      '<button class="btn-back" id="feedCancelBtn" type="button" style="margin-top:8px">← Выбрать другой вариант</button>';

    var input = body.querySelector("#feedDurationInput");
    input.addEventListener("input", function () { state.feedingTracker.duration = input.value; });
    body.querySelector("#feedSaveBtn").addEventListener("click", function () { submitFeedingLog(root, body); });
    body.querySelector("#feedCancelBtn").addEventListener("click", function () {
      state.feedingTracker.side = null;
      state.feedingTracker.saveError = "";
      renderFeedingSideBody(root, body);
    });
  }

  function submitFeedingLog(root, body) {
    var f = state.feedingTracker;
    var dur = parseInt(f.duration, 10);
    if (!dur || dur <= 0) {
      f.saveError = "Введи количество минут, например: 15";
      renderFeedingSideBody(root, body);
      return;
    }
    var opt = FEEDING_SIDE_OPTIONS.filter(function (o) { return o.key === f.side; })[0];
    f.saveLoading = true;
    f.saveError = "";
    renderFeedingSideBody(root, body);
    apiPost("/feeding/log", { side: f.side, duration: dur }).then(function () {
      if (state.screen !== "feeding-tracker") return;
      state.feedingTracker.saveLoading = false;
      state.feedingTracker.side = null;
      state.feedingTracker.duration = "";
      state.feedingTracker.saveMessage = "✅ Кормление записано! " + opt.label + ", " + dur + " мин 🤱";
      renderFeedingSideBody(root, root.querySelector("#feedingSideBody"));
      loadFeedingEntries(root);
    }).catch(function (err) {
      if (state.screen !== "feeding-tracker") return;
      state.feedingTracker.saveLoading = false;
      state.feedingTracker.saveError = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы сохранить запись."
        : "Не получилось сохранить запись. Попробуй ещё раз чуть позже.";
      renderFeedingSideBody(root, root.querySelector("#feedingSideBody"));
    });
  }

  function loadFeedingEntries(root) {
    state.feedingTracker.entriesLoading = true;
    state.feedingTracker.entriesError = "";
    renderFeedingEntries(root);
    apiGet("/history/recent").then(function (data) {
      if (state.screen !== "feeding-tracker") return;
      state.feedingTracker.entriesLoading = false;
      state.feedingTracker.entries = (data.items || []).filter(function (it) { return it.type === "feeding"; });
      renderFeedingEntries(root);
    }).catch(function (err) {
      if (state.screen !== "feeding-tracker") return;
      state.feedingTracker.entriesLoading = false;
      state.feedingTracker.entriesError = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы увидеть записи."
        : "Не получилось загрузить записи.";
      renderFeedingEntries(root);
    });
  }

  function renderFeedingEntries(root) {
    var el = root.querySelector("#feedingEntries");
    if (!el) return;
    var f = state.feedingTracker;
    if (f.entriesLoading) {
      el.innerHTML = '<div class="state-message">Загружаем записи…</div>';
      return;
    }
    if (f.entriesError) {
      el.innerHTML = '<div class="state-message"><p class="state-message__title">Не получилось загрузить</p><p>' + esc(f.entriesError) + "</p></div>";
      return;
    }
    if (!f.entries.length) {
      el.innerHTML = '<div class="state-message">Записей нет. Нажимай кнопки после каждого кормления!</div>';
      return;
    }
    el.innerHTML = f.entries.slice(0, 6).map(historyItemHtml).join("");
  }

  function renderFeedingAnalyzeBlock(root) {
    var el = root.querySelector("#feedingAnalyzeBlock");
    if (!el) return;
    var f = state.feedingTracker;

    if (f.analyzeLoading) {
      el.innerHTML = '<div class="state-message"><p class="state-message__title">Разбор питания</p><p>Анализирую кормления…</p></div>';
      return;
    }

    if (f.analyzeError) {
      el.innerHTML =
        '<div class="pr-error">' + esc(f.analyzeError) + "</div>" +
        '<button class="btn-primary" id="feedAnalyzeRetry" type="button">Попробовать ещё раз</button>';
      el.querySelector("#feedAnalyzeRetry").addEventListener("click", function () { requestFeedingAnalyze(root); });
      return;
    }

    if (f.analyzeAnswer) {
      el.innerHTML =
        '<div class="ai-q-answer">' + esc(f.analyzeAnswer).replace(/\n/g, "<br>") + "</div>" +
        '<button class="btn-primary" id="feedAnalyzeAgain" type="button">Получить ещё раз</button>';
      el.querySelector("#feedAnalyzeAgain").addEventListener("click", function () { requestFeedingAnalyze(root); });
      return;
    }

    el.innerHTML = '<button class="btn-primary" id="feedAnalyzeStart" type="button">🥣 AI-разбор питания</button>';
    el.querySelector("#feedAnalyzeStart").addEventListener("click", function () { requestFeedingAnalyze(root); });
  }

  function requestFeedingAnalyze(root) {
    state.feedingTracker.analyzeLoading = true;
    state.feedingTracker.analyzeError = "";
    state.feedingTracker.analyzeAnswer = "";
    renderFeedingAnalyzeBlock(root);
    apiGet("/feeding/analyze").then(function (data) {
      if (state.screen !== "feeding-tracker") return;
      state.feedingTracker.analyzeLoading = false;
      state.feedingTracker.analyzeAnswer = (data && data.answer) || "";
      renderFeedingAnalyzeBlock(root);
    }).catch(function (err) {
      if (state.screen !== "feeding-tracker") return;
      state.feedingTracker.analyzeLoading = false;
      if (err && err.code === 401) {
        state.feedingTracker.analyzeError = "Открой мини-приложение из бота «Мамин помощник», чтобы получить разбор.";
      } else if (err && err.code === 400) {
        state.feedingTracker.analyzeError = "Нужно больше записей для анализа. Фиксируй кормления несколько раз!";
      } else {
        state.feedingTracker.analyzeError = "Не получилось получить ответ. Попробуй ещё раз чуть позже.";
      }
      renderFeedingAnalyzeBlock(root);
    });
  }

  // ===== Прикорм 6+ (справочный навигатор внутри «Питание»: WHO complementary feeding 6-23
  // months. Каталог продуктов статический и дублирует backend MINIAPP_CF_* — в БД пишутся
  // только личные отметки через /complementary-foods/mark. Нет AI-вызовов.) =====
  var CF_AGE_TIER_LABELS = {
    "6-7": "6–7 месяцев",
    "8-9": "8–9 месяцев",
    "10-12": "10–12 месяцев",
    "12+": "12+ месяцев"
  };

  var CF_STATUS_OPTIONS = [
    { key: "not_tried", label: "○ Не пробовали" },
    { key: "tried", label: "✓ Пробовали" },
    { key: "liked", label: "❤️ Понравилось" },
    { key: "disliked", label: "— Не понравилось" },
    { key: "reaction", label: "⚠ Была реакция" }
  ];

  var CF_STATUS_MARK = {
    not_tried: "○ Не пробовали",
    tried: "✓ Пробовали",
    liked: "❤️ Понравилось",
    disliked: "— Не понравилось",
    reaction: "⚠ Была реакция"
  };

  var CF_STATUS_EMOJI = { tried: "✓", liked: "❤️", disliked: "—", reaction: "⚠" };

  var CF_REACTION_SAFETY_NOTE =
    "При выраженной или быстро нарастающей реакции, затруднении дыхания, отёке или ухудшении " +
    "состояния малыша — это повод для срочной медицинской помощи, а не для ожидания.";

  var CF_DISCLAIMER = "Информация носит справочный характер и не заменяет рекомендации педиатра.";

  function cfPluralSuffix(n) {
    var mod10 = n % 10, mod100 = n % 100;
    if (mod100 >= 11 && mod100 <= 14) return "ов";
    if (mod10 === 1) return "";
    if (mod10 >= 2 && mod10 <= 4) return "а";
    return "ов";
  }

  function openComplementaryFeeding() {
    state.cf = {
      view: "hub",
      catalog: null, catalogLoading: false, catalogError: "",
      my: null, myLoading: false, myError: "",
      ageTier: null,
      openCategory: null,
      openFood: null,
      markLoadingKey: null, markErrorKey: "", markError: "",
      reactionDraft: {}
    };
    navigate("complementary-feeding", { cfFrom: state.screen });
    loadCfCatalog();
    loadCfMy();
  }

  function cfGoBack(root) {
    if (state.cf.view !== "hub") {
      state.cf.view = "hub";
      state.cf.openCategory = null;
      state.cf.openFood = null;
      state.cf.markError = "";
      renderComplementaryFeeding(root);
    } else {
      navigate(state.cfFrom || "feeding-tracker");
    }
  }

  function cfTitleForView(view) {
    if (view === "what") return "Что давать";
    if (view === "mine") return "Мои продукты";
    if (view === "how") return "Как вводить";
    if (view === "safety") return "Важно и нельзя";
    return "Прикорм 6+";
  }

  function loadCfCatalog() {
    state.cf.catalogLoading = true;
    state.cf.catalogError = "";
    apiGet("/complementary-foods").then(function (data) {
      if (state.screen !== "complementary-feeding") return;
      state.cf.catalogLoading = false;
      state.cf.catalog = data;
      if (!state.cf.ageTier) state.cf.ageTier = (data && data.default_age_tier) || "6-7";
      renderCfBody(document.getElementById("screenRoot"));
    }).catch(function (err) {
      if (state.screen !== "complementary-feeding") return;
      state.cf.catalogLoading = false;
      state.cf.catalogError = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы увидеть каталог."
        : "Не получилось загрузить каталог. Попробуй ещё раз чуть позже.";
      renderCfBody(document.getElementById("screenRoot"));
    });
  }

  function loadCfMy() {
    state.cf.myLoading = true;
    state.cf.myError = "";
    apiGet("/complementary-foods/my").then(function (data) {
      if (state.screen !== "complementary-feeding") return;
      state.cf.myLoading = false;
      state.cf.my = data;
      renderCfBody(document.getElementById("screenRoot"));
    }).catch(function (err) {
      if (state.screen !== "complementary-feeding") return;
      state.cf.myLoading = false;
      state.cf.myError = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы увидеть свои продукты."
        : "Не получилось загрузить список. Попробуй ещё раз чуть позже.";
      renderCfBody(document.getElementById("screenRoot"));
    });
  }

  function cfFindFoodMeta(foodKey) {
    var meta = null;
    if (state.cf.catalog) {
      state.cf.catalog.categories.forEach(function (cat) {
        cat.foods.forEach(function (f) { if (f.key === foodKey) meta = { key: f.key, title: f.title, category: cat.key, allergen: f.allergen }; });
      });
    }
    return meta;
  }

  function markCfFood(root, foodKey, status, reactionText) {
    var c = state.cf;
    c.markLoadingKey = foodKey;
    c.markError = "";
    c.markErrorKey = "";
    renderCfBody(root);
    var payload = { food_key: foodKey, status: status };
    if (reactionText !== null && reactionText !== undefined) payload.reaction_text = reactionText;
    apiPost("/complementary-foods/mark", payload).then(function (data) {
      if (state.screen !== "complementary-feeding") return;
      c.markLoadingKey = null;
      if (c.reactionDraft) delete c.reactionDraft[foodKey];
      if (!c.my) c.my = { items: [], tried_count: 0, liked_count: 0, total_foods: (c.catalog ? c.catalog.total_foods : 0) };
      var items = c.my.items.slice();
      var idx = -1;
      for (var i = 0; i < items.length; i++) { if (items[i].food_key === foodKey) { idx = i; break; } }
      var meta = cfFindFoodMeta(foodKey) || { title: foodKey, category: "" };
      var newItem = {
        food_key: foodKey,
        title: meta.title,
        category: meta.category,
        status: data.status,
        first_tried_at: data.first_tried_at,
        reaction_text: data.reaction_text,
        updated_at: data.updated_at
      };
      if (idx >= 0) items[idx] = newItem; else items.push(newItem);
      c.my.items = items;
      c.my.tried_count = items.filter(function (it) { return it.status !== "not_tried"; }).length;
      c.my.liked_count = items.filter(function (it) { return it.status === "liked"; }).length;
      renderCfBody(root);
    }).catch(function (err) {
      if (state.screen !== "complementary-feeding") return;
      c.markLoadingKey = null;
      c.markErrorKey = foodKey;
      c.markError = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы сохранить отметку."
        : "Не получилось сохранить отметку. Попробуй ещё раз чуть позже.";
      renderCfBody(root);
    });
  }

  function cfMyStatusMap() {
    var map = {};
    if (state.cf.my && state.cf.my.items) {
      state.cf.my.items.forEach(function (it) { map[it.food_key] = it; });
    }
    return map;
  }

  function cfFoodDetailHtml(f, status, rec) {
    var c = state.cf;
    var busy = c.markLoadingKey === f.key;
    var html = '<div class="cf-food-detail">';
    if (f.allergen && c.catalog) {
      html += '<p class="pr-note">' + esc(c.catalog.allergen_note) + "</p>";
    }
    html +=
      '<div class="cf-food-detail__actions">' +
      CF_STATUS_OPTIONS.map(function (opt) {
        return (
          '<button class="cf-status-btn' + (status === opt.key ? " is-active" : "") + '" type="button" ' +
          'data-cf-status="' + esc(opt.key) + '" data-cf-food-key="' + esc(f.key) + '"' + (busy ? " disabled" : "") + ">" +
          esc(opt.label) + "</button>"
        );
      }).join("") +
      "</div>";

    if (status === "reaction") {
      var draft = (c.reactionDraft && c.reactionDraft[f.key] !== undefined) ? c.reactionDraft[f.key] : ((rec && rec.reaction_text) || "");
      html +=
        '<label class="pr-field"><span class="pr-field__label">Что произошло? (необязательно)</span>' +
        '<textarea class="pr-textarea" rows="2" maxlength="300" data-cf-reaction-input="' + esc(f.key) + '"' + (busy ? " disabled" : "") + ">" + esc(draft) + "</textarea></label>" +
        '<div class="pr-safety-banner">' + esc(CF_REACTION_SAFETY_NOTE) + "</div>" +
        '<button class="btn-primary" type="button" data-cf-reaction-save="' + esc(f.key) + '"' + (busy ? " disabled" : "") + ">" + (busy ? "Сохраняю…" : "Сохранить") + "</button>";
    }

    if (c.markError && c.markErrorKey === f.key) html += '<div class="pr-error">' + esc(c.markError) + "</div>";
    html += "</div>";
    return html;
  }

  function cfFoodRowHtml(f) {
    var map = cfMyStatusMap();
    var rec = map[f.key];
    var status = rec ? rec.status : "not_tried";
    var isOpen = state.cf.openFood === f.key;
    var html =
      '<button class="cf-food-row" type="button" data-cf-food="' + esc(f.key) + '">' +
      '<span><p class="cf-food-row__title">' + esc(f.title) + "</p>" +
      (f.allergen ? '<span class="cf-food-row__allergen">⚠ аллерген</span>' : "") +
      "</span>" +
      '<span class="cf-food-status cf-food-status--' + esc(status) + '">' + esc(CF_STATUS_MARK[status] || "") + "</span>" +
      "</button>";
    if (isOpen) html += cfFoodDetailHtml(f, status, rec);
    return html;
  }

  function bindCfCommon(root, body) {
    body.querySelectorAll("[data-cf-tier]").forEach(function (el) {
      el.addEventListener("click", function () {
        state.cf.ageTier = el.getAttribute("data-cf-tier");
        state.cf.openCategory = null;
        state.cf.openFood = null;
        renderCfBody(root);
      });
    });
    body.querySelectorAll("[data-cf-cat]").forEach(function (el) {
      el.addEventListener("click", function () {
        var key = el.getAttribute("data-cf-cat");
        state.cf.openCategory = (state.cf.openCategory === key) ? null : key;
        state.cf.openFood = null;
        renderCfBody(root);
      });
    });
    body.querySelectorAll("[data-cf-food]").forEach(function (el) {
      el.addEventListener("click", function () {
        var key = el.getAttribute("data-cf-food");
        state.cf.openFood = (state.cf.openFood === key) ? null : key;
        state.cf.markError = "";
        renderCfBody(root);
      });
    });
    body.querySelectorAll("[data-cf-status]").forEach(function (el) {
      el.addEventListener("click", function () {
        var status = el.getAttribute("data-cf-status");
        var foodKey = el.getAttribute("data-cf-food-key");
        markCfFood(root, foodKey, status, status === "reaction" ? "" : null);
      });
    });
    body.querySelectorAll("[data-cf-reaction-input]").forEach(function (el) {
      el.addEventListener("input", function () {
        var key = el.getAttribute("data-cf-reaction-input");
        if (!state.cf.reactionDraft) state.cf.reactionDraft = {};
        state.cf.reactionDraft[key] = el.value;
      });
    });
    body.querySelectorAll("[data-cf-reaction-save]").forEach(function (el) {
      el.addEventListener("click", function () {
        var key = el.getAttribute("data-cf-reaction-save");
        var text = (state.cf.reactionDraft && state.cf.reactionDraft[key] !== undefined) ? state.cf.reactionDraft[key] : "";
        markCfFood(root, key, "reaction", text);
      });
    });
  }

  function cfHubEntryHtml(key, title, sub) {
    return (
      '<button class="cf-entry" data-cf-nav="' + esc(key) + '" type="button">' +
      '<img class="cf-entry__icon" src="' + ICONS_EMBLEM + 'mama_complementary_feeding_light.webp" alt="" loading="lazy">' +
      '<span><p class="cf-entry__title">' + esc(title) + "</p>" +
      '<p class="cf-entry__sub">' + esc(sub) + "</p></span>" +
      "</button>"
    );
  }

  function renderCfHub(root, body) {
    var c = state.cf;
    var progressHtml = "";
    if (c.myLoading && !c.my) {
      progressHtml = '<div class="cf-progress"><span class="cf-progress__label">Загружаем прогресс…</span></div>';
    } else if (c.my) {
      var total = c.my.total_foods || 0;
      var pct = total ? Math.round((c.my.tried_count / total) * 100) : 0;
      progressHtml =
        '<div class="cf-progress"><span class="cf-progress__label">Попробовано ' + c.my.tried_count + " из " + total + "</span>" +
        '<div class="cf-progress__bar"><div class="cf-progress__fill" style="width:' + pct + '%"></div></div></div>';
    }

    body.innerHTML =
      progressHtml +
      cfHubEntryHtml("what", "Что давать сейчас", "Продукты по возрасту малыша") +
      cfHubEntryHtml("mine", "Мои продукты", c.my ? ("Попробовано " + c.my.tried_count + " из " + (c.my.total_foods || 0)) : "Что уже попробовал малыш") +
      cfHubEntryHtml("how", "Как вводить", "Спокойный план по возрасту") +
      cfHubEntryHtml("safety", "Важно и нельзя", "Безопасность и запреты");

    body.querySelectorAll("[data-cf-nav]").forEach(function (el) {
      el.addEventListener("click", function () {
        var target = el.getAttribute("data-cf-nav");
        state.cf.view = target;
        state.cf.openCategory = null;
        state.cf.openFood = null;
        state.cf.markError = "";
        if ((target === "what" || target === "mine") && !state.cf.my && !state.cf.myLoading) loadCfMy();
        if (target === "what" && !state.cf.catalog && !state.cf.catalogLoading) loadCfCatalog();
        renderComplementaryFeeding(root);
      });
    });
  }

  function renderCfWhat(root, body) {
    var c = state.cf;
    if (c.catalogLoading || !c.catalog) {
      body.innerHTML = c.catalogError
        ? '<div class="pr-error">' + esc(c.catalogError) + '</div><button class="btn-primary" id="cfRetryCatalog" type="button">Попробовать ещё раз</button>'
        : '<div class="state-message">Загружаем каталог…</div>';
      var retry = body.querySelector("#cfRetryCatalog");
      if (retry) retry.addEventListener("click", function () { loadCfCatalog(); });
      return;
    }
    var tiers = c.catalog.age_tiers || [];
    var tierIdx = tiers.indexOf(c.ageTier);
    var html =
      '<div class="history-filters">' +
      tiers.map(function (t) {
        return '<button type="button" class="history-filter-chip' + (c.ageTier === t ? " is-active" : "") + '" data-cf-tier="' + esc(t) + '">' + esc(CF_AGE_TIER_LABELS[t] || t) + "</button>";
      }).join("") +
      "</div>" +
      '<p class="ai-q-hint" style="margin:6px 0 0">Это не индивидуальный рацион — ориентир, что подходит по возрасту. Малыш пробует по готовности.</p>';

    c.catalog.categories.forEach(function (cat) {
      var foods = cat.foods.filter(function (f) { return tiers.indexOf(f.min_tier) <= tierIdx; });
      if (!foods.length) return;
      var isOpen = c.openCategory === cat.key;
      html +=
        '<div class="cf-category">' +
        '<button class="cf-category__head" type="button" data-cf-cat="' + esc(cat.key) + '">' +
        '<span><p class="cf-category__title">' + esc(cat.title) + "</p>" +
        '<p class="cf-category__sub">' + foods.length + " продукт" + cfPluralSuffix(foods.length) + "</p></span>" +
        '<span class="cf-category__chevron' + (isOpen ? " is-open" : "") + '">▾</span>' +
        "</button>";
      if (isOpen) {
        html +=
          '<div class="cf-category__body">' +
          '<p class="cf-category__example">Примеры сочетаний: ' + esc(cat.example) + "</p>" +
          foods.map(function (f) { return cfFoodRowHtml(f); }).join("") +
          "</div>";
      }
      html += "</div>";
    });

    body.innerHTML = html;
    bindCfCommon(root, body);
  }

  function renderCfMine(root, body) {
    var c = state.cf;
    if (c.myLoading || !c.my) {
      body.innerHTML = c.myError
        ? '<div class="pr-error">' + esc(c.myError) + '</div><button class="btn-primary" id="cfRetryMy" type="button">Попробовать ещё раз</button>'
        : '<div class="state-message">Загружаем твои продукты…</div>';
      var retry = body.querySelector("#cfRetryMy");
      if (retry) retry.addEventListener("click", function () { loadCfMy(); });
      return;
    }
    var total = c.my.total_foods || 0;
    var pct = total ? Math.round((c.my.tried_count / total) * 100) : 0;
    var html =
      '<div class="cf-progress"><span class="cf-progress__label">Попробовано ' + c.my.tried_count + " из " + total + "</span>" +
      '<div class="cf-progress__bar"><div class="cf-progress__fill" style="width:' + pct + '%"></div></div></div>';

    var items = c.my.items.filter(function (it) { return it.status !== "not_tried"; });
    if (!items.length) {
      html += '<div class="state-message">Пока нет отметок. Открой «Что давать» и отметь, что уже попробовал малыш.</div>';
    } else {
      html += items.map(function (it) {
        var meta = cfFindFoodMeta(it.food_key);
        var food = { key: it.food_key, title: it.title || (meta && meta.title) || it.food_key, allergen: meta && meta.allergen };
        return cfFoodRowHtml(food);
      }).join("");
    }
    body.innerHTML = html;
    bindCfCommon(root, body);
  }

  function renderCfHow(body) {
    var blocks = [
      { title: "Около 6 месяцев", text: "Начинайте с небольшого количества, мягкой подходящей консистенции. Грудное молоко или смесь остаются основным питанием — следите за сигналами голода и насыщения малыша." },
      { title: "6–8 месяцев", text: "Ориентир ВОЗ — 2–3 приёма прикорма в день. Постепенно расширяйте разнообразие: пюре, размятая или мягкая пища — по навыкам малыша." },
      { title: "Примерно с 8 месяцев", text: "При готовности ребёнка можно предлагать безопасные мягкие finger foods и развивать более разнообразные текстуры." },
      { title: "9–11 месяцев", text: "Ориентир — 3–4 приёма пищи, больше разнообразных сочетаний и текстур." },
      { title: "К 12 месяцам", text: "Постепенно приближайтесь к семейной пище, адаптированной по соли, сахару, размеру кусочков и безопасности." }
    ];
    var html =
      '<p class="ai-q-hint" style="margin:0 0 4px">Возраст — только ориентир: смотрите на навыки и готовность именно вашего малыша, а не только на цифру в месяцах.</p>' +
      blocks.map(function (b) {
        return '<div class="today-note" style="margin-bottom:8px"><b>' + esc(b.title) + "</b><br>" + esc(b.text) + "</div>";
      }).join("") +
      '<p class="pr-note" style="margin-top:10px">' + esc(CF_DISCLAIMER) + "</p>";
    body.innerHTML = html;
  }

  function renderCfSafety(body) {
    var rules = [
      "Мёд нельзя до 12 месяцев.",
      "Не давайте цельные орехи.",
      "Не давайте твёрдые/круглые продукты, опасные по форме (виноград целиком, крупные твёрдые кусочки и т.п.), без правильной подготовки.",
      "Не добавляйте сахар в детскую еду.",
      "Минимизируйте соль — не досаливайте детскую пищу.",
      "Избегайте непастеризованных небезопасных продуктов.",
      "Коровье молоко не используйте как основной напиток вместо грудного молока/смеси до 12 месяцев.",
      "Учитывайте риск удушья (choking hazards) при выборе формы и размера кусочков.",
      "Ребёнок должен есть сидя и под наблюдением взрослого."
    ];
    var html =
      '<div class="pr-safety-banner">' + rules.map(function (r) { return esc(r); }).join("<br>") + "</div>" +
      '<div class="today-note" style="margin-bottom:8px">' +
      "<b>«Давится» (gagging) — это не то же самое, что «подавился» (choking).</b><br>" +
      "Gagging — обычный, часто шумный рефлекс при знакомстве с новой текстурой: малыш кашляет, " +
      "может покраснеть, но дышит и справляется сам. А если ребёнок не может дышать, кашлять или " +
      "издавать звук, синеет — это подавился, и это повод для немедленных действий и вызова " +
      "скорой помощи. Не путайте одно с другим, но и не теряйте бдительности." +
      "</div>" +
      '<p class="pr-note">' + esc(CF_DISCLAIMER) + "</p>";
    body.innerHTML = html;
  }

  function renderCfBody(root) {
    if (!root) return;
    var body = root.querySelector("#cfBody");
    if (!body) return;
    var view = state.cf.view;
    if (view === "what") { renderCfWhat(root, body); return; }
    if (view === "mine") { renderCfMine(root, body); return; }
    if (view === "how") { renderCfHow(body); return; }
    if (view === "safety") { renderCfSafety(body); return; }
    renderCfHub(root, body);
  }

  function renderComplementaryFeeding(root) {
    var view = state.cf.view;
    root.innerHTML =
      '<div class="screen">' +
      '<button class="btn-back" id="cfBackBtn" type="button">← Назад</button>' +
      '<div class="ai-q-scene" id="cfScreen">' +
      '<img class="ai-q-icon" src="' + ICONS_EMBLEM + 'mama_complementary_feeding_light.webp" alt="" loading="lazy">' +
      '<p class="section-heading" style="margin:0 0 2px;text-align:center">' + esc(cfTitleForView(view)) + "</p>" +
      (view === "hub" ? '<p class="ai-q-hint">Что давать, как вводить и что малыш уже попробовал 💕</p>' : "") +
      '<div id="cfBody"></div>' +
      "</div></div>";

    root.querySelector("#cfBackBtn").addEventListener("click", function () { cfGoBack(root); });
    renderCfBody(root);
  }

  // ===== Самочувствие (реальный трекер: symptom_add/save_symptom_entry/symptom_analyze из Telegram) =====
  function renderSymptomsTracker(root) {
    root.innerHTML =
      '<div class="screen">' +
      backButtonHtml(state.symptomsTrackerFrom || "home") +
      '<div class="ai-q-scene" id="symptomsTrackerScreen">' +
      '<img class="ai-q-icon" src="' + ICONS_EMBLEM + 'mama_wellbeing_light.webp" alt="" loading="lazy">' +
      '<p class="section-heading" style="margin:0 0 2px;text-align:center">Самочувствие</p>' +
      '<p class="ai-q-hint">Фиксируй симптомы малыша — бот поможет отследить динамику 💕</p>' +
      '<div id="symptomsSaveBody"></div>' +
      '<p class="section-heading" style="margin:6px 0 0">Последние записи</p>' +
      '<div id="symptomsEntries" class="history-list"><div class="state-message">Загружаем записи…</div></div>' +
      '<div id="symptomsAnalyzeBlock"></div>' +
      "</div></div>";

    bindBack(root);
    renderSymptomsSaveBody(root, root.querySelector("#symptomsSaveBody"));
    loadSymptomsEntries(root);
    renderSymptomsAnalyzeBlock(root);
  }

  function renderSymptomsSaveBody(root, body) {
    if (!body) return;
    var s = state.symptomsTracker;
    body.innerHTML =
      '<label class="pr-field">' +
      '<span class="pr-field__label">Что вас беспокоит?</span>' +
      '<textarea id="symptomsInput" class="pr-textarea" rows="4" maxlength="' + MINIAPP_SYMPTOM_MAX_LEN + '" placeholder="Например: температура 38.2, кашель, сыпь на щеках"' + (s.saveLoading ? " disabled" : "") + ">" + esc(s.text) + "</textarea>" +
      "</label>" +
      (s.saveError ? '<div class="pr-error">' + esc(s.saveError) + "</div>" : "") +
      (s.saveMessage ? '<p class="sleep-confirm">' + esc(s.saveMessage) + "</p>" : "") +
      '<button class="btn-primary" id="symptomsSaveBtn" type="button"' + (s.saveLoading ? " disabled" : "") + ">" + (s.saveLoading ? "Сохраняю…" : "Сохранить") + "</button>";

    var textarea = body.querySelector("#symptomsInput");
    textarea.addEventListener("input", function () {
      state.symptomsTracker.text = textarea.value;
      state.symptomsTracker.saveError = "";
    });
    body.querySelector("#symptomsSaveBtn").addEventListener("click", function () { submitSymptomLog(root, body); });
  }

  function submitSymptomLog(root, body) {
    var s = state.symptomsTracker;
    var symptom = (s.text || "").trim();
    if (!symptom) {
      s.saveError = "Опиши симптом перед сохранением.";
      s.saveMessage = "";
      renderSymptomsSaveBody(root, body);
      return;
    }
    s.saveLoading = true;
    s.saveError = "";
    s.saveMessage = "";
    renderSymptomsSaveBody(root, body);
    apiPost("/symptoms/log", { symptom: symptom }).then(function () {
      if (state.screen !== "symptoms-tracker") return;
      state.symptomsTracker.saveLoading = false;
      state.symptomsTracker.text = "";
      state.symptomsTracker.saveMessage = "✅ Симптом записан!";
      renderSymptomsSaveBody(root, root.querySelector("#symptomsSaveBody"));
      loadSymptomsEntries(root);
    }).catch(function (err) {
      if (state.screen !== "symptoms-tracker") return;
      state.symptomsTracker.saveLoading = false;
      state.symptomsTracker.saveError = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы сохранить запись."
        : (err && err.code === 400)
          ? "Опиши симптом перед сохранением."
          : "Не получилось сохранить запись. Попробуй ещё раз чуть позже.";
      renderSymptomsSaveBody(root, root.querySelector("#symptomsSaveBody"));
    });
  }

  function loadSymptomsEntries(root) {
    state.symptomsTracker.entriesLoading = true;
    state.symptomsTracker.entriesError = "";
    renderSymptomsEntries(root);
    apiGet("/history/recent").then(function (data) {
      if (state.screen !== "symptoms-tracker") return;
      state.symptomsTracker.entriesLoading = false;
      state.symptomsTracker.entries = (data.items || []).filter(function (it) { return it.type === "symptoms"; });
      renderSymptomsEntries(root);
    }).catch(function (err) {
      if (state.screen !== "symptoms-tracker") return;
      state.symptomsTracker.entriesLoading = false;
      state.symptomsTracker.entriesError = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы увидеть записи."
        : "Не получилось загрузить записи.";
      renderSymptomsEntries(root);
    });
  }

  function renderSymptomsEntries(root) {
    var el = root.querySelector("#symptomsEntries");
    if (!el) return;
    var s = state.symptomsTracker;
    if (s.entriesLoading) {
      el.innerHTML = '<div class="state-message">Загружаем записи…</div>';
      return;
    }
    if (s.entriesError) {
      el.innerHTML = '<div class="state-message"><p class="state-message__title">Не получилось загрузить</p><p>' + esc(s.entriesError) + "</p></div>";
      return;
    }
    if (!s.entries.length) {
      el.innerHTML = '<div class="state-message">Записей нет. Фиксируй симптомы малыша, и здесь появится дневник.</div>';
      return;
    }
    el.innerHTML = s.entries.slice(0, 7).map(historyItemHtml).join("");
  }

  function renderSymptomsAnalyzeBlock(root) {
    var el = root.querySelector("#symptomsAnalyzeBlock");
    if (!el) return;
    var s = state.symptomsTracker;

    if (s.analyzeLoading) {
      el.innerHTML = '<div class="state-message"><p class="state-message__title">Анализ самочувствия</p><p>Анализирую симптомы…</p></div>';
      return;
    }

    if (s.analyzeError) {
      el.innerHTML =
        '<div class="pr-error">' + esc(s.analyzeError) + "</div>" +
        '<button class="btn-primary" id="symptomsAnalyzeRetry" type="button">Попробовать ещё раз</button>';
      el.querySelector("#symptomsAnalyzeRetry").addEventListener("click", function () { requestSymptomsAnalyze(root); });
      return;
    }

    if (s.analyzeAnswer) {
      el.innerHTML =
        '<div class="ai-q-answer">' + esc(s.analyzeAnswer).replace(/\n/g, "<br>") + "</div>" +
        '<button class="btn-primary" id="symptomsAnalyzeAgain" type="button">Повторить анализ</button>';
      el.querySelector("#symptomsAnalyzeAgain").addEventListener("click", function () { requestSymptomsAnalyze(root); });
      return;
    }

    el.innerHTML = '<button class="btn-primary" id="symptomsAnalyzeStart" type="button">🔍 AI-разбор самочувствия</button>';
    el.querySelector("#symptomsAnalyzeStart").addEventListener("click", function () { requestSymptomsAnalyze(root); });
  }

  function requestSymptomsAnalyze(root) {
    state.symptomsTracker.analyzeLoading = true;
    state.symptomsTracker.analyzeError = "";
    state.symptomsTracker.analyzeAnswer = "";
    renderSymptomsAnalyzeBlock(root);
    apiGet("/symptoms/analyze").then(function (data) {
      if (state.screen !== "symptoms-tracker") return;
      state.symptomsTracker.analyzeLoading = false;
      state.symptomsTracker.analyzeAnswer = (data && data.answer) || "";
      renderSymptomsAnalyzeBlock(root);
    }).catch(function (err) {
      if (state.screen !== "symptoms-tracker") return;
      state.symptomsTracker.analyzeLoading = false;
      if (err && err.code === 401) {
        state.symptomsTracker.analyzeError = "Открой мини-приложение из бота «Мамин помощник», чтобы получить разбор.";
      } else if (err && err.code === 400) {
        state.symptomsTracker.analyzeError = "Нет симптомов для анализа. Сначала запиши хотя бы один.";
      } else {
        state.symptomsTracker.analyzeError = "Не получилось получить ответ. Попробуй ещё раз чуть позже.";
      }
      renderSymptomsAnalyzeBlock(root);
    });
  }

  // ===== Дневник малыша (реальный сценарий: mama_diary/diary_add/save_diary_entry из Telegram) =====
  function renderDiaryTracker(root) {
    root.innerHTML =
      '<div class="screen">' +
      backButtonHtml(state.diaryTrackerFrom || "trackers") +
      '<div class="ai-q-scene" id="diaryTrackerScreen">' +
      '<img class="ai-q-icon" src="' + ICONS_EMBLEM + 'mama_baby_diary_light.webp" alt="" loading="lazy">' +
      '<p class="section-heading" style="margin:0 0 2px;text-align:center">Дневник малыша</p>' +
      '<p class="ai-q-hint">Что произошло сегодня? Первый зуб, новое слово, первый шаг, важное событие 💕</p>' +
      '<div id="diarySaveBody"></div>' +
      '<p class="section-heading" style="margin:6px 0 0">Последние записи</p>' +
      '<div id="diaryEntries" class="history-list"><div class="state-message">Загружаем записи…</div></div>' +
      "</div></div>";

    bindBack(root);
    renderDiarySaveBody(root, root.querySelector("#diarySaveBody"));
    loadDiaryEntries(root);
  }

  function renderDiarySaveBody(root, body) {
    if (!body) return;
    var d = state.diaryTracker;
    body.innerHTML =
      '<label class="pr-field">' +
      '<span class="pr-field__label">Что произошло сегодня?</span>' +
      '<textarea id="diaryInput" class="pr-textarea" rows="4" maxlength="' + MINIAPP_DIARY_MAX_LEN + '" placeholder="Например: первый зуб, новое слово, первый шаг, важное событие"' + (d.saveLoading ? " disabled" : "") + ">" + esc(d.text) + "</textarea>" +
      "</label>" +
      (d.saveError ? '<div class="pr-error">' + esc(d.saveError) + "</div>" : "") +
      (d.saveMessage ? '<p class="sleep-confirm">' + esc(d.saveMessage) + "</p>" : "") +
      '<button class="btn-primary" id="diarySaveBtn" type="button"' + (d.saveLoading ? " disabled" : "") + ">" + (d.saveLoading ? "Сохраняю…" : "Добавить запись") + "</button>";

    var textarea = body.querySelector("#diaryInput");
    textarea.addEventListener("input", function () {
      state.diaryTracker.text = textarea.value;
      state.diaryTracker.saveError = "";
    });
    body.querySelector("#diarySaveBtn").addEventListener("click", function () { submitDiaryEntry(root, body); });
  }

  function submitDiaryEntry(root, body) {
    var d = state.diaryTracker;
    var text = (d.text || "").trim();
    if (!text) {
      d.saveError = "Напиши, что произошло, перед сохранением.";
      d.saveMessage = "";
      renderDiarySaveBody(root, body);
      return;
    }
    d.saveLoading = true;
    d.saveError = "";
    d.saveMessage = "";
    renderDiarySaveBody(root, body);
    apiPost("/diary/add", { text: text }).then(function () {
      if (state.screen !== "diary-tracker") return;
      state.diaryTracker.saveLoading = false;
      state.diaryTracker.text = "";
      state.diaryTracker.saveMessage = "✅ Запись сохранена в дневник!";
      renderDiarySaveBody(root, root.querySelector("#diarySaveBody"));
      loadDiaryEntries(root);
    }).catch(function (err) {
      if (state.screen !== "diary-tracker") return;
      state.diaryTracker.saveLoading = false;
      state.diaryTracker.saveError = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы сохранить запись."
        : (err && err.code === 400)
          ? "Напиши, что произошло, перед сохранением."
          : "Не получилось сохранить запись. Попробуй ещё раз чуть позже.";
      renderDiarySaveBody(root, root.querySelector("#diarySaveBody"));
    });
  }

  function loadDiaryEntries(root) {
    state.diaryTracker.entriesLoading = true;
    state.diaryTracker.entriesError = "";
    renderDiaryEntries(root);
    apiGet("/diary/list").then(function (data) {
      if (state.screen !== "diary-tracker") return;
      state.diaryTracker.entriesLoading = false;
      state.diaryTracker.entries = (data.items || []).map(function (it) {
        return { label: "Дневник", detail: it.text || "", created_at: it.created_at || "" };
      });
      renderDiaryEntries(root);
    }).catch(function (err) {
      if (state.screen !== "diary-tracker") return;
      state.diaryTracker.entriesLoading = false;
      state.diaryTracker.entriesError = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы увидеть записи."
        : "Не получилось загрузить записи.";
      renderDiaryEntries(root);
    });
  }

  function renderDiaryEntries(root) {
    var el = root.querySelector("#diaryEntries");
    if (!el) return;
    var d = state.diaryTracker;
    if (d.entriesLoading) {
      el.innerHTML = '<div class="state-message">Загружаем записи…</div>';
      return;
    }
    if (d.entriesError) {
      el.innerHTML = '<div class="state-message"><p class="state-message__title">Не получилось загрузить</p><p>' + esc(d.entriesError) + "</p></div>";
      return;
    }
    if (!d.entries.length) {
      el.innerHTML = '<div class="state-message">Записей пока нет. Начни фиксировать важные моменты! 💕</div>';
      return;
    }
    el.innerHTML = d.entries.slice(0, 10).map(historyItemHtml).join("");
  }

  // ===== Рост и вес (реальный трекер: growth_add/growth_height/growth_weight/growth_analyze из Telegram) =====
  function renderGrowthTracker(root) {
    root.innerHTML =
      '<div class="screen">' +
      backButtonHtml(state.growthTrackerFrom || "home") +
      '<div class="ai-q-scene" id="growthTrackerScreen">' +
      '<img class="ai-q-icon" src="' + ICONS_EMBLEM + 'mama_growth_weight_light.webp" alt="" loading="lazy">' +
      '<p class="section-heading" style="margin:0 0 2px;text-align:center">Рост и вес</p>' +
      '<p class="ai-q-hint">Отмечай замеры роста и веса — здесь появится динамика малыша 💕</p>' +
      '<div id="growthFormBody"></div>' +
      '<p class="section-heading" style="margin:6px 0 0">Последние замеры</p>' +
      '<div id="growthEntries" class="history-list"><div class="state-message">Загружаем записи…</div></div>' +
      '<div id="growthAnalyzeBlock"></div>' +
      "</div></div>";

    bindBack(root);
    renderGrowthFormBody(root, root.querySelector("#growthFormBody"));
    loadGrowthEntries(root);
    renderGrowthAnalyzeBlock(root);
  }

  function renderGrowthFormBody(root, body) {
    if (!body) return;
    var g = state.growthTracker;
    body.innerHTML =
      '<label class="pr-field">' +
      '<span class="pr-field__label">Рост, см</span>' +
      '<input type="number" inputmode="decimal" min="30" max="200" step="0.1" id="growthHeightInput" class="pr-input" placeholder="Например, 67.5" value="' + esc(g.height) + '"' + (g.saveLoading ? " disabled" : "") + ">" +
      "</label>" +
      '<label class="pr-field">' +
      '<span class="pr-field__label">Вес, кг</span>' +
      '<input type="number" inputmode="decimal" min="0.5" max="100" step="0.1" id="growthWeightInput" class="pr-input" placeholder="Например, 7.2" value="' + esc(g.weight) + '"' + (g.saveLoading ? " disabled" : "") + ">" +
      "</label>" +
      (g.saveError ? '<div class="pr-error">' + esc(g.saveError) + "</div>" : "") +
      '<button class="btn-primary" id="growthSaveBtn" type="button"' + (g.saveLoading ? " disabled" : "") + ">" + (g.saveLoading ? "Сохраняю…" : "Сохранить") + "</button>" +
      (g.saveMessage ? '<p class="sleep-confirm">' + esc(g.saveMessage) + "</p>" : "");

    var hInput = body.querySelector("#growthHeightInput");
    var wInput = body.querySelector("#growthWeightInput");
    hInput.addEventListener("input", function () { state.growthTracker.height = hInput.value; });
    wInput.addEventListener("input", function () { state.growthTracker.weight = wInput.value; });
    body.querySelector("#growthSaveBtn").addEventListener("click", function () { submitGrowthLog(root, body); });
  }

  function submitGrowthLog(root, body) {
    var g = state.growthTracker;
    var height = parseFloat(String(g.height).replace(",", "."));
    var weight = parseFloat(String(g.weight).replace(",", "."));
    if (!height || height <= 0) {
      g.saveError = "Введи рост в сантиметрах, например: 67.5";
      renderGrowthFormBody(root, body);
      return;
    }
    if (!weight || weight <= 0) {
      g.saveError = "Введи вес в килограммах, например: 7.2";
      renderGrowthFormBody(root, body);
      return;
    }
    g.saveLoading = true;
    g.saveError = "";
    renderGrowthFormBody(root, body);
    apiPost("/growth/log", { height: height, weight: weight }).then(function () {
      if (state.screen !== "growth-tracker") return;
      state.growthTracker.saveLoading = false;
      state.growthTracker.height = "";
      state.growthTracker.weight = "";
      state.growthTracker.saveMessage = "✅ Замер сохранён! Рост " + height + " см, вес " + weight + " кг 📏";
      renderGrowthFormBody(root, root.querySelector("#growthFormBody"));
      loadGrowthEntries(root);
    }).catch(function (err) {
      if (state.screen !== "growth-tracker") return;
      state.growthTracker.saveLoading = false;
      state.growthTracker.saveError = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы сохранить запись."
        : (err && err.code === 400)
        ? "Проверь значения роста и веса — похоже, они некорректны."
        : "Не получилось сохранить запись. Попробуй ещё раз чуть позже.";
      renderGrowthFormBody(root, root.querySelector("#growthFormBody"));
    });
  }

  function loadGrowthEntries(root) {
    state.growthTracker.entriesLoading = true;
    state.growthTracker.entriesError = "";
    renderGrowthEntries(root);
    apiGet("/growth/list").then(function (data) {
      if (state.screen !== "growth-tracker") return;
      state.growthTracker.entriesLoading = false;
      state.growthTracker.entries = (data && data.items) || [];
      renderGrowthEntries(root);
    }).catch(function (err) {
      if (state.screen !== "growth-tracker") return;
      state.growthTracker.entriesLoading = false;
      state.growthTracker.entriesError = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы увидеть записи."
        : "Не получилось загрузить записи.";
      renderGrowthEntries(root);
    });
  }

  function growthEntryHtml(item) {
    return (
      '<div class="history-row">' +
      '<div><p class="history-row__label">📏 ' + esc(String(item.height)) + " см, ⚖️ " + esc(String(item.weight)) + ' кг</p></div>' +
      '<span class="history-row__time">' + esc(formatDate(item.created_at)) + "</span>" +
      "</div>"
    );
  }

  function growthDynamicsText(entries) {
    if (!entries || entries.length < 2) return "";
    var newest = entries[0];
    var oldest = entries[entries.length - 1];
    var dh = Math.round((newest.height - oldest.height) * 10) / 10;
    var dw = Math.round((newest.weight - oldest.weight) * 10) / 10;
    var signH = dh >= 0 ? "+" : "";
    var signW = dw >= 0 ? "+" : "";
    return "Динамика за " + entries.length + " замер(ов): рост " + signH + dh + " см, вес " + signW + dw + " кг";
  }

  function renderGrowthEntries(root) {
    var el = root.querySelector("#growthEntries");
    if (!el) return;
    var g = state.growthTracker;
    if (g.entriesLoading) {
      el.innerHTML = '<div class="state-message">Загружаем записи…</div>';
      return;
    }
    if (g.entriesError) {
      el.innerHTML = '<div class="state-message"><p class="state-message__title">Не получилось загрузить</p><p>' + esc(g.entriesError) + "</p></div>";
      return;
    }
    if (!g.entries.length) {
      el.innerHTML = '<div class="state-message">Замеров пока нет. Начни отслеживать!</div>';
      return;
    }
    var dynamics = growthDynamicsText(g.entries);
    el.innerHTML = (dynamics ? '<p class="ai-q-hint" style="margin:0 0 4px">' + esc(dynamics) + "</p>" : "") +
      g.entries.slice(0, 6).map(growthEntryHtml).join("");
  }

  function renderGrowthAnalyzeBlock(root) {
    var el = root.querySelector("#growthAnalyzeBlock");
    if (!el) return;
    var g = state.growthTracker;

    if (g.analyzeLoading) {
      el.innerHTML = '<div class="state-message"><p class="state-message__title">Анализ динамики</p><p>Анализирую рост и вес…</p></div>';
      return;
    }

    if (g.analyzeError) {
      el.innerHTML =
        '<div class="pr-error">' + esc(g.analyzeError) + "</div>" +
        '<button class="btn-primary" id="growthAnalyzeRetry" type="button">Попробовать ещё раз</button>';
      el.querySelector("#growthAnalyzeRetry").addEventListener("click", function () { requestGrowthAnalyze(root); });
      return;
    }

    if (g.analyzeAnswer) {
      el.innerHTML =
        '<div class="ai-q-answer">' + esc(g.analyzeAnswer).replace(/\n/g, "<br>") + "</div>" +
        '<button class="btn-primary" id="growthAnalyzeAgain" type="button">Получить ещё раз</button>';
      el.querySelector("#growthAnalyzeAgain").addEventListener("click", function () { requestGrowthAnalyze(root); });
      return;
    }

    el.innerHTML = '<button class="btn-primary" id="growthAnalyzeStart" type="button">📈 AI-анализ динамики</button>';
    el.querySelector("#growthAnalyzeStart").addEventListener("click", function () { requestGrowthAnalyze(root); });
  }

  function requestGrowthAnalyze(root) {
    state.growthTracker.analyzeLoading = true;
    state.growthTracker.analyzeError = "";
    state.growthTracker.analyzeAnswer = "";
    renderGrowthAnalyzeBlock(root);
    apiGet("/growth/analyze").then(function (data) {
      if (state.screen !== "growth-tracker") return;
      state.growthTracker.analyzeLoading = false;
      state.growthTracker.analyzeAnswer = (data && data.answer) || "";
      renderGrowthAnalyzeBlock(root);
    }).catch(function (err) {
      if (state.screen !== "growth-tracker") return;
      state.growthTracker.analyzeLoading = false;
      if (err && err.code === 401) {
        state.growthTracker.analyzeError = "Открой мини-приложение из бота «Мамин помощник», чтобы получить разбор.";
      } else if (err && err.code === 400) {
        state.growthTracker.analyzeError = "Нужно хотя бы одно измерение для анализа. Добавь замер!";
      } else {
        state.growthTracker.analyzeError = "Не получилось получить ответ. Попробуй ещё раз чуть позже.";
      }
      renderGrowthAnalyzeBlock(root);
    });
  }

  // ===== Прививки (реальный сценарий, эквивалентный tracker_vaccines/vaccines_create/
  // vaccines_done/vac_done_{id}/vaccines_info из Telegram-бота) =====
  function renderVaccinesTracker(root) {
    root.innerHTML =
      '<div class="screen">' +
      backButtonHtml(state.vaccinesTrackerFrom || "trackers") +
      '<div class="ai-q-scene" id="vaccinesTrackerScreen">' +
      '<img class="ai-q-icon" src="' + ICONS_EMBLEM + 'mama_vaccines_light.webp" alt="" loading="lazy">' +
      '<p class="section-heading" style="margin:0 0 2px;text-align:center">Прививки</p>' +
      '<p class="ai-q-hint">Календарь прививок малыша с напоминаниями и справкой по каждой вакцине 💕</p>' +
      '<div id="vaccinesBody"></div>' +
      "</div></div>";
    bindBack(root);
    loadVaccinesList(root);
  }

  function loadVaccinesList(root) {
    state.vaccinesTracker.itemsLoading = true;
    state.vaccinesTracker.itemsError = "";
    renderVaccinesBody(root);
    apiGet("/vaccines/list").then(function (data) {
      if (state.screen !== "vaccines-tracker") return;
      state.vaccinesTracker.itemsLoading = false;
      state.vaccinesTracker.items = (data && data.items) || [];
      renderVaccinesBody(root);
    }).catch(function (err) {
      if (state.screen !== "vaccines-tracker") return;
      state.vaccinesTracker.itemsLoading = false;
      state.vaccinesTracker.itemsError = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы увидеть календарь."
        : "Не получилось загрузить календарь прививок.";
      renderVaccinesBody(root);
    });
  }

  function renderVaccinesBody(root) {
    var body = root.querySelector("#vaccinesBody");
    if (!body) return;
    var v = state.vaccinesTracker;

    if (v.itemsLoading) {
      body.innerHTML = '<div class="state-message">Загружаем календарь…</div>';
      return;
    }

    if (v.itemsError) {
      body.innerHTML =
        '<div class="state-message"><p class="state-message__title">Не получилось загрузить</p><p>' + esc(v.itemsError) + "</p></div>" +
        '<button class="btn-primary" id="vacRetryBtn" type="button">Попробовать ещё раз</button>';
      body.querySelector("#vacRetryBtn").addEventListener("click", function () { loadVaccinesList(root); });
      return;
    }

    var html = "";
    if (v.createError) html += '<div class="pr-error">' + esc(v.createError) + "</div>";
    if (v.createMessage) html += '<p class="sleep-confirm">' + esc(v.createMessage) + "</p>";
    if (v.doneError) html += '<div class="pr-error">' + esc(v.doneError) + "</div>";

    if (!v.items.length) {
      html +=
        '<div class="state-message">Календарь прививок пока не создан.</div>' +
        '<button class="btn-primary" id="vacCreateBtn" type="button"' + (v.createLoading ? " disabled" : "") + ">" +
        (v.createLoading ? "Создаю…" : "📅 Создать календарь") + "</button>";
      body.innerHTML = html;
      body.querySelector("#vacCreateBtn").addEventListener("click", function () { submitVaccinesCreate(root); });
      return;
    }

    html +=
      '<button class="btn-primary" id="vacRecreateBtn" type="button"' + (v.createLoading ? " disabled" : "") + ">" +
      (v.createLoading ? "Создаю…" : "📅 Пересоздать календарь") + "</button>" +
      '<div class="vac-list">' + v.items.map(vaccineRowHtml).join("") + "</div>";
    body.innerHTML = html;

    body.querySelector("#vacRecreateBtn").addEventListener("click", function () { submitVaccinesCreate(root); });
    body.querySelectorAll("[data-vac-done]").forEach(function (btn) {
      btn.addEventListener("click", function () { markVaccineDone(root, parseInt(btn.getAttribute("data-vac-done"), 10)); });
    });
    body.querySelectorAll("[data-vac-info]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        toggleVaccineInfo(root, parseInt(btn.getAttribute("data-vac-info"), 10), btn.getAttribute("data-vac-name"));
      });
    });
  }

  function vaccineRowHtml(item) {
    var v = state.vaccinesTracker;
    var isDone = !!item.done;
    var busy = v.doneLoadingId === item.id;
    var html =
      '<div class="vac-row">' +
      '<div class="vac-row__main">' +
      '<p class="vac-row__title">' + esc(item.vaccine) + "</p>" +
      '<p class="vac-row__date">' + esc(item.scheduled_date) + "</p>" +
      "</div>" +
      '<span class="vac-status ' + (isDone ? "vac-status--done" : "vac-status--pending") + '">' +
      (isDone ? "✅ Сделана" : "⏳ Запланирована") + "</span>" +
      "</div>" +
      '<div class="vac-row__actions">' +
      '<button class="vac-btn" type="button" data-vac-info="' + item.id + '" data-vac-name="' + esc(item.vaccine) + '">Подробнее</button>' +
      (isDone ? "" : '<button class="vac-btn vac-btn--primary" type="button" data-vac-done="' + item.id + '"' + (busy ? " disabled" : "") + ">" + (busy ? "Отмечаю…" : "Отметить сделанной") + "</button>") +
      "</div>";
    if (v.infoOpenId === item.id) html += vaccineInfoHtml();
    return html;
  }

  function vaccineInfoHtml() {
    var v = state.vaccinesTracker;
    if (v.infoLoading) return '<div class="vac-info state-message">Готовлю справку…</div>';
    if (v.infoError) return '<div class="vac-info pr-error">' + esc(v.infoError) + "</div>";
    if (v.infoAnswer) return '<div class="vac-info ai-q-answer">' + esc(v.infoAnswer).replace(/\n/g, "<br>") + "</div>";
    return "";
  }

  function submitVaccinesCreate(root) {
    var v = state.vaccinesTracker;
    v.createLoading = true;
    v.createError = "";
    v.createMessage = "";
    renderVaccinesBody(root);
    apiPost("/vaccines/create-schedule", {}).then(function (data) {
      if (state.screen !== "vaccines-tracker") return;
      state.vaccinesTracker.createLoading = false;
      state.vaccinesTracker.createMessage = "✅ Календарь создан! Добавлено " + ((data && data.added) || 0) + " прививок.";
      loadVaccinesList(root);
    }).catch(function (err) {
      if (state.screen !== "vaccines-tracker") return;
      state.vaccinesTracker.createLoading = false;
      state.vaccinesTracker.createError = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы создать календарь."
        : (err && err.code === 400)
        ? "Сначала укажи в боте «Мамин помощник» дату рождения малыша."
        : "Не получилось создать календарь. Попробуй ещё раз чуть позже.";
      renderVaccinesBody(root);
    });
  }

  function markVaccineDone(root, vacId) {
    var v = state.vaccinesTracker;
    v.doneLoadingId = vacId;
    v.doneError = "";
    renderVaccinesBody(root);
    apiPost("/vaccines/" + vacId + "/done", {}).then(function () {
      if (state.screen !== "vaccines-tracker") return;
      state.vaccinesTracker.doneLoadingId = null;
      state.vaccinesTracker.items = state.vaccinesTracker.items.map(function (it) {
        if (it.id === vacId) { it.done = true; it.status = "done"; }
        return it;
      });
      renderVaccinesBody(root);
    }).catch(function (err) {
      if (state.screen !== "vaccines-tracker") return;
      state.vaccinesTracker.doneLoadingId = null;
      state.vaccinesTracker.doneError = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы отметить прививку."
        : (err && err.code === 404)
        ? "Эта прививка недоступна."
        : "Не получилось отметить прививку. Попробуй ещё раз чуть позже.";
      renderVaccinesBody(root);
    });
  }

  function toggleVaccineInfo(root, vacId, vaccineName) {
    var v = state.vaccinesTracker;
    if (v.infoOpenId === vacId) {
      v.infoOpenId = null;
      v.infoError = "";
      v.infoAnswer = "";
      renderVaccinesBody(root);
      return;
    }
    v.infoOpenId = vacId;
    v.infoLoading = true;
    v.infoError = "";
    v.infoAnswer = "";
    renderVaccinesBody(root);
    apiGet("/vaccines/info?name=" + encodeURIComponent(vaccineName || "")).then(function (data) {
      if (state.screen !== "vaccines-tracker" || state.vaccinesTracker.infoOpenId !== vacId) return;
      state.vaccinesTracker.infoLoading = false;
      state.vaccinesTracker.infoAnswer = (data && data.answer) || "";
      renderVaccinesBody(root);
    }).catch(function (err) {
      if (state.screen !== "vaccines-tracker" || state.vaccinesTracker.infoOpenId !== vacId) return;
      state.vaccinesTracker.infoLoading = false;
      state.vaccinesTracker.infoError = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы получить справку."
        : "Не получилось получить справку. Попробуй ещё раз чуть позже.";
      renderVaccinesBody(root);
    });
  }

  function renderStub(root) {
    var stub = STUBS[state.stubKey] || { title: "Раздел", icon: "icon-history-3d.webp" };
    var stubIsEmblem = stub.icon.indexOf("mama_") === 0;
    root.innerHTML =
      '<div class="screen">' +
      '<div class="stub-scene" id="stubScreen">' +
      backButtonHtml("home") +
      '<img class="stub-icon" src="' + (stubIsEmblem ? ICONS_EMBLEM : ICONS_HOME) + stub.icon + '" alt="" loading="lazy">' +
      '<div class="state-message">' +
      '<p class="state-message__title">' + esc(stub.title) + "</p>" +
      "<p>Раздел подключается. Эта функция уже работает в чат-боте «Мамин помощник» и скоро появится прямо в мини-приложении.</p>" +
      "</div></div></div>";
    bindBack(root);
  }

  function bindBack(root) {
    root.querySelectorAll("[data-back]").forEach(function (el) {
      el.addEventListener("click", function () { navigate(el.getAttribute("data-back")); });
    });
  }

  // Единая точка выхода "назад" для нативной кнопки платформы (MAX/Telegram BackButton) —
  // использует ту же внутреннюю навигацию, что и экранная кнопка "← Назад", а не закрывает Mini App.
  function appBack() {
    var root = document.getElementById("screenRoot");
    if (state.screen === "recovery") {
      if (state.recovery.choice) {
        state.recovery = { choice: null, loading: false, error: "", answer: "" };
        renderRecovery(root);
      } else {
        navigate("mom-support");
      }
      return;
    }
    if (state.screen === "child-hub") {
      if (state.child.choice) {
        state.child = { choice: null, loading: false, error: "", answer: "", moreLoading: false, moreError: "" };
        renderChildHub(root);
      } else {
        navigate(state.childHubFrom || "assistant");
      }
      return;
    }
    if (state.screen === "firstdays-hub") {
      if (state.firstdays.choice) {
        state.firstdays = { choice: null, loading: false, error: "", answer: "" };
        renderFirstdaysHub(root);
      } else {
        navigate("child-hub");
      }
      return;
    }
    if (state.screen === "benefits") {
      if (state.benefits.choice) {
        state.benefits = { choice: null, loading: false, error: "", answer: "", personalText: "", personalAnswer: "", personalLoading: false, personalError: "" };
        renderBenefits(root);
      } else {
        navigate("mom-support");
      }
      return;
    }
    if (state.screen === "pregnancy") {
      if (state.pregnancy.choice) {
        state.pregnancy.choice = null;
        state.pregnancy.choiceLoading = false;
        state.pregnancy.choiceError = "";
        state.pregnancy.answer = "";
        renderPregnancy(root);
      } else {
        navigate("home");
      }
      return;
    }
    if (state.screen === "emergency") {
      if (state.emergency.view !== "list") {
        state.emergency.view = "list";
        state.emergency.guideKey = null;
        state.emergency.other = { text: "", answer: "", loading: false, error: "" };
        renderEmergency(root);
      } else {
        navigate(state.emergencyFrom || "assistant");
      }
      return;
    }
    if (state.screen === "feedback") {
      if (state.feedback.kind) {
        state.feedback = { kind: null, text: "", loading: false, error: "", success: false, successMessage: "" };
        renderFeedback(root);
      } else {
        navigate("profile");
      }
      return;
    }
    if (state.screen === "reset-me-done") {
      navigate("profile");
      return;
    }
    if (state.screen === "donate") {
      if (state.donate.phase !== "pick") {
        state.donate.phase = "pick";
        state.donate.payError = "";
        renderDonate(root);
      } else {
        navigate("profile");
      }
      return;
    }
    if (state.screen === "photo-analysis") {
      if (state.photoAnalysis.type) {
        if (state.photoAnalysis.previewUrl) { try { URL.revokeObjectURL(state.photoAnalysis.previewUrl); } catch (e) { /* not fatal */ } }
        state.photoAnalysis = { type: null, fileName: "", previewUrl: "", file: null, loading: false, error: "", answer: "", match: null, message: "" };
        renderPhotoAnalysis(root);
      } else {
        navigate(state.photoAnalysisFrom || "assistant");
      }
      return;
    }
    if (state.screen === "complementary-feeding") {
      cfGoBack(root);
      return;
    }
    var backEl = root && root.querySelector("[data-back]");
    if (backEl) { navigate(backEl.getAttribute("data-back")); return; }
    navigate("home");
  }

  // ===== Вопрос специалисту (реальный AI-сценарий, эквивалентный Telegram-боту) =====
  function renderAiQuestion(root) {
    root.innerHTML =
      '<div class="screen">' +
      backButtonHtml(state.aiQuestionFrom || "home") +
      '<div class="ai-q-scene" id="aiQuestionScreen">' +
      '<img class="ai-q-icon" src="' + ICONS_EMBLEM + 'mama_specialist_light.webp" alt="" loading="lazy">' +
      '<p class="section-heading" style="margin:0 0 2px;text-align:center">Вопрос специалисту</p>' +
      '<p class="ai-q-hint">О беременности, ребёнке, здоровье, воспитании, психологии — отвечу с учётом твоей ситуации 💕</p>' +
      '<div id="aiQuestionBody"></div>' +
      "</div></div>";
    bindBack(root);
    renderAiQuestionBody(root.querySelector("#aiQuestionBody"));
  }

  // Общий компонент вопрос/ответ поверх /ask-question. Используется и «Вопрос специалисту»,
  // и «Школа» — второй только добавляет тематический префикс к тексту вопроса перед отправкой,
  // без отдельного AI prompt на backend.
  function renderQuestionBody(body, qState, topicPrefix) {
    if (!body) return;

    if (qState.answer) {
      body.innerHTML =
        '<div class="ai-q-answer">' + esc(qState.answer).replace(/\n/g, "<br>") + "</div>" +
        '<button class="btn-primary" id="aiQuestionAgain" type="button">Задать ещё вопрос</button>';
      body.querySelector("#aiQuestionAgain").addEventListener("click", function () {
        qState.text = "";
        qState.answer = "";
        qState.loading = false;
        qState.error = "";
        renderQuestionBody(body, qState, topicPrefix);
      });
      return;
    }

    var maxLen = MINIAPP_ASK_QUESTION_MAX_LEN - (topicPrefix ? topicPrefix.length : 0);
    body.innerHTML =
      '<label class="pr-field">' +
      '<span class="pr-field__label">Опишите ситуацию или задайте вопрос</span>' +
      '<textarea id="aiQuestionInput" class="pr-textarea" rows="5" maxlength="' + maxLen + '" placeholder="Опишите ситуацию или задайте вопрос"' + (qState.loading ? " disabled" : "") + ">" + esc(qState.text) + "</textarea>" +
      "</label>" +
      (qState.error ? '<div class="pr-error">' + esc(qState.error) + "</div>" : "") +
      '<button class="btn-primary" id="aiQuestionSubmit" type="button"' + (qState.loading ? " disabled" : "") + ">" + (qState.loading ? "Думаю…" : "Получить ответ") + "</button>";

    var textarea = body.querySelector("#aiQuestionInput");
    var submitBtn = body.querySelector("#aiQuestionSubmit");
    textarea.addEventListener("input", function () { qState.text = textarea.value; });

    submitBtn.addEventListener("click", function () {
      var question = (textarea.value || "").trim();
      if (!question) {
        qState.error = "Напиши вопрос перед отправкой.";
        renderQuestionBody(body, qState, topicPrefix);
        return;
      }
      qState.text = question;
      qState.loading = true;
      qState.error = "";
      renderQuestionBody(body, qState, topicPrefix);

      var payload = topicPrefix ? topicPrefix + question : question;
      apiPost("/ask-question", { question: payload }).then(function (data) {
        qState.loading = false;
        qState.answer = (data && data.answer) || "";
        renderQuestionBody(body, qState, topicPrefix);
      }).catch(function (err) {
        qState.loading = false;
        if (err && err.code === 401) {
          qState.error = "Открой мини-приложение из бота «Мамин помощник», чтобы задать вопрос.";
        } else if (err && err.code === 400) {
          qState.error = "Напиши вопрос перед отправкой.";
        } else {
          qState.error = "Не получилось получить ответ. Попробуй ещё раз чуть позже.";
        }
        renderQuestionBody(body, qState, topicPrefix);
      });
    });
  }

  function renderAiQuestionBody(body) {
    renderQuestionBody(body, state.aiQuestion, null);
  }

  // ===== Школа (тот же AI-сценарий, что «Вопрос специалисту», с тематическим префиксом) =====
  function renderSchool(root) {
    root.innerHTML =
      '<div class="screen">' +
      backButtonHtml(state.schoolFrom || "home") +
      '<div class="ai-q-scene" id="schoolScreen">' +
      '<img class="ai-q-icon" src="' + ICONS_EMBLEM + 'mama_school_light.webp" alt="" loading="lazy">' +
      '<p class="section-heading" style="margin:0 0 2px;text-align:center">Школа</p>' +
      '<p class="ai-q-hint">Можно спросить про адаптацию, уроки, оценки, тревожность, отношения с учителем и одноклассниками 💕</p>' +
      '<div id="schoolBody"></div>' +
      "</div></div>";
    bindBack(root);
    renderQuestionBody(root.querySelector("#schoolBody"), state.school, SCHOOL_TOPIC_PREFIX);
  }

  // ===== Истерики и эмоции (реальный AI-сценарий mama_tantrums/mama_emotions из Telegram) =====
  function renderTantrumEmotions(root) {
    var t = state.tantrumEmotions;
    root.innerHTML =
      '<div class="screen">' +
      '<button class="btn-back" id="teBack" type="button">← Назад</button>' +
      '<div class="ai-q-scene" id="tantrumEmotionsScreen">' +
      '<img class="ai-q-icon" src="' + ICONS_EMBLEM + 'mama_tantrums_emotions_light.webp" alt="" loading="lazy">' +
      '<p class="section-heading" style="margin:0 0 2px;text-align:center">Истерики и эмоции</p>' +
      (!t.choice ? '<p class="ai-q-hint">Выбери, с чем помочь прямо сейчас 💕</p>' : "") +
      '<div id="tantrumEmotionsBody"></div>' +
      "</div></div>";

    root.querySelector("#teBack").addEventListener("click", function () {
      if (state.tantrumEmotions.choice) {
        state.tantrumEmotions = { choice: null, loading: false, error: "", answer: "" };
        renderTantrumEmotions(root);
      } else {
        navigate(state.tantrumEmotionsFrom || "assistant");
      }
    });

    renderTantrumEmotionsBody(root, root.querySelector("#tantrumEmotionsBody"));
  }

  function renderTantrumEmotionsBody(root, body) {
    if (!body) return;
    var t = state.tantrumEmotions;

    if (!t.choice) {
      body.innerHTML =
        '<div class="row-list">' +
        TANTRUM_EMOTIONS_OPTIONS.map(function (opt) {
          var optIsEmblem = opt.icon.indexOf("mama_") === 0;
          return (
            '<button class="row-card" data-te-option="' + esc(opt.key) + '" type="button">' +
            '<img class="row-card__icon" src="' + (optIsEmblem ? ICONS_EMBLEM : ICONS) + opt.icon + '" alt="" loading="lazy">' +
            "<span><p class=\"row-card__title\">" + esc(opt.title) + "</p>" +
            '<p class="row-card__sub">' + esc(opt.sub) + "</p></span></button>"
          );
        }).join("") +
        "</div>";
      body.querySelectorAll("[data-te-option]").forEach(function (el) {
        el.addEventListener("click", function () {
          var key = el.getAttribute("data-te-option");
          state.tantrumEmotions = { choice: key, loading: true, error: "", answer: "" };
          renderTantrumEmotions(root);
          requestTantrumEmotionsAnswer(root, key);
        });
      });
      return;
    }

    var opt = TANTRUM_EMOTIONS_OPTIONS.filter(function (o) { return o.key === t.choice; })[0];

    if (t.loading) {
      body.innerHTML = '<div class="state-message"><p class="state-message__title">' + esc(opt.title) + "</p><p>Думаю над ответом…</p></div>";
      return;
    }

    if (t.error) {
      body.innerHTML =
        '<p class="ai-q-hint">' + esc(opt.title) + "</p>" +
        '<div class="pr-error">' + esc(t.error) + "</div>" +
        '<button class="btn-primary" id="teRetry" type="button">Попробовать ещё раз</button>';
      body.querySelector("#teRetry").addEventListener("click", function () {
        state.tantrumEmotions.loading = true;
        state.tantrumEmotions.error = "";
        renderTantrumEmotionsBody(root, body);
        requestTantrumEmotionsAnswer(root, t.choice);
      });
      return;
    }

    body.innerHTML =
      '<div class="ai-q-answer">' + esc(t.answer).replace(/\n/g, "<br>") + "</div>" +
      '<button class="btn-primary" id="teAgain" type="button">Получить ответ ещё раз</button>';
    body.querySelector("#teAgain").addEventListener("click", function () {
      state.tantrumEmotions.loading = true;
      state.tantrumEmotions.error = "";
      state.tantrumEmotions.answer = "";
      renderTantrumEmotionsBody(root, body);
      requestTantrumEmotionsAnswer(root, t.choice);
    });
  }

  function requestTantrumEmotionsAnswer(root, key) {
    var opt = TANTRUM_EMOTIONS_OPTIONS.filter(function (o) { return o.key === key; })[0];
    apiPost(opt.endpoint, {}).then(function (data) {
      if (state.screen !== "tantrum-emotions" || state.tantrumEmotions.choice !== key) return;
      state.tantrumEmotions.loading = false;
      state.tantrumEmotions.answer = (data && data.answer) || "";
      renderTantrumEmotionsBody(root, root.querySelector("#tantrumEmotionsBody"));
    }).catch(function (err) {
      if (state.screen !== "tantrum-emotions" || state.tantrumEmotions.choice !== key) return;
      state.tantrumEmotions.loading = false;
      if (err && err.code === 401) {
        state.tantrumEmotions.error = "Открой мини-приложение из бота «Мамин помощник», чтобы получить ответ.";
      } else if (err && err.code === 400) {
        state.tantrumEmotions.error = "Сначала заверши короткую анкету в чат-боте «Мамин помощник» — там указывается возраст ребёнка.";
      } else {
        state.tantrumEmotions.error = "Не получилось получить ответ. Попробуй ещё раз чуть позже.";
      }
      renderTantrumEmotionsBody(root, root.querySelector("#tantrumEmotionsBody"));
    });
  }

  function historyItemHtml(item) {
    return (
      '<div class="history-row">' +
      "<div><p class=\"history-row__label\">" + esc(item.label) + "</p>" +
      '<p class="history-row__detail">' + esc(item.detail || "—") + "</p></div>" +
      '<span class="history-row__time">' + esc(formatDate(item.created_at)) + "</span>" +
      "</div>"
    );
  }

  function formatDate(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return iso.slice(0, 16).replace("T", " ");
    var dd = String(d.getDate()).padStart(2, "0");
    var mm = String(d.getMonth() + 1).padStart(2, "0");
    var hh = String(d.getHours()).padStart(2, "0");
    var mi = String(d.getMinutes()).padStart(2, "0");
    return dd + "." + mm + " " + hh + ":" + mi;
  }

  function renderHistory(root) {
    root.innerHTML =
      '<div class="screen">' +
      '<div class="history-scene" id="historyScreen">' +
      '<div class="history-top">' +
      '<img class="history-top__icon" src="' + ICONS_EMBLEM + 'mama_history_light.webp" alt="" loading="lazy">' +
      '<div><p class="section-heading" style="margin:0">История</p>' +
      '<p class="history-top__sub">Последние записи из дневника</p></div>' +
      "</div>" +
      '<div class="history-filters" id="historyTabs">' +
      HISTORY_FILTERS.map(function (f) {
        return '<button type="button" class="history-filter-chip' + (state.historyFilter === f.key ? " is-active" : "") + '" data-filter="' + esc(f.key) + '">' + esc(f.label) + "</button>";
      }).join("") +
      "</div>" +
      '<div id="historyList" class="history-list">' +
      '<div class="state-message">Загружаем историю…</div>' +
      "</div></div></div>";

    root.querySelectorAll("[data-filter]").forEach(function (el) {
      el.addEventListener("click", function () {
        state.historyFilter = el.getAttribute("data-filter");
        navigate("history", { historyFilter: state.historyFilter });
      });
    });

    apiGet("/history/recent").then(function (data) {
      var list = document.getElementById("historyList");
      if (!list) return;
      var items = (data.items || []).filter(function (it) {
        return !state.historyFilter || it.type === state.historyFilter;
      });
      if (!items.length) {
        list.innerHTML =
          '<div class="history-empty">' +
          '<img class="history-empty__icon" src="' + ICONS_EMBLEM + 'mama_history_light.webp" alt="" loading="lazy">' +
          '<p class="history-empty__title">Пока пусто</p>' +
          '<p class="history-empty__text">Здесь появятся записи из дневника: сон, питание и самочувствие.</p></div>';
        return;
      }
      list.innerHTML = items.map(historyItemHtml).join("");
    }).catch(function (err) {
      var list = document.getElementById("historyList");
      if (!list) return;
      if (err && err.code === 401) {
        list.innerHTML = '<div class="state-message"><p class="state-message__title">Нужен вход через Telegram</p><p>Открой мини-приложение из бота «Мамин помощник», чтобы увидеть свою историю.</p></div>';
      } else {
        list.innerHTML = '<div class="state-message"><p class="state-message__title">Не получилось загрузить</p><p>Попробуй ещё раз чуть позже.</p></div>';
      }
    });
  }

  function platformLabel() {
    var p = Platform.getPlatform();
    if (p === "telegram") return "Telegram";
    if (p === "max") return "MAX";
    return "Web";
  }

  function openExternal(url) {
    Platform.openLink(url);
  }

  function renderProfile(root) {
    root.innerHTML =
      '<div class="screen">' +
      '<div class="profile-scene" id="profileScreen">' +
      '<div class="profile-top">' +
      '<img class="profile-top__icon" src="' + ICONS_EMBLEM + 'mama_profile_light.webp" alt="" loading="lazy">' +
      '<p class="section-heading" style="margin:0">Профиль</p>' +
      "</div>" +
      '<div id="profileBody"><div class="state-message">Загружаем профиль…</div></div>' +
      '<div class="profile-actions">' +
      '<button class="profile-action" id="profileChannelBtn" type="button">' +
      '<svg viewBox="0 0 24 24" class="profile-action__icon" aria-hidden="true"><path d="M3 11.5 21 4l-7.5 18-3-7-7-3.5Z"/></svg>' +
      "<span>Канал «Я мама»</span>" +
      '<span class="profile-action__chevron">→</span>' +
      "</button>" +
      '<button class="profile-action" id="profileDonateBtn" type="button">' +
      '<img class="profile-action__icon" src="' + ICONS_EMBLEM + 'mama_support_project_light.webp" alt="" loading="lazy">' +
      "<span>Поддержать проект</span>" +
      '<span class="profile-action__chevron">→</span>' +
      "</button>" +
      '<button class="profile-action" id="profileFeedbackBtn" type="button">' +
      '<img class="profile-action__icon" src="' + ICONS_EMBLEM + 'mama_feedback_light.webp" alt="" loading="lazy">' +
      "<span>Обратная связь</span>" +
      '<span class="profile-action__chevron">→</span>' +
      "</button>" +
      '<button class="profile-action" id="profileInviteBtn" type="button">' +
      '<img class="profile-action__icon" src="' + ICONS_EMBLEM + 'mama_invite_friend_light.webp" alt="" loading="lazy">' +
      "<span>Пригласить друга</span>" +
      '<span class="profile-action__chevron">→</span>' +
      "</button>" +
      '<button class="profile-action profile-action--danger" id="profileResetMeBtn" type="button">' +
      '<svg viewBox="0 0 24 24" class="profile-action__icon" aria-hidden="true"><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m-8 0 1 13a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1l1-13"/></svg>' +
      "<span>Удалить мои данные</span>" +
      '<span class="profile-action__chevron">→</span>' +
      "</button>" +
      "</div>" +
      "</div></div>";

    root.querySelector("#profileChannelBtn").addEventListener("click", function () { openExternal(CHANNEL_URL); });
    root.querySelector("#profileDonateBtn").addEventListener("click", function () { runAction({ type: "stub", stub: "donate" }); });
    root.querySelector("#profileFeedbackBtn").addEventListener("click", function () {
      state.feedback = { kind: null, text: "", loading: false, error: "", success: false, successMessage: "" };
      navigate("feedback");
    });
    root.querySelector("#profileInviteBtn").addEventListener("click", function () { navigate("invite"); });
    root.querySelector("#profileResetMeBtn").addEventListener("click", function () {
      state.resetMe = { confirm: false, loading: false, error: "", success: false };
      navigate("reset-me");
    });

    loadProfileBody(root);
  }

  function loadProfileBody(root) {
    var loadingBody = document.getElementById("profileBody");
    if (loadingBody) loadingBody.innerHTML = '<div class="state-message">Загружаем профиль…</div>';
    apiGet("/profile").then(function (data) {
      var body = document.getElementById("profileBody");
      if (!body) return;
      if (!data.registered) {
        body.innerHTML = '<div class="state-message"><p class="state-message__title">Регистрация не завершена</p><p>Заверши короткую анкету в чат-боте «Мамин помощник» — тогда профиль появится и здесь.</p></div>';
        return;
      }
      var modeLabel = data.mode === "pregnant" ? "Беременность" : data.mode ? "Мама" : "—";
      var extra = "";
      if (data.mode === "pregnant" && data.pregnancy_weeks != null) {
        extra = '<div class="field-row"><span class="field-row__label">Срок</span><span class="field-row__value">' + esc(data.pregnancy_weeks) + " нед.</span></div>";
      } else if (data.child_months != null) {
        extra = '<div class="field-row"><span class="field-row__label">Возраст малыша</span><span class="field-row__value">' + esc(data.child_months) + " мес.</span></div>";
      }
      body.innerHTML =
        '<div class="profile-list">' +
        '<div class="field-row"><span class="field-row__label">Имя</span><span class="field-row__value">' + esc(data.name || "—") + "</span></div>" +
        '<div class="field-row"><span class="field-row__label">Режим</span><span class="field-row__value">' + esc(modeLabel) + "</span></div>" +
        extra +
        '<div class="field-row"><span class="field-row__label">Платформа</span><span class="field-row__value">' + esc(platformLabel()) + "</span></div>" +
        '<div class="field-row"><span class="field-row__label">Статус</span><span class="field-row__value">Все функции бесплатно</span></div>' +
        "</div>";
    }).catch(function (err) {
      var body = document.getElementById("profileBody");
      if (!body) return;
      if (err && err.code === 401) {
        body.innerHTML = '<div class="state-message"><p class="state-message__title">Нужен вход через Telegram</p><p>Открой мини-приложение из бота «Мамин помощник», чтобы увидеть профиль.</p></div>';
      } else {
        body.innerHTML =
          '<div class="state-message"><p class="state-message__title">Не получилось загрузить</p><p>Попробуй ещё раз чуть позже.</p></div>' +
          '<button class="btn-primary" id="profileRetryBtn" type="button">Попробовать ещё раз</button>';
        var retryBtn = body.querySelector("#profileRetryBtn");
        if (retryBtn) retryBtn.addEventListener("click", function () { loadProfileBody(root); });
      }
    });
  }

  // ===== Удалить мои данные (Профиль → Удалить мои данные): перенос reset_me/reset_me_confirm
  // из чат-бота через POST /api/miniapp/reset-me. Тот же список данных, что удаляет Telegram-
  // сценарий; платёжная история не затрагивается. Два отдельных шага (описание -> подтверждение),
  // Back на любом шаге до финального нажатия ведёт в Профиль (backButtonHtml("profile")). После
  // успеха — полная перезагрузка страницы, чтобы гарантированно не осталось закэшированного в
  // памяти состояния (история психолога, черновики и т.п.) и профиль подхватился как незаполненный.
  function renderResetMe(root) {
    var r = state.resetMe;

    if (r.success) {
      root.innerHTML =
        '<div class="screen">' +
        '<div class="ai-q-scene" id="resetMeScreen">' +
        '<p class="section-heading" style="margin:0 0 2px;text-align:center">Готово</p>' +
        '<p class="ai-q-hint">Ваш профиль и данные в «Мамином помощнике» удалены. Чтобы продолжить пользоваться ботом, пройдите короткую регистрацию заново.</p>' +
        '<button class="btn-primary" id="resetMeDoneBtn" type="button">Хорошо</button>' +
        "</div></div>";
      root.querySelector("#resetMeDoneBtn").addEventListener("click", function () {
        navigate("profile");
      });
      return;
    }

    if (r.confirm) {
      root.innerHTML =
        '<div class="screen">' +
        backButtonHtml("profile") +
        '<div class="ai-q-scene" id="resetMeScreen">' +
        '<p class="section-heading" style="margin:0 0 2px;text-align:center">Точно удалить всё?</p>' +
        '<p class="ai-q-hint">Это действие нельзя отменить. Профиль, дневник, трекеры и история будут удалены навсегда.</p>' +
        (r.error ? '<div class="pr-error">' + esc(r.error) + "</div>" : "") +
        '<div class="sleep-actions">' +
        '<button class="vac-btn vac-btn--primary sleep-actions__btn" id="resetMeConfirmBtn" type="button"' + (r.loading ? " disabled" : "") + ">" + (r.loading ? "Удаляю…" : "Да, удалить") + "</button>" +
        '<button class="vac-btn sleep-actions__btn" id="resetMeCancelBtn" type="button"' + (r.loading ? " disabled" : "") + ">Отмена</button>" +
        "</div>" +
        "</div></div>";
      bindBack(root);
      root.querySelector("#resetMeConfirmBtn").addEventListener("click", function () { doResetMe(root); });
      root.querySelector("#resetMeCancelBtn").addEventListener("click", function () {
        state.resetMe.confirm = false;
        state.resetMe.error = "";
        renderResetMe(root);
      });
      return;
    }

    root.innerHTML =
      '<div class="screen">' +
      backButtonHtml("profile") +
      '<div class="ai-q-scene" id="resetMeScreen">' +
      '<p class="section-heading" style="margin:0 0 2px;text-align:center">Удалить мои данные</p>' +
      '<p class="ai-q-hint">Будут удалены: дневник, записи сна и кормлений, самочувствие, рост и вес, история психолога, прививки, подписка и лимиты запросов — и ваш профиль.</p>' +
      '<div class="pr-safety-banner">Действие необратимо. Платёжная история не удаляется.</div>' +
      '<button class="btn-primary" id="resetMeStartBtn" type="button">Удалить мои данные</button>' +
      "</div></div>";
    bindBack(root);
    root.querySelector("#resetMeStartBtn").addEventListener("click", function () {
      state.resetMe.confirm = true;
      renderResetMe(root);
    });
  }

  function doResetMe(root) {
    state.resetMe.loading = true;
    state.resetMe.error = "";
    renderResetMe(root);
    apiPost("/reset-me", { confirm: true }).then(function () {
      if (state.screen !== "reset-me") return;
      window.location.href = window.location.pathname + "?screen=reset-me-done" + window.location.hash;
    }).catch(function (err) {
      if (state.screen !== "reset-me") return;
      state.resetMe.loading = false;
      state.resetMe.error = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы продолжить."
        : "Не получилось удалить данные. Попробуй ещё раз чуть позже.";
      renderResetMe(root);
    });
  }

  function renderResetMeDone(root) {
    root.innerHTML =
      '<div class="screen">' +
      '<div class="ai-q-scene" id="resetMeDoneScreen">' +
      '<p class="section-heading" style="margin:0 0 2px;text-align:center">Готово</p>' +
      '<p class="ai-q-hint">Ваш профиль и данные в «Мамином помощнике» удалены. Чтобы продолжить пользоваться ботом, пройдите короткую регистрацию заново.</p>' +
      '<button class="btn-primary" id="resetMeDoneBtn" type="button">Хорошо</button>' +
      "</div></div>";
    root.querySelector("#resetMeDoneBtn").addEventListener("click", function () {
      navigate("profile");
    });
  }

  // ===== Пригласить подругу (Профиль → Пригласить подругу): перенос invite_friend из чат-бота,
  // та же реферальная программа (/api/miniapp/referral), без новой системы бонусов =====
  function renderInvite(root) {
    root.innerHTML =
      '<div class="screen">' +
      backButtonHtml("profile") +
      '<div class="invite-scene" id="inviteScreen">' +
      '<p class="section-heading" style="margin:0 0 2px">Пригласить друга</p>' +
      '<p class="ai-q-hint">Поделись личной ссылкой — пусть больше мам узнают о «Мамином помощнике» 🤍</p>' +
      '<div id="inviteBody"><div class="state-message">Загружаем ссылку…</div></div>' +
      "</div></div>";
    bindBack(root);
    loadInviteBody(root);
  }

  function loadInviteBody(root) {
    var loadingBody = document.getElementById("inviteBody");
    if (loadingBody) loadingBody.innerHTML = '<div class="state-message">Загружаем ссылку…</div>';
    apiGet("/referral").then(function (data) {
      var body = document.getElementById("inviteBody");
      if (!body) return;
      var statsRows = '<div class="field-row"><span class="field-row__label">Приглашено</span><span class="field-row__value">' + esc(data.invited_count || 0) + "</span></div>";
      if (data.bonus_questions_granted) {
        statsRows += '<div class="field-row"><span class="field-row__label">Бонусов начислено</span><span class="field-row__value">' + esc(data.bonus_questions_granted) + "</span></div>";
      }
      if (data.bonus_questions_available) {
        statsRows += '<div class="field-row"><span class="field-row__label">Доступно бонусных вопросов</span><span class="field-row__value">' + esc(data.bonus_questions_available) + "</span></div>";
      }
      body.innerHTML =
        '<div class="invite-link-box" id="inviteLinkBox">' + esc(data.link) + "</div>" +
        '<div class="child-actions">' +
        '<button class="btn-primary" id="inviteCopyBtn" type="button">Скопировать ссылку</button>' +
        (data.share_url ? '<button class="btn-primary" id="inviteShareBtn" type="button">Поделиться</button>' : "") +
        "</div>" +
        '<div class="profile-list">' + statsRows + "</div>" +
        (data.note ? '<p class="ai-q-hint">' + esc(data.note) + "</p>" : "");
      var copyBtn = body.querySelector("#inviteCopyBtn");
      if (copyBtn) {
        copyBtn.addEventListener("click", function () {
          copyToClipboard(data.link).then(function () {
            copyBtn.textContent = "Ссылка скопирована ✓";
            setTimeout(function () { copyBtn.textContent = "Скопировать ссылку"; }, 2000);
          }).catch(function () {
            copyBtn.textContent = "Не получилось скопировать";
            setTimeout(function () { copyBtn.textContent = "Скопировать ссылку"; }, 2000);
          });
        });
      }
      var shareBtn = body.querySelector("#inviteShareBtn");
      if (shareBtn && data.share_url) {
        shareBtn.addEventListener("click", function () { Platform.openLink(data.share_url); });
      }
    }).catch(function (err) {
      var body = document.getElementById("inviteBody");
      if (!body) return;
      if (err && err.code === 401) {
        body.innerHTML = '<div class="state-message"><p class="state-message__title">Нужен вход</p><p>Открой мини-приложение из бота «Мамин помощник», чтобы получить свою ссылку.</p></div>';
      } else {
        body.innerHTML =
          '<div class="state-message"><p class="state-message__title">Не получилось загрузить</p><p>Попробуй ещё раз чуть позже.</p></div>' +
          '<button class="btn-primary" id="inviteRetryBtn" type="button">Попробовать ещё раз</button>';
        var retryBtn = body.querySelector("#inviteRetryBtn");
        if (retryBtn) retryBtn.addEventListener("click", function () { loadInviteBody(root); });
      }
    });
  }

  function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      try {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        var ok = document.execCommand("copy");
        document.body.removeChild(ta);
        if (ok) resolve(); else reject(new Error("copy_failed"));
      } catch (e) { reject(e); }
    });
  }

  // ===== Обратная связь (Профиль → Обратная связь): выбор темы -> textarea -> отправка =====
  function feedbackTopicRowHtml(item) {
    var isEmblem = item.icon.indexOf("mama_") === 0;
    return (
      '<button class="row-card" data-feedback-topic="' + esc(item.key) + '" type="button">' +
      '<img class="row-card__icon" src="' + (isEmblem ? ICONS_EMBLEM : ICONS) + item.icon + '" alt="" loading="lazy">' +
      "<span>" +
      '<p class="row-card__title">' + esc(item.title) + "</p>" +
      '<p class="row-card__sub">' + esc(item.sub) + "</p>" +
      "</span></button>"
    );
  }

  function renderFeedback(root) {
    if (state.feedback.kind) {
      renderFeedbackForm(root);
      return;
    }
    root.innerHTML =
      '<div class="screen">' +
      backButtonHtml("profile") +
      '<div class="panel">' +
      '<p class="panel__title">Обратная связь</p>' +
      '<div class="row-list">' + FEEDBACK_TOPICS.map(feedbackTopicRowHtml).join("") + "</div>" +
      "</div></div>";
    bindBack(root);
    root.querySelectorAll("[data-feedback-topic]").forEach(function (el) {
      el.addEventListener("click", function () {
        var topic = FEEDBACK_TOPICS.filter(function (t) { return t.key === el.getAttribute("data-feedback-topic"); })[0];
        if (!topic) return;
        state.feedback = { kind: topic.key, text: "", loading: false, error: "", success: false, successMessage: "" };
        renderFeedback(root);
      });
    });
  }

  function renderFeedbackForm(root) {
    var topic = FEEDBACK_TOPICS.filter(function (t) { return t.key === state.feedback.kind; })[0];
    if (!topic) {
      state.feedback = { kind: null, text: "", loading: false, error: "", success: false, successMessage: "" };
      renderFeedback(root);
      return;
    }
    root.innerHTML =
      '<div class="screen">' +
      '<button class="btn-back" id="feedbackFormBack" type="button">← Назад</button>' +
      '<div class="ai-q-scene" id="feedbackFormScreen">' +
      '<p class="section-heading" style="margin:0 0 2px;text-align:center">' + esc(topic.title) + "</p>" +
      '<div id="feedbackFormBody"></div>' +
      "</div></div>";

    root.querySelector("#feedbackFormBack").addEventListener("click", function () {
      state.feedback = { kind: null, text: "", loading: false, error: "", success: false, successMessage: "" };
      renderFeedback(root);
    });

    renderFeedbackFormBody(root, root.querySelector("#feedbackFormBody"));
  }

  function renderFeedbackFormBody(root, body) {
    if (!body) return;
    var f = state.feedback;
    var topic = FEEDBACK_TOPICS.filter(function (t) { return t.key === f.kind; })[0];
    if (!topic) return;

    if (f.success) {
      body.innerHTML =
        '<div class="ai-q-answer">' + esc(f.successMessage || "Спасибо! Сообщение отправлено.").replace(/\n/g, "<br>") + "</div>" +
        '<button class="btn-primary" id="feedbackAgainBtn" type="button">К выбору темы</button>';
      body.querySelector("#feedbackAgainBtn").addEventListener("click", function () {
        state.feedback = { kind: null, text: "", loading: false, error: "", success: false, successMessage: "" };
        renderFeedback(root);
      });
      return;
    }

    body.innerHTML =
      '<label class="pr-field">' +
      '<span class="pr-field__label">' + esc(topic.placeholder) + "</span>" +
      '<textarea id="feedbackTextInput" class="pr-textarea" rows="6" maxlength="' + MINIAPP_FEEDBACK_MAX_LEN + '" placeholder="' + esc(topic.placeholder) + '"' + (f.loading ? " disabled" : "") + ">" + esc(f.text) + "</textarea>" +
      "</label>" +
      (f.error ? '<div class="pr-error">' + esc(f.error) + "</div>" : "") +
      '<button class="btn-primary" id="feedbackSubmitBtn" type="button"' + (f.loading ? " disabled" : "") + ">" + (f.loading ? "Отправляем…" : "Отправить") + "</button>";

    var textarea = body.querySelector("#feedbackTextInput");
    var submitBtn = body.querySelector("#feedbackSubmitBtn");
    textarea.addEventListener("input", function () { state.feedback.text = textarea.value; });

    submitBtn.addEventListener("click", function () {
      var text = (textarea.value || "").trim();
      if (!text) {
        state.feedback.error = "Напиши сообщение перед отправкой.";
        renderFeedbackFormBody(root, body);
        return;
      }
      state.feedback.text = text;
      state.feedback.loading = true;
      state.feedback.error = "";
      renderFeedbackFormBody(root, body);

      apiPost(topic.endpoint, { text: text }).then(function (data) {
        if (state.screen !== "feedback" || state.feedback.kind !== topic.key) return;
        state.feedback.loading = false;
        state.feedback.success = true;
        state.feedback.successMessage = (data && data.message) || "Спасибо! Сообщение отправлено.";
        renderFeedbackFormBody(root, root.querySelector("#feedbackFormBody"));
      }).catch(function (err) {
        if (state.screen !== "feedback" || state.feedback.kind !== topic.key) return;
        state.feedback.loading = false;
        if (err && err.code === 401) {
          state.feedback.error = "Открой мини-приложение из бота «Мамин помощник», чтобы отправить сообщение.";
        } else if (err && err.code === 400) {
          state.feedback.error = "Напиши сообщение перед отправкой.";
        } else {
          state.feedback.error = "Не получилось отправить. Попробуй ещё раз чуть позже.";
        }
        renderFeedbackFormBody(root, body);
      });
    });
  }

  // ===== Поддержка мамы: хаб разделов =====
  function momSectionRowHtml(item) {
    var isEmblem = item.icon.indexOf("mama_") === 0;
    return (
      '<button class="row-card" data-mom-section="' + esc(item.key) + '" type="button">' +
      '<img class="row-card__icon" src="' + (isEmblem ? ICONS_EMBLEM : ICONS) + item.icon + '" alt="" loading="lazy">' +
      '<span>' +
      '<p class="row-card__title">' + esc(item.title) + "</p>" +
      '<p class="row-card__sub">' + esc(item.sub) + "</p>" +
      (item.price ? '<p class="row-card__price">' + item.price + ' ₽</p>' : "") +
      "</span></button>"
    );
  }

  function renderMomSupport(root) {
    root.innerHTML =
      '<div class="screen">' +
      backButtonHtml("home") +
      '<div class="panel">' +
      '<p class="panel__title">Поддержка мамы</p>' +
      '<div class="row-list">' + MOM_SUPPORT_SECTIONS.map(momSectionRowHtml).join("") + "</div>" +
      "</div></div>";
    bindBack(root);
    root.querySelectorAll("[data-mom-section]").forEach(function (el) {
      var item = MOM_SUPPORT_SECTIONS.filter(function (s) { return s.key === el.getAttribute("data-mom-section"); })[0];
      el.addEventListener("click", function () {
        if (item.screen === "mom-emotions") state.momEmotions = { loading: false, error: "", answer: "" };
        if (item.screen === "benefits") state.benefits = { choice: null, loading: false, error: "", answer: "", personalText: "", personalAnswer: "", personalLoading: false, personalError: "" };
        if (item.screen === "psycho-chat") {
          state.psychoChat = {
            items: [],
            loaded: false,
            loading: false,
            loadError: "",
            text: "",
            sending: false,
            sendError: "",
            clearConfirm: false,
            clearLoading: false,
            clearError: ""
          };
        }
        navigate(item.screen, item.fn ? { momPendingKey: item.fn } : undefined);
      });
    });
  }

  // ===== Эмоции мамы (в хабе «Поддержка мамы») — тот же сценарий mama_emotions, что и в Telegram,
  // через уже рабочий эндпоинт /api/miniapp/emotions =====
  function renderMomEmotions(root) {
    var m = state.momEmotions;
    root.innerHTML =
      '<div class="screen">' +
      backButtonHtml("mom-support") +
      '<div class="ai-q-scene" id="momEmotionsScreen">' +
      '<img class="ai-q-icon" src="' + ICONS_EMBLEM + 'mama_mom_psychologist_light.webp" alt="" loading="lazy">' +
      '<p class="section-heading" style="margin:0 0 2px;text-align:center">Эмоции мамы</p>' +
      '<div id="momEmotionsBody"></div>' +
      "</div></div>";
    bindBack(root);
    if (!m.loading && !m.answer && !m.error) {
      m.loading = true;
      requestMomEmotionsAnswer(root);
    }
    renderMomEmotionsBody(root, root.querySelector("#momEmotionsBody"));
  }

  function renderMomEmotionsBody(root, body) {
    if (!body) return;
    var m = state.momEmotions;

    if (m.loading) {
      body.innerHTML = '<div class="state-message"><p>Думаю над ответом…</p></div>';
      return;
    }

    if (m.error) {
      body.innerHTML =
        '<div class="pr-error">' + esc(m.error) + "</div>" +
        '<button class="btn-primary" id="momEmotionsRetry" type="button">Попробовать ещё раз</button>';
      body.querySelector("#momEmotionsRetry").addEventListener("click", function () {
        state.momEmotions.loading = true;
        state.momEmotions.error = "";
        renderMomEmotionsBody(root, body);
        requestMomEmotionsAnswer(root);
      });
      return;
    }

    body.innerHTML =
      '<div class="ai-q-answer">' + esc(m.answer).replace(/\n/g, "<br>") + "</div>" +
      '<button class="btn-primary" id="momEmotionsAgain" type="button">Получить ответ ещё раз</button>';
    body.querySelector("#momEmotionsAgain").addEventListener("click", function () {
      state.momEmotions.loading = true;
      state.momEmotions.error = "";
      state.momEmotions.answer = "";
      renderMomEmotionsBody(root, body);
      requestMomEmotionsAnswer(root);
    });
  }

  function requestMomEmotionsAnswer(root) {
    apiPost("/emotions", {}).then(function (data) {
      if (state.screen !== "mom-emotions") return;
      state.momEmotions.loading = false;
      state.momEmotions.answer = (data && data.answer) || "";
      renderMomEmotionsBody(root, root.querySelector("#momEmotionsBody"));
    }).catch(function (err) {
      if (state.screen !== "mom-emotions") return;
      state.momEmotions.loading = false;
      state.momEmotions.error = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы получить ответ."
        : "Не получилось получить ответ. Попробуй ещё раз чуть позже.";
      renderMomEmotionsBody(root, root.querySelector("#momEmotionsBody"));
    });
  }

  // ===== Мамин психолог (в хабе «Поддержка мамы») — тот же сценарий psycho_start/psycho_message/
  // psycho_clear, что и в Telegram и MAX-боте, через /api/miniapp/psycho/* (та же таблица
  // psycho_history, тот же PSYCHO_SYSTEM и OpenAI client на backend) =====
  function renderPsychoChat(root) {
    root.innerHTML =
      '<div class="screen">' +
      backButtonHtml("mom-support") +
      '<div class="psycho-scene" id="psychoChatScreen">' +
      '<img class="ai-q-icon" src="' + ICONS_EMBLEM + 'mama_mom_psychologist_light.webp" alt="" loading="lazy">' +
      '<p class="section-heading" style="margin:0 0 2px;text-align:center">Мамин психолог</p>' +
      '<p class="ai-q-hint">Здесь можно говорить обо всём — усталость, тревога, отношения, чувство вины, злость. ' +
      'Я помню наш разговор. Это не экстренная и не медицинская помощь — при угрозе жизни или здоровью обратись за экстренной помощью 💕</p>' +
      '<div id="psychoChatBody"></div>' +
      "</div></div>";
    bindBack(root);
    var p = state.psychoChat;
    if (!p.loaded && !p.loading) {
      p.loading = true;
      requestPsychoHistory(root);
    }
    renderPsychoChatBody(root, root.querySelector("#psychoChatBody"));
  }

  function requestPsychoHistory(root) {
    apiGet("/psycho/history").then(function (data) {
      if (state.screen !== "psycho-chat") return;
      state.psychoChat.loading = false;
      state.psychoChat.loaded = true;
      state.psychoChat.items = (data && data.items) || [];
      renderPsychoChatBody(root, root.querySelector("#psychoChatBody"));
      scrollPsychoToBottom();
    }).catch(function (err) {
      if (state.screen !== "psycho-chat") return;
      state.psychoChat.loading = false;
      state.psychoChat.loadError = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы получить ответ."
        : "Не получилось загрузить историю. Попробуй ещё раз чуть позже.";
      renderPsychoChatBody(root, root.querySelector("#psychoChatBody"));
    });
  }

  function psychoMessageHtml(msg) {
    var isUser = msg.role === "user";
    return (
      '<div class="psycho-msg ' + (isUser ? "psycho-msg--user" : "psycho-msg--assistant") + '">' +
      esc(msg.content).replace(/\n/g, "<br>") +
      "</div>"
    );
  }

  function renderPsychoChatBody(root, body) {
    if (!body) return;
    var p = state.psychoChat;

    if (p.loading && !p.loaded) {
      body.innerHTML = '<div class="state-message"><p>Загружаю историю…</p></div>';
      return;
    }

    if (p.loadError) {
      body.innerHTML =
        '<div class="pr-error">' + esc(p.loadError) + "</div>" +
        '<button class="btn-primary" id="psychoRetryLoad" type="button">Попробовать ещё раз</button>';
      body.querySelector("#psychoRetryLoad").addEventListener("click", function () {
        state.psychoChat.loading = true;
        state.psychoChat.loadError = "";
        renderPsychoChatBody(root, body);
        requestPsychoHistory(root);
      });
      return;
    }

    var risky = hasSafetyRisk(p.text);
    var html = '<div class="psycho-messages" id="psychoMessages">';
    if (!p.items.length) {
      html += '<div class="psycho-msg psycho-msg--assistant">Привет! Я твой личный психолог 💕 Здесь можно говорить обо всём — ' +
        'усталость, тревога, отношения, чувство вины, злость, растерянность. Расскажи, как ты сейчас?</div>';
    } else {
      html += p.items.map(psychoMessageHtml).join("");
    }
    if (p.sending) {
      html += '<div class="psycho-msg psycho-msg--assistant psycho-msg--typing">Думаю…</div>';
    }
    html += "</div>";

    html +=
      (risky ? '<div class="pr-safety-banner">Если сейчас есть угроза жизни или безопасности — не жди ответа здесь, обратись за экстренной помощью в своём регионе.</div>' : "") +
      (p.sendError ? '<div class="pr-error">' + esc(p.sendError) + "</div>" : "") +
      '<textarea id="psychoInput" class="pr-textarea" rows="3" maxlength="' + MINIAPP_PSYCHO_MAX_LEN + '" placeholder="Расскажи, как ты сейчас…"' + (p.sending ? " disabled" : "") + ">" + esc(p.text) + "</textarea>" +
      '<button class="btn-primary" id="psychoSend" type="button"' + (p.sending ? " disabled" : "") + ">" + (p.sending ? "Отправляю…" : "Отправить") + "</button>";

    html +=
      '<div class="psycho-actions">' +
      (p.clearConfirm
        ? ('<p class="sleep-confirm">Точно начать с чистого листа? История разговора будет удалена без возможности восстановить.</p>' +
           (p.clearError ? '<div class="pr-error">' + esc(p.clearError) + "</div>" : "") +
           '<div class="sleep-actions">' +
           '<button class="vac-btn vac-btn--primary sleep-actions__btn" id="psychoClearConfirm" type="button"' + (p.clearLoading ? " disabled" : "") + ">" + (p.clearLoading ? "Удаляю…" : "Да, очистить") + "</button>" +
           '<button class="vac-btn sleep-actions__btn" id="psychoClearCancel" type="button"' + (p.clearLoading ? " disabled" : "") + ">Отмена</button>" +
           "</div>")
        : '<button class="btn-back" id="psychoClearStart" type="button">🗑 Очистить диалог</button>') +
      "</div>";

    body.innerHTML = html;

    var textarea = body.querySelector("#psychoInput");
    textarea.addEventListener("input", function () {
      state.psychoChat.text = textarea.value;
      if (hasSafetyRisk(textarea.value) !== risky) renderPsychoChatBody(root, body);
    });

    body.querySelector("#psychoSend").addEventListener("click", function () {
      sendPsychoMessage(root, body);
    });

    var clearStartBtn = body.querySelector("#psychoClearStart");
    if (clearStartBtn) {
      clearStartBtn.addEventListener("click", function () {
        state.psychoChat.clearConfirm = true;
        state.psychoChat.clearError = "";
        renderPsychoChatBody(root, body);
      });
    }
    var clearCancelBtn = body.querySelector("#psychoClearCancel");
    if (clearCancelBtn) {
      clearCancelBtn.addEventListener("click", function () {
        state.psychoChat.clearConfirm = false;
        renderPsychoChatBody(root, body);
      });
    }
    var clearConfirmBtn = body.querySelector("#psychoClearConfirm");
    if (clearConfirmBtn) {
      clearConfirmBtn.addEventListener("click", function () {
        clearPsychoHistory(root, body);
      });
    }

    scrollPsychoToBottom();
  }

  function sendPsychoMessage(root, body) {
    var p = state.psychoChat;
    var textarea = body.querySelector("#psychoInput");
    var text = ((textarea && textarea.value) || "").trim();
    if (!text) {
      p.sendError = "Напиши сообщение перед отправкой.";
      renderPsychoChatBody(root, body);
      return;
    }
    p.items = p.items.concat([{ role: "user", content: text, created_at: "" }]);
    p.text = "";
    p.sending = true;
    p.sendError = "";
    renderPsychoChatBody(root, body);

    apiPost("/psycho/message", { message: text }).then(function (data) {
      if (state.screen !== "psycho-chat") return;
      state.psychoChat.sending = false;
      state.psychoChat.items = state.psychoChat.items.concat([{ role: "assistant", content: (data && data.answer) || "", created_at: "" }]);
      renderPsychoChatBody(root, root.querySelector("#psychoChatBody"));
    }).catch(function (err) {
      if (state.screen !== "psycho-chat") return;
      state.psychoChat.sending = false;
      state.psychoChat.sendError = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы продолжить."
        : "Не получилось отправить сообщение. Попробуй ещё раз чуть позже.";
      renderPsychoChatBody(root, root.querySelector("#psychoChatBody"));
    });
  }

  function clearPsychoHistory(root, body) {
    state.psychoChat.clearLoading = true;
    state.psychoChat.clearError = "";
    renderPsychoChatBody(root, body);
    apiPost("/psycho/clear", {}).then(function () {
      if (state.screen !== "psycho-chat") return;
      state.psychoChat.clearLoading = false;
      state.psychoChat.clearConfirm = false;
      state.psychoChat.items = [];
      renderPsychoChatBody(root, root.querySelector("#psychoChatBody"));
    }).catch(function (err) {
      if (state.screen !== "psycho-chat") return;
      state.psychoChat.clearLoading = false;
      state.psychoChat.clearError = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы продолжить."
        : "Не получилось очистить диалог. Попробуй ещё раз чуть позже.";
      renderPsychoChatBody(root, root.querySelector("#psychoChatBody"));
    });
  }

  function scrollPsychoToBottom() {
    window.requestAnimationFrame(function () {
      window.scrollTo(0, document.body.scrollHeight);
    });
  }

  // ===== Грудное вскармливание (в хабе «Поддержка мамы») — те же 6 сценариев bf_start/bf_pump/
  // bf_lactostaz/bf_food/bf_nofood/bf_formula, что и в Telegram, через /api/miniapp/content/breastfeeding =====
  function renderBreastfeeding(root) {
    var b = state.breastfeeding;
    root.innerHTML =
      '<div class="screen">' +
      '<button class="btn-back" id="bfBack" type="button">← Назад</button>' +
      '<div class="ai-q-scene" id="breastfeedingScreen">' +
      '<img class="ai-q-icon" src="' + ICONS_EMBLEM + 'mama_breastfeeding_light.webp" alt="" loading="lazy">' +
      '<p class="section-heading" style="margin:0 0 2px;text-align:center">Грудное вскармливание</p>' +
      (!b.choice ? '<p class="ai-q-hint">Выбери тему — научная поддержка на каждом этапе 💕</p>' : "") +
      '<div id="breastfeedingBody"></div>' +
      "</div></div>";

    root.querySelector("#bfBack").addEventListener("click", function () {
      if (state.breastfeeding.choice) {
        state.breastfeeding = { choice: null, loading: false, error: "", answer: "" };
        renderBreastfeeding(root);
      } else {
        navigate("mom-support");
      }
    });

    renderBreastfeedingBody(root, root.querySelector("#breastfeedingBody"));
  }

  function renderBreastfeedingBody(root, body) {
    if (!body) return;
    var b = state.breastfeeding;

    if (!b.choice) {
      body.innerHTML =
        '<div class="row-list">' +
        BREASTFEEDING_OPTIONS.map(function (opt) {
          var optIsEmblem = opt.icon.indexOf("mama_") === 0;
          return (
            '<button class="row-card" data-bf-option="' + esc(opt.key) + '" type="button">' +
            '<img class="row-card__icon" src="' + (optIsEmblem ? ICONS_EMBLEM : ICONS) + opt.icon + '" alt="" loading="lazy">' +
            "<span><p class=\"row-card__title\">" + esc(opt.title) + "</p>" +
            '<p class="row-card__sub">' + esc(opt.sub) + "</p></span></button>"
          );
        }).join("") +
        "</div>";
      body.querySelectorAll("[data-bf-option]").forEach(function (el) {
        el.addEventListener("click", function () {
          var key = el.getAttribute("data-bf-option");
          state.breastfeeding = { choice: key, loading: true, error: "", answer: "" };
          renderBreastfeeding(root);
          requestBreastfeedingAnswer(root, key);
        });
      });
      return;
    }

    var opt = BREASTFEEDING_OPTIONS.filter(function (o) { return o.key === b.choice; })[0];

    if (b.loading) {
      body.innerHTML = '<div class="state-message"><p class="state-message__title">' + esc(opt.title) + "</p><p>Думаю над ответом…</p></div>";
      return;
    }

    if (b.error) {
      body.innerHTML =
        '<p class="ai-q-hint">' + esc(opt.title) + "</p>" +
        '<div class="pr-error">' + esc(b.error) + "</div>" +
        '<button class="btn-primary" id="bfRetry" type="button">Попробовать ещё раз</button>';
      body.querySelector("#bfRetry").addEventListener("click", function () {
        state.breastfeeding.loading = true;
        state.breastfeeding.error = "";
        renderBreastfeedingBody(root, body);
        requestBreastfeedingAnswer(root, b.choice);
      });
      return;
    }

    body.innerHTML =
      '<div class="ai-q-answer">' + esc(b.answer).replace(/\n/g, "<br>") + "</div>" +
      '<button class="btn-primary" id="bfAgain" type="button">Обновить рекомендации</button>';
    body.querySelector("#bfAgain").addEventListener("click", function () {
      state.breastfeeding.loading = true;
      state.breastfeeding.error = "";
      state.breastfeeding.answer = "";
      renderBreastfeedingBody(root, body);
      requestBreastfeedingAnswer(root, b.choice);
    });
  }

  function requestBreastfeedingAnswer(root, key) {
    var opt = BREASTFEEDING_OPTIONS.filter(function (o) { return o.key === key; })[0];
    apiGet(opt.endpoint).then(function (data) {
      if (state.screen !== "breastfeeding" || state.breastfeeding.choice !== key) return;
      state.breastfeeding.loading = false;
      state.breastfeeding.answer = (data && data.answer) || "";
      renderBreastfeedingBody(root, root.querySelector("#breastfeedingBody"));
    }).catch(function (err) {
      if (state.screen !== "breastfeeding" || state.breastfeeding.choice !== key) return;
      state.breastfeeding.loading = false;
      state.breastfeeding.error = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы получить ответ."
        : "Не получилось получить ответ. Попробуй ещё раз чуть позже.";
      renderBreastfeedingBody(root, root.querySelector("#breastfeedingBody"));
    });
  }

  // ===== Восстановление мамы (в хабе «Поддержка мамы») — те же 6 сценариев rec_natural/rec_caesar/
  // rec_sport/rec_intimate/rec_hair/rec_diastaz, что и в Telegram, через /api/miniapp/content/recovery =====
  function renderRecovery(root) {
    var r = state.recovery;
    root.innerHTML =
      '<div class="screen">' +
      '<button class="btn-back" id="recBack" type="button">← Назад</button>' +
      '<div class="ai-q-scene" id="recoveryScreen">' +
      '<img class="ai-q-icon" src="' + ICONS_EMBLEM + 'mama_mom_recovery_light.webp" alt="" loading="lazy">' +
      '<p class="section-heading" style="margin:0 0 2px;text-align:center">Восстановление мамы</p>' +
      (!r.choice ? '<p class="ai-q-hint">Выбери тему — твоё здоровье так же важно, как здоровье малыша 💕</p>' : "") +
      '<div id="recoveryBody"></div>' +
      "</div></div>";

    root.querySelector("#recBack").addEventListener("click", function () {
      if (state.recovery.choice) {
        state.recovery = { choice: null, loading: false, error: "", answer: "" };
        renderRecovery(root);
      } else {
        navigate("mom-support");
      }
    });

    renderRecoveryBody(root, root.querySelector("#recoveryBody"));
  }

  function renderRecoveryBody(root, body) {
    if (!body) return;
    var r = state.recovery;

    if (!r.choice) {
      body.innerHTML =
        '<div class="row-list">' +
        RECOVERY_OPTIONS.map(function (opt) {
          var optIsEmblem = opt.icon.indexOf("mama_") === 0;
          return (
            '<button class="row-card" data-rec-option="' + esc(opt.key) + '" type="button">' +
            '<img class="row-card__icon" src="' + (optIsEmblem ? ICONS_EMBLEM : ICONS) + opt.icon + '" alt="" loading="lazy">' +
            "<span><p class=\"row-card__title\">" + esc(opt.title) + "</p>" +
            '<p class="row-card__sub">' + esc(opt.sub) + "</p></span></button>"
          );
        }).join("") +
        "</div>";
      body.querySelectorAll("[data-rec-option]").forEach(function (el) {
        el.addEventListener("click", function () {
          var key = el.getAttribute("data-rec-option");
          state.recovery = { choice: key, loading: true, error: "", answer: "" };
          renderRecovery(root);
          requestRecoveryAnswer(root, key);
        });
      });
      return;
    }

    var opt = RECOVERY_OPTIONS.filter(function (o) { return o.key === r.choice; })[0];

    if (r.loading) {
      body.innerHTML = '<div class="state-message"><p class="state-message__title">' + esc(opt.title) + "</p><p>Думаю над ответом…</p></div>";
      return;
    }

    if (r.error) {
      body.innerHTML =
        '<p class="ai-q-hint">' + esc(opt.title) + "</p>" +
        '<div class="pr-error">' + esc(r.error) + "</div>" +
        '<button class="btn-primary" id="recRetry" type="button">Попробовать ещё раз</button>';
      body.querySelector("#recRetry").addEventListener("click", function () {
        state.recovery.loading = true;
        state.recovery.error = "";
        renderRecoveryBody(root, body);
        requestRecoveryAnswer(root, r.choice);
      });
      return;
    }

    body.innerHTML =
      '<div class="ai-q-answer">' + esc(r.answer).replace(/\n/g, "<br>") + "</div>" +
      '<button class="btn-primary" id="recAgain" type="button">Обновить рекомендации</button>';
    body.querySelector("#recAgain").addEventListener("click", function () {
      state.recovery.loading = true;
      state.recovery.error = "";
      state.recovery.answer = "";
      renderRecoveryBody(root, body);
      requestRecoveryAnswer(root, r.choice);
    });
  }

  function requestRecoveryAnswer(root, key) {
    var opt = RECOVERY_OPTIONS.filter(function (o) { return o.key === key; })[0];
    apiGet(opt.endpoint).then(function (data) {
      if (state.screen !== "recovery" || state.recovery.choice !== key) return;
      state.recovery.loading = false;
      state.recovery.answer = (data && data.answer) || "";
      renderRecoveryBody(root, root.querySelector("#recoveryBody"));
    }).catch(function (err) {
      if (state.screen !== "recovery" || state.recovery.choice !== key) return;
      state.recovery.loading = false;
      state.recovery.error = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы получить ответ."
        : "Не получилось получить ответ. Попробуй ещё раз чуть позже.";
      renderRecoveryBody(root, root.querySelector("#recoveryBody"));
    });
  }

  // ===== Ребёнок (раздел в «Помощник», не в Трекерах) — каталог из 11 контентных AI-разделов
  // (development/games/books/health/meds/teeth/food/recipes/routine/sleep/family), те же сценарии
  // и промпты, что в Telegram (mama_dev и т.п.), через единый GET /content/child?topic=.
  // v2/light 2-колоночный компактный каталог (как Home/Трекеры/Помощник), персистентный фон — без
  // отдельного экрана на раздел: один экран "child-hub" переключает каталог/детали через choice,
  // как breastfeeding/recovery. Back из детали — к каталогу, back из каталога — в «Помощник».
  function renderChildHub(root) {
    var c = state.child;

    if (!c.choice) {
      root.innerHTML =
        '<div class="screen">' +
        backButtonHtml(state.childHubFrom || "assistant") +
        '<div class="assistant-scene" id="childHubScreen">' +
        '<p class="section-heading">Ребёнок</p>' +
        '<div class="shortcut-grid">' + CHILD_OPTIONS.map(cardHtml).join("") + "</div>" +
        "</div></div>";
      bindBack(root);
      root.querySelectorAll("[data-action-card]").forEach(function (el) {
        var item = CHILD_OPTIONS.filter(function (o) { return o.key === el.getAttribute("data-action-card"); })[0];
        el.addEventListener("click", function () {
          if (item.screen) {
            if (item.screen === "firstdays-hub") state.firstdays = { choice: null, loading: false, error: "", answer: "" };
            navigate(item.screen);
            return;
          }
          state.child = { choice: item.key, loading: true, error: "", answer: "", moreLoading: false, moreError: "" };
          renderChildHub(root);
          requestChildAnswer(root, item.key, item.endpoint);
        });
      });
      return;
    }

    var opt = CHILD_OPTIONS.filter(function (o) { return o.key === c.choice; })[0];
    var optIsEmblem = opt.icon.indexOf("mama_") === 0;
    root.innerHTML =
      '<div class="screen">' +
      '<button class="btn-back" id="childBack" type="button">← Назад</button>' +
      '<div class="ai-q-scene" id="childTopicScreen">' +
      '<img class="ai-q-icon" src="' + (optIsEmblem ? ICONS_EMBLEM : ICONS_HOME) + opt.icon + '" alt="" loading="lazy">' +
      '<p class="section-heading" style="margin:0 0 2px;text-align:center">' + esc(opt.title) + "</p>" +
      '<div id="childTopicBody"></div>' +
      "</div></div>";

    root.querySelector("#childBack").addEventListener("click", function () {
      state.child = { choice: null, loading: false, error: "", answer: "", moreLoading: false, moreError: "" };
      renderChildHub(root);
    });

    renderChildTopicBody(root, root.querySelector("#childTopicBody"));
  }

  function renderChildTopicBody(root, body) {
    if (!body) return;
    var c = state.child;
    var opt = CHILD_OPTIONS.filter(function (o) { return o.key === c.choice; })[0];

    if (c.loading) {
      body.innerHTML = '<div class="state-message"><p class="state-message__title">' + esc(opt.title) + "</p><p>Думаю над ответом…</p></div>";
      return;
    }

    if (c.error) {
      body.innerHTML =
        '<p class="ai-q-hint">' + esc(opt.title) + "</p>" +
        '<div class="pr-error">' + esc(c.error) + "</div>" +
        '<button class="btn-primary" id="childRetry" type="button">Попробовать ещё раз</button>';
      body.querySelector("#childRetry").addEventListener("click", function () {
        state.child.loading = true;
        state.child.error = "";
        renderChildTopicBody(root, body);
        requestChildAnswer(root, c.choice, opt.endpoint);
      });
      return;
    }

    body.innerHTML =
      '<div class="ai-q-answer">' + esc(c.answer).replace(/\n/g, "<br>") + "</div>" +
      (c.moreError ? '<div class="pr-error">' + esc(c.moreError) + "</div>" : "") +
      '<div class="child-actions">' +
      '<button class="btn-primary" id="childAgain" type="button">Обновить рекомендации</button>' +
      (opt.moreEndpoint ? '<button class="btn-primary" id="childMore" type="button"' + (c.moreLoading ? " disabled" : "") + ">" + (c.moreLoading ? "Загружаю…" : "Ещё") + "</button>" : "") +
      "</div>";

    body.querySelector("#childAgain").addEventListener("click", function () {
      state.child.loading = true;
      state.child.error = "";
      state.child.answer = "";
      renderChildTopicBody(root, body);
      requestChildAnswer(root, c.choice, opt.endpoint);
    });

    var moreBtn = body.querySelector("#childMore");
    if (moreBtn) {
      moreBtn.addEventListener("click", function () {
        state.child.moreLoading = true;
        state.child.moreError = "";
        renderChildTopicBody(root, body);
        requestChildAnswer(root, c.choice, opt.moreEndpoint, true);
      });
    }
  }

  function requestChildAnswer(root, key, endpoint, isMore) {
    apiGet(endpoint).then(function (data) {
      if (state.screen !== "child-hub" || state.child.choice !== key) return;
      state.child.loading = false;
      state.child.moreLoading = false;
      state.child.error = "";
      state.child.moreError = "";
      state.child.answer = (data && data.answer) || "";
      renderChildTopicBody(root, root.querySelector("#childTopicBody"));
    }).catch(function (err) {
      if (state.screen !== "child-hub" || state.child.choice !== key) return;
      var msg;
      if (err && err.code === 401) {
        msg = "Открой мини-приложение из бота «Мамин помощник», чтобы получить ответ.";
      } else if (err && err.code === 400 && err.message === "profile_required") {
        msg = "Сначала укажи дату рождения ребёнка в профиле, чтобы получить персональные рекомендации.";
      } else {
        msg = "Не получилось получить ответ. Попробуй ещё раз чуть позже.";
      }
      if (isMore) {
        state.child.moreLoading = false;
        state.child.moreError = msg;
      } else {
        state.child.loading = false;
        state.child.error = msg;
      }
      renderChildTopicBody(root, root.querySelector("#childTopicBody"));
    });
  }

  // ===== Первые дни с малышом (хаб в каталоге «Ребёнок») — 5 реальных AI-сценариев
  // (pediatrician/doctors/documents/massage/swimming) через единый GET /content/firstdays?topic=,
  // тот же choice-паттерн, что и renderChildHub. "sadik" не открывает деталь здесь — ведёт на уже
  // рабочий экран "kindergarten" (не дублирует fd_sadik). Back из корня — в каталог "child-hub".
  function renderFirstdaysHub(root) {
    var f = state.firstdays;

    if (!f.choice) {
      root.innerHTML =
        '<div class="screen">' +
        backButtonHtml("child-hub") +
        '<div class="assistant-scene" id="firstdaysHubScreen">' +
        '<p class="section-heading">Первые дни с малышом</p>' +
        '<div class="shortcut-grid">' + FIRSTDAYS_OPTIONS.map(cardHtml).join("") + "</div>" +
        "</div></div>";
      bindBack(root);
      root.querySelectorAll("[data-action-card]").forEach(function (el) {
        var item = FIRSTDAYS_OPTIONS.filter(function (o) { return o.key === el.getAttribute("data-action-card"); })[0];
        el.addEventListener("click", function () {
          if (item.screen === "kindergarten") {
            navigate("kindergarten", { kindergartenFrom: "firstdays-hub" });
            return;
          }
          state.firstdays = { choice: item.key, loading: true, error: "", answer: "" };
          renderFirstdaysHub(root);
          requestFirstdaysAnswer(root, item.key, item.endpoint);
        });
      });
      return;
    }

    var opt = FIRSTDAYS_OPTIONS.filter(function (o) { return o.key === f.choice; })[0];
    var optIsEmblem = opt.icon.indexOf("mama_") === 0;
    root.innerHTML =
      '<div class="screen">' +
      '<button class="btn-back" id="firstdaysBack" type="button">← Назад</button>' +
      '<div class="ai-q-scene" id="firstdaysTopicScreen">' +
      '<img class="ai-q-icon" src="' + (optIsEmblem ? ICONS_EMBLEM : ICONS_HOME) + opt.icon + '" alt="" loading="lazy">' +
      '<p class="section-heading" style="margin:0 0 2px;text-align:center">' + esc(opt.title) + "</p>" +
      '<div id="firstdaysTopicBody"></div>' +
      "</div></div>";

    root.querySelector("#firstdaysBack").addEventListener("click", function () {
      state.firstdays = { choice: null, loading: false, error: "", answer: "" };
      renderFirstdaysHub(root);
    });

    renderFirstdaysTopicBody(root, root.querySelector("#firstdaysTopicBody"));
  }

  function renderFirstdaysTopicBody(root, body) {
    if (!body) return;
    var f = state.firstdays;
    var opt = FIRSTDAYS_OPTIONS.filter(function (o) { return o.key === f.choice; })[0];

    if (f.loading) {
      body.innerHTML = '<div class="state-message"><p class="state-message__title">' + esc(opt.title) + "</p><p>Думаю над ответом…</p></div>";
      return;
    }

    if (f.error) {
      body.innerHTML =
        '<p class="ai-q-hint">' + esc(opt.title) + "</p>" +
        '<div class="pr-error">' + esc(f.error) + "</div>" +
        '<button class="btn-primary" id="firstdaysRetry" type="button">Попробовать ещё раз</button>';
      body.querySelector("#firstdaysRetry").addEventListener("click", function () {
        state.firstdays.loading = true;
        state.firstdays.error = "";
        renderFirstdaysTopicBody(root, body);
        requestFirstdaysAnswer(root, f.choice, opt.endpoint);
      });
      return;
    }

    body.innerHTML =
      '<div class="ai-q-answer">' + esc(f.answer).replace(/\n/g, "<br>") + "</div>" +
      '<div class="child-actions">' +
      '<button class="btn-primary" id="firstdaysAgain" type="button">Обновить</button>' +
      "</div>";

    body.querySelector("#firstdaysAgain").addEventListener("click", function () {
      state.firstdays.loading = true;
      state.firstdays.error = "";
      state.firstdays.answer = "";
      renderFirstdaysTopicBody(root, body);
      requestFirstdaysAnswer(root, f.choice, opt.endpoint);
    });
  }

  function requestFirstdaysAnswer(root, key, endpoint) {
    apiGet(endpoint).then(function (data) {
      if (state.screen !== "firstdays-hub" || state.firstdays.choice !== key) return;
      state.firstdays.loading = false;
      state.firstdays.error = "";
      state.firstdays.answer = (data && data.answer) || "";
      renderFirstdaysTopicBody(root, root.querySelector("#firstdaysTopicBody"));
    }).catch(function (err) {
      if (state.screen !== "firstdays-hub" || state.firstdays.choice !== key) return;
      var msg;
      if (err && err.code === 401) {
        msg = "Открой мини-приложение из бота «Мамин помощник», чтобы получить ответ.";
      } else if (err && err.code === 400 && err.message === "profile_required") {
        msg = "Сначала укажи дату рождения ребёнка в профиле, чтобы получить персональные рекомендации.";
      } else {
        msg = "Не получилось получить ответ. Попробуй ещё раз чуть позже.";
      }
      state.firstdays.loading = false;
      state.firstdays.error = msg;
      renderFirstdaysTopicBody(root, root.querySelector("#firstdaysTopicBody"));
    });
  }

  // ===== Беременность (реальные сценарии preg_week/preg_baby/preg_checklist/preg_shop из
  // mama_bot.py). "week" — расчёт срока (не AI), остальные три — тот же OpenAI pipeline, что
  // и в Telegram. Доступно только профилю mode="pregnant" (проверяется на бэкенде через
  // GET /pregnancy/week — 400 pregnancy_profile_required для остальных, не 500). Вход только
  // с Home для беременного профиля, back из корня раздела ведёт на Home =====
  function renderPregnancy(root) {
    var p = state.pregnancy;
    root.innerHTML =
      '<div class="screen">' +
      '<button class="btn-back" id="pregBack" type="button">← Назад</button>' +
      '<div class="ai-q-scene" id="pregnancyScreen">' +
      '<img class="ai-q-icon" src="' + ICONS_EMBLEM + 'mama_pregnancy_light.webp" alt="" loading="lazy">' +
      '<p class="section-heading" style="margin:0 0 2px;text-align:center">Беременность</p>' +
      (!p.choice && p.weeksText ? '<p class="ai-q-hint">' + esc(p.weeksText) + "</p>" : "") +
      '<div id="pregnancyBody"></div>' +
      "</div></div>";

    root.querySelector("#pregBack").addEventListener("click", function () {
      if (state.pregnancy.choice) {
        state.pregnancy.choice = null;
        state.pregnancy.choiceLoading = false;
        state.pregnancy.choiceError = "";
        state.pregnancy.answer = "";
        renderPregnancy(root);
      } else {
        navigate("home");
      }
    });

    if (!p.choice && p.loading) loadPregnancyAccess(root);
    renderPregnancyBody(root, root.querySelector("#pregnancyBody"));
  }

  function loadPregnancyAccess(root) {
    apiGet("/pregnancy/week").then(function (data) {
      if (state.screen !== "pregnancy") return;
      state.pregnancy.loading = false;
      state.pregnancy.notApplicable = false;
      state.pregnancy.loadError = "";
      state.pregnancy.weeks = data.weeks;
      state.pregnancy.days = data.days;
      state.pregnancy.weeksText = (data.weeks != null && data.days != null)
        ? data.weeks + " нед. " + data.days + " дн." + (data.trimester ? " · " + data.trimester : "")
        : "";
      renderPregnancy(root);
    }).catch(function (err) {
      if (state.screen !== "pregnancy") return;
      state.pregnancy.loading = false;
      if (err && err.code === 400 && err.message === "pregnancy_profile_required") {
        state.pregnancy.notApplicable = true;
      } else if (err && err.code === 401) {
        state.pregnancy.loadError = "Открой мини-приложение из бота «Мамин помощник», чтобы получить доступ.";
      } else {
        state.pregnancy.loadError = "Не получилось загрузить раздел. Попробуй ещё раз чуть позже.";
      }
      renderPregnancy(root);
    });
  }

  function renderPregnancyBody(root, body) {
    if (!body) return;
    var p = state.pregnancy;

    if (p.loading) {
      body.innerHTML = '<div class="state-message"><p class="state-message__title">Беременность</p><p>Загружаю…</p></div>';
      return;
    }

    if (p.notApplicable) {
      body.innerHTML = '<div class="state-message"><p class="state-message__title">Раздел доступен для профиля беременности</p></div>';
      return;
    }

    if (p.loadError) {
      body.innerHTML =
        '<div class="pr-error">' + esc(p.loadError) + "</div>" +
        '<button class="btn-primary" id="pregRetryLoad" type="button">Попробовать ещё раз</button>';
      body.querySelector("#pregRetryLoad").addEventListener("click", function () {
        state.pregnancy.loading = true;
        renderPregnancyBody(root, body);
        loadPregnancyAccess(root);
      });
      return;
    }

    if (!p.choice) {
      body.innerHTML =
        '<div class="row-list">' +
        PREGNANCY_OPTIONS.map(function (opt) {
          var optIsEmblem = opt.icon.indexOf("mama_") === 0;
          return (
            '<button class="row-card" data-preg-option="' + esc(opt.key) + '" type="button">' +
            '<img class="row-card__icon" src="' + (optIsEmblem ? ICONS_EMBLEM : ICONS) + opt.icon + '" alt="" loading="lazy">' +
            "<span><p class=\"row-card__title\">" + esc(opt.title) + "</p>" +
            '<p class="row-card__sub">' + esc(opt.sub) + "</p></span></button>"
          );
        }).join("") +
        "</div>";
      body.querySelectorAll("[data-preg-option]").forEach(function (el) {
        el.addEventListener("click", function () {
          var key = el.getAttribute("data-preg-option");
          state.pregnancy.choice = key;
          state.pregnancy.choiceLoading = true;
          state.pregnancy.choiceError = "";
          state.pregnancy.answer = "";
          renderPregnancy(root);
          requestPregnancySection(root, key);
        });
      });
      return;
    }

    var opt = PREGNANCY_OPTIONS.filter(function (o) { return o.key === p.choice; })[0];

    if (p.choiceLoading) {
      body.innerHTML = '<div class="state-message"><p class="state-message__title">' + esc(opt.title) + "</p><p>Думаю над ответом…</p></div>";
      return;
    }

    if (p.choiceError) {
      body.innerHTML =
        '<p class="ai-q-hint">' + esc(opt.title) + "</p>" +
        '<div class="pr-error">' + esc(p.choiceError) + "</div>" +
        '<button class="btn-primary" id="pregRetry" type="button">Попробовать ещё раз</button>';
      body.querySelector("#pregRetry").addEventListener("click", function () {
        state.pregnancy.choiceLoading = true;
        state.pregnancy.choiceError = "";
        renderPregnancyBody(root, body);
        requestPregnancySection(root, p.choice);
      });
      return;
    }

    body.innerHTML =
      '<div class="ai-q-answer">' + esc(p.answer).replace(/\n/g, "<br>") + "</div>" +
      '<button class="btn-primary" id="pregAgain" type="button">Обновить</button>';
    body.querySelector("#pregAgain").addEventListener("click", function () {
      state.pregnancy.choiceLoading = true;
      state.pregnancy.choiceError = "";
      state.pregnancy.answer = "";
      renderPregnancyBody(root, body);
      requestPregnancySection(root, p.choice);
    });
  }

  function requestPregnancySection(root, key) {
    var opt = PREGNANCY_OPTIONS.filter(function (o) { return o.key === key; })[0];
    apiGet(opt.endpoint).then(function (data) {
      if (state.screen !== "pregnancy" || state.pregnancy.choice !== key) return;
      state.pregnancy.choiceLoading = false;
      state.pregnancy.answer = (data && (data.text || data.answer)) || "";
      renderPregnancyBody(root, root.querySelector("#pregnancyBody"));
    }).catch(function (err) {
      if (state.screen !== "pregnancy" || state.pregnancy.choice !== key) return;
      state.pregnancy.choiceLoading = false;
      state.pregnancy.choiceError = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы получить ответ."
        : "Не получилось получить ответ. Попробуй ещё раз чуть позже.";
      renderPregnancyBody(root, root.querySelector("#pregnancyBody"));
    });
  }

  // ===== Пособия и выплаты (в хабе «Поддержка мамы») — те же сценарии ben_birth/ben_15/ben_3/
  // ben_matcap/ben_decree/ben_multi (GET /content/benefits?topic=) и ben_personal/ben_personal_answer
  // (POST /benefits/personal), что и в Telegram =====
  function renderBenefits(root) {
    var b = state.benefits;
    root.innerHTML =
      '<div class="screen">' +
      '<button class="btn-back" id="benBack" type="button">← Назад</button>' +
      '<div class="ai-q-scene" id="benefitsScreen">' +
      '<img class="ai-q-icon" src="' + ICONS_EMBLEM + 'mama_benefits_light.webp" alt="" loading="lazy">' +
      '<p class="section-heading" style="margin:0 0 2px;text-align:center">Пособия и выплаты</p>' +
      (!b.choice ? '<p class="ai-q-hint">Узнай, какие выплаты тебе положены 💕</p>' : "") +
      '<div id="benefitsBody"></div>' +
      "</div></div>";

    root.querySelector("#benBack").addEventListener("click", function () {
      if (state.benefits.choice) {
        state.benefits = { choice: null, loading: false, error: "", answer: "", personalText: "", personalAnswer: "", personalLoading: false, personalError: "" };
        renderBenefits(root);
      } else {
        navigate("mom-support");
      }
    });

    renderBenefitsBody(root, root.querySelector("#benefitsBody"));
  }

  function renderBenefitsBody(root, body) {
    if (!body) return;
    var b = state.benefits;

    if (!b.choice) {
      body.innerHTML =
        '<div class="row-list">' +
        BENEFITS_OPTIONS.map(function (opt) {
          var optIsEmblem = opt.icon.indexOf("mama_") === 0;
          return (
            '<button class="row-card" data-ben-option="' + esc(opt.key) + '" type="button">' +
            '<img class="row-card__icon" src="' + (optIsEmblem ? ICONS_EMBLEM : ICONS) + opt.icon + '" alt="" loading="lazy">' +
            "<span><p class=\"row-card__title\">" + esc(opt.title) + "</p>" +
            '<p class="row-card__sub">' + esc(opt.sub) + "</p></span></button>"
          );
        }).join("") +
        "</div>";
      body.querySelectorAll("[data-ben-option]").forEach(function (el) {
        el.addEventListener("click", function () {
          var key = el.getAttribute("data-ben-option");
          state.benefits.choice = key;
          if (key !== "personal") {
            state.benefits.loading = true;
            state.benefits.error = "";
            state.benefits.answer = "";
          }
          renderBenefits(root);
          if (key !== "personal") requestBenefitsAnswer(root, key);
        });
      });
      return;
    }

    if (b.choice === "personal") {
      renderBenefitsPersonalBody(root, body);
      return;
    }

    var opt = BENEFITS_OPTIONS.filter(function (o) { return o.key === b.choice; })[0];

    if (b.loading) {
      body.innerHTML = '<div class="state-message"><p class="state-message__title">' + esc(opt.title) + "</p><p>Подбираю актуальную информацию…</p></div>";
      return;
    }

    if (b.error) {
      body.innerHTML =
        '<p class="ai-q-hint">' + esc(opt.title) + "</p>" +
        '<div class="pr-error">' + esc(b.error) + "</div>" +
        '<button class="btn-primary" id="benRetry" type="button">Попробовать ещё раз</button>';
      body.querySelector("#benRetry").addEventListener("click", function () {
        state.benefits.loading = true;
        state.benefits.error = "";
        renderBenefitsBody(root, body);
        requestBenefitsAnswer(root, b.choice);
      });
      return;
    }

    body.innerHTML =
      '<div class="ai-q-answer">' + esc(b.answer).replace(/\n/g, "<br>") + "</div>" +
      '<button class="btn-primary" id="benAgain" type="button">Обновить информацию</button>';
    body.querySelector("#benAgain").addEventListener("click", function () {
      state.benefits.loading = true;
      state.benefits.error = "";
      state.benefits.answer = "";
      renderBenefitsBody(root, body);
      requestBenefitsAnswer(root, b.choice);
    });
  }

  function requestBenefitsAnswer(root, key) {
    var opt = BENEFITS_OPTIONS.filter(function (o) { return o.key === key; })[0];
    apiGet(opt.endpoint).then(function (data) {
      if (state.screen !== "benefits" || state.benefits.choice !== key) return;
      state.benefits.loading = false;
      state.benefits.answer = (data && data.answer) || "";
      renderBenefitsBody(root, root.querySelector("#benefitsBody"));
    }).catch(function (err) {
      if (state.screen !== "benefits" || state.benefits.choice !== key) return;
      state.benefits.loading = false;
      state.benefits.error = (err && err.code === 401)
        ? "Открой мини-приложение из бота «Мамин помощник», чтобы получить ответ."
        : "Не получилось получить ответ. Попробуй ещё раз чуть позже.";
      renderBenefitsBody(root, root.querySelector("#benefitsBody"));
    });
  }

  function renderBenefitsPersonalBody(root, body) {
    if (!body) return;
    var b = state.benefits;

    if (b.personalAnswer) {
      body.innerHTML =
        '<div class="ai-q-answer">' + esc(b.personalAnswer).replace(/\n/g, "<br>") + "</div>" +
        '<button class="btn-primary" id="benPersonalAgain" type="button">Задать другую ситуацию</button>';
      body.querySelector("#benPersonalAgain").addEventListener("click", function () {
        state.benefits.personalText = "";
        state.benefits.personalAnswer = "";
        state.benefits.personalLoading = false;
        state.benefits.personalError = "";
        renderBenefitsBody(root, body);
      });
      return;
    }

    body.innerHTML =
      '<label class="pr-field">' +
      '<span class="pr-field__label">Опишите вашу ситуацию</span>' +
      '<textarea id="benPersonalInput" class="pr-textarea" rows="5" maxlength="2000" placeholder="Работаю официально, второй ребёнок, замужем, Москва"' + (b.personalLoading ? " disabled" : "") + ">" + esc(b.personalText) + "</textarea>" +
      "</label>" +
      (b.personalError ? '<div class="pr-error">' + esc(b.personalError) + "</div>" : "") +
      '<button class="btn-primary" id="benPersonalSubmit" type="button"' + (b.personalLoading ? " disabled" : "") + ">" + (b.personalLoading ? "Подбираю…" : "Подобрать выплаты") + "</button>";

    var textarea = body.querySelector("#benPersonalInput");
    var submitBtn = body.querySelector("#benPersonalSubmit");
    textarea.addEventListener("input", function () { state.benefits.personalText = textarea.value; });

    submitBtn.addEventListener("click", function () {
      var situation = (textarea.value || "").trim();
      if (!situation) {
        state.benefits.personalError = "Опиши ситуацию перед отправкой.";
        renderBenefitsPersonalBody(root, body);
        return;
      }
      state.benefits.personalText = situation;
      state.benefits.personalLoading = true;
      state.benefits.personalError = "";
      renderBenefitsPersonalBody(root, body);

      apiPost("/benefits/personal", { situation: situation }).then(function (data) {
        if (state.screen !== "benefits" || state.benefits.choice !== "personal") return;
        state.benefits.personalLoading = false;
        state.benefits.personalAnswer = (data && data.answer) || "";
        renderBenefitsBody(root, root.querySelector("#benefitsBody"));
      }).catch(function (err) {
        if (state.screen !== "benefits" || state.benefits.choice !== "personal") return;
        state.benefits.personalLoading = false;
        if (err && err.code === 401) {
          state.benefits.personalError = "Открой мини-приложение из бота «Мамин помощник», чтобы получить ответ.";
        } else if (err && err.code === 400) {
          state.benefits.personalError = "Опиши ситуацию перед отправкой.";
        } else {
          state.benefits.personalError = "Не получилось получить ответ. Попробуй ещё раз чуть позже.";
        }
        renderBenefitsBody(root, root.querySelector("#benefitsBody"));
      });
    });
  }

  // ===== Разделы «Поддержка мамы», ещё не перенесённые на backend мини-приложения =====
  // Работают в Telegram-боте «Мамин помощник» (mama_bot.py) — экран называет точную функцию,
  // это не generic заглушка.
  function renderMomSupportPending(root) {
    var item = MOM_SUPPORT_SECTIONS.filter(function (s) { return s.fn === state.momPendingKey; })[0];
    var title = item ? item.title : "Раздел";
    var icon = item ? item.icon : "icon-mom-support-3d.webp";
    var sub = item ? item.sub : "";
    var fn = state.momPendingKey || "";
    root.innerHTML =
      '<div class="screen">' +
      backButtonHtml("mom-support") +
      '<div class="stub-scene" id="momSupportPendingScreen">' +
      '<img class="stub-icon" src="' + ICONS_HOME + icon + '" alt="" loading="lazy">' +
      '<div class="state-message">' +
      '<p class="state-message__title">' + esc(title) + "</p>" +
      (sub ? "<p>" + esc(sub) + "</p>" : "") +
      '<p>Пока доступно в Telegram-боте «Мамин помощник» (функция <code>' + esc(fn) + '</code>). В мини-приложении появится отдельным экраном, когда бэкенд будет перенесён.</p>' +
      "</div></div></div>";
    bindBack(root);
  }

  function renderPersonalReviewForm(root) {
    var form = state.prForm;
    root.innerHTML =
      '<div class="screen">' +
      backButtonHtml("mom-support") +
      '<div class="panel">' +
      '<p class="panel__title">Личный разбор ситуации</p>' +
      '<p class="pr-hint">Опишите, что происходит. Автор проекта лично изучит ситуацию и запишет подробный голосовой ответ.</p>' +
      '<label class="pr-field">' +
      '<span class="pr-field__label">Опишите ситуацию</span>' +
      '<textarea id="prSituation" class="pr-textarea" rows="6" maxlength="4000" placeholder="Расскажите, что происходит…">' + esc(form.situation_text) + "</textarea>" +
      "</label>" +
      '<div class="pr-field">' +
      '<span class="pr-field__label">Как удобнее получить ответ</span>' +
      '<label class="pr-radio"><input type="radio" name="prReply" value="telegram"' + (form.preferred_reply === "email" ? "" : " checked") + '> Telegram (в этот бот)</label>' +
      '<label class="pr-radio"><input type="radio" name="prReply" value="email"' + (form.preferred_reply === "email" ? " checked" : "") + "> Email</label>" +
      "</div>" +
      '<label class="pr-field" id="prEmailField" style="' + (form.preferred_reply === "email" ? "" : "display:none") + '">' +
      '<span class="pr-field__label">Email</span>' +
      '<input type="email" id="prEmail" class="pr-input" value="' + esc(form.email) + '" placeholder="you@example.com">' +
      "</label>" +
      '<label class="pr-check"><input type="checkbox" id="prConsent"' + (form.consent ? " checked" : "") + "> Согласен(на) на обработку данных для подготовки личного разбора</label>" +
      '<label class="pr-check"><input type="checkbox" id="prDisclaimer"' + (form.disclaimer_ack ? " checked" : "") + "> Личный разбор не является медицинской, психотерапевтической или экстренной помощью</label>" +
      '<div class="pr-error" id="prFormError" style="display:none"></div>' +
      '<button class="btn-primary" id="prFormNext" type="button">Далее</button>' +
      "</div></div>";

    bindBack(root);

    var situationEl = root.querySelector("#prSituation");
    var emailField = root.querySelector("#prEmailField");
    var emailEl = root.querySelector("#prEmail");
    var consentEl = root.querySelector("#prConsent");
    var disclaimerEl = root.querySelector("#prDisclaimer");
    var errorEl = root.querySelector("#prFormError");

    root.querySelectorAll('input[name="prReply"]').forEach(function (r) {
      r.addEventListener("change", function () {
        if (r.checked) emailField.style.display = r.value === "email" ? "" : "none";
      });
    });

    root.querySelector("#prFormNext").addEventListener("click", function () {
      var situation = (situationEl.value || "").trim();
      var replyType = root.querySelector('input[name="prReply"]:checked').value;
      var email = (emailEl.value || "").trim();
      var consent = consentEl.checked;
      var disclaimer = disclaimerEl.checked;
      var error = "";
      if (situation.length < 10) error = "Опишите ситуацию подробнее (не менее 10 символов).";
      else if (replyType === "email" && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) error = "Укажите корректный email.";
      else if (!consent) error = "Нужно согласие на обработку данных.";
      else if (!disclaimer) error = "Нужно подтвердить, что это не медицинская и не экстренная помощь.";
      if (error) {
        errorEl.textContent = error;
        errorEl.style.display = "";
        return;
      }
      state.prForm = {
        situation_text: situation,
        preferred_reply: replyType,
        email: replyType === "email" ? email : "",
        consent: true,
        disclaimer_ack: true
      };
      navigate("pr-pay");
    });
  }

  function renderPersonalReviewPay(root) {
    var form = state.prForm;
    if (!form || !form.situation_text) { navigate("mom-support"); return; }
    var risky = hasSafetyRisk(form.situation_text);
    root.innerHTML =
      '<div class="screen">' +
      backButtonHtml("pr-form") +
      '<div class="panel">' +
      '<p class="panel__title">Личный разбор ситуации</p>' +
      (risky
        ? '<div class="pr-safety-banner">Не ждите личного разбора. При непосредственной угрозе жизни или безопасности обратитесь за экстренной помощью в вашем регионе.</div>'
        : "") +
      '<p class="pr-price">Стоимость личного разбора — ' + PERSONAL_REVIEW_PRICE + " ₽</p>" +
      '<p class="pr-note">После оплаты заявка будет передана автору проекта. Ответ будет подготовлен лично.</p>' +
      '<div class="pr-error" id="prPayError" style="display:none"></div>' +
      '<button class="btn-primary" id="prPayBtn" type="button">Оплатить ' + PERSONAL_REVIEW_PRICE + " ₽</button>" +
      "</div></div>";
    bindBack(root);
    var btn = root.querySelector("#prPayBtn");
    var errorEl = root.querySelector("#prPayError");
    btn.addEventListener("click", function () {
      btn.disabled = true;
      btn.textContent = "Создаём платёж…";
      apiPost("/personal-review/submit", {
        situation_text: form.situation_text,
        preferred_reply: form.preferred_reply,
        email: form.email,
        consent: true,
        disclaimer_ack: true
      }).then(function (data) {
        state.prReviewId = data.review_id;
        if (data.confirmation_url) {
          Platform.openLink(data.confirmation_url);
        }
        navigate("pr-status");
      }).catch(function (err) {
        btn.disabled = false;
        btn.textContent = "Оплатить " + PERSONAL_REVIEW_PRICE + " ₽";
        errorEl.textContent = (err && err.code === 401)
          ? "Открой мини-приложение из бота «Мамин помощник», чтобы оплатить."
          : "Не получилось создать платёж. Попробуй ещё раз чуть позже.";
        errorEl.style.display = "";
      });
    });
  }

  function renderPersonalReviewStatus(root) {
    if (!state.prReviewId) { navigate("mom-support"); return; }
    root.innerHTML =
      '<div class="screen">' +
      backButtonHtml("home") +
      '<div class="panel">' +
      '<p class="panel__title" id="prStatusTitle">Заявка принята</p>' +
      '<p id="prStatusDetail">Личный разбор готовит автор проекта.</p>' +
      "</div></div>";
    bindBack(root);
    pollPersonalReviewStatus();
  }

  function pollPersonalReviewStatus() {
    if (state.prStatusTimer) {
      clearTimeout(state.prStatusTimer);
      state.prStatusTimer = null;
    }
    if (state.screen !== "pr-status" || !state.prReviewId) return;
    apiGet("/personal-review/status?id=" + encodeURIComponent(state.prReviewId)).then(function (data) {
      if (state.screen !== "pr-status") return;
      var titleEl = document.getElementById("prStatusTitle");
      var detailEl = document.getElementById("prStatusDetail");
      if (titleEl) titleEl.textContent = data.title || "Заявка принята";
      if (detailEl) detailEl.textContent = data.detail || "";
      if (!data.answered) {
        state.prStatusTimer = setTimeout(pollPersonalReviewStatus, 5000);
      }
    }).catch(function () {
      if (state.screen === "pr-status") {
        state.prStatusTimer = setTimeout(pollPersonalReviewStatus, 8000);
      }
    });
  }

  // ===== Поддержать проект (реальный donate/support-flow: POST /support/create создаёт
  // платёж через существующий YooKassa support-flow и возвращает confirmation_url; оплату
  // подтверждает уже работающий check_payments_loop бота нужной платформы). =====
  function renderDonate(root) {
    var d = state.donate;
    root.innerHTML =
      '<div class="screen">' +
      '<button class="btn-back" id="donateBack" type="button">← Назад</button>' +
      '<div class="ai-q-scene" id="donateScreen">' +
      '<img class="ai-q-icon" src="' + ICONS_EMBLEM + 'mama_support_project_light.webp" alt="" loading="lazy">' +
      '<p class="section-heading" style="margin:0 0 2px;text-align:center">Поддержать проект</p>' +
      (d.phase === "pick"
        ? '<p class="ai-q-hint">«Мамин помощник» остаётся бесплатным для всех родителей. Если проект оказался полезен — поддержи его развитие любой удобной суммой. Это добровольная благодарность, все функции доступны и без оплаты 💕</p>'
        : "") +
      '<div id="donateBody"></div>' +
      "</div></div>";

    root.querySelector("#donateBack").addEventListener("click", function () {
      if (state.donate.phase !== "pick") {
        state.donate.phase = "pick";
        state.donate.payError = "";
        renderDonate(root);
      } else {
        navigate("profile");
      }
    });

    renderDonateBody(root, root.querySelector("#donateBody"));
  }

  function renderDonateBody(root, body) {
    if (!body) return;
    var d = state.donate;

    if (d.phase === "done") {
      body.innerHTML =
        '<p class="state-message__title">Спасибо за поддержку ❤️</p>' +
        '<p class="pr-note">Окно оплаты открылось отдельно. Как только оплата пройдёт, подтверждение придёт в бот «Мамин помощник».</p>' +
        '<button class="btn-primary" id="donateDoneBtn" type="button">В профиль</button>';
      body.querySelector("#donateDoneBtn").addEventListener("click", function () { navigate("profile"); });
      return;
    }

    if (d.phase === "confirm") {
      var amountLabel = d.amount === Math.round(d.amount) ? d.amount.toFixed(0) : d.amount.toFixed(2);
      body.innerHTML =
        '<p class="pr-price">Сумма поддержки — ' + amountLabel + ' ₽</p>' +
        '<p class="pr-note">Оплата добровольная и не открывает дополнительных функций — они уже доступны всем.</p>' +
        (d.payError ? '<div class="pr-error">' + esc(d.payError) + "</div>" : "") +
        '<button class="btn-primary" id="donatePayBtn" type="button"' + (d.payLoading ? " disabled" : "") + ">" + (d.payLoading ? "Создаём платёж…" : "Перейти к оплате") + "</button>";

      body.querySelector("#donatePayBtn").addEventListener("click", function () {
        if (state.donate.payLoading) return;
        state.donate.payLoading = true;
        state.donate.payError = "";
        renderDonateBody(root, body);
        apiPost("/support/create", { amount: state.donate.amount, variant: state.donate.variant }).then(function (data) {
          state.donate.payLoading = false;
          if (data && data.confirmation_url) {
            Platform.openLink(data.confirmation_url);
            state.donate.phase = "done";
          } else {
            state.donate.payError = "Не получилось создать платёж. Попробуй ещё раз чуть позже.";
          }
          renderDonateBody(root, body);
        }).catch(function (err) {
          state.donate.payLoading = false;
          state.donate.payError = (err && err.code === 401)
            ? "Открой мини-приложение из бота «Мамин помощник», чтобы поддержать проект."
            : "Не получилось создать платёж. Попробуй ещё раз чуть позже.";
          renderDonateBody(root, body);
        });
      });
      return;
    }

    // phase === "pick"
    body.innerHTML =
      '<div class="row-list">' +
      DONATE_AMOUNTS.map(function (opt) {
        return '<button class="row-card" data-donate-amount="' + esc(opt.variant) + '" type="button">' +
          '<span><p class="row-card__title">' + esc(opt.label) + "</p></span></button>";
      }).join("") +
      '<button class="row-card" id="donateCustomBtn" type="button">' +
      '<span><p class="row-card__title">Своя сумма</p></span></button>' +
      "</div>" +
      '<label class="pr-field" id="donateCustomField" style="display:none">' +
      '<span class="pr-field__label">Сумма в рублях (от ' + DONATE_MIN_AMOUNT + ' до ' + DONATE_MAX_AMOUNT + ')</span>' +
      '<input type="number" inputmode="decimal" id="donateCustomInput" class="pr-input" min="' + DONATE_MIN_AMOUNT + '" max="' + DONATE_MAX_AMOUNT + '" placeholder="Например, 250" value="' + esc(d.customInput) + '">' +
      "</label>" +
      '<div class="pr-error" id="donateCustomError" style="' + (d.customError ? "" : "display:none") + '">' + esc(d.customError || "") + "</div>" +
      '<button class="btn-primary" id="donateCustomNext" type="button" style="display:none">Подтвердить сумму</button>';

    body.querySelectorAll("[data-donate-amount]").forEach(function (el) {
      el.addEventListener("click", function () {
        var variant = el.getAttribute("data-donate-amount");
        var opt = DONATE_AMOUNTS.filter(function (o) { return o.variant === variant; })[0];
        if (!opt) return;
        state.donate.amount = opt.amount;
        state.donate.variant = opt.variant;
        state.donate.phase = "confirm";
        state.donate.payError = "";
        renderDonateBody(root, body);
      });
    });

    var customField = body.querySelector("#donateCustomField");
    var customInput = body.querySelector("#donateCustomInput");
    var customNext = body.querySelector("#donateCustomNext");
    var customErrorEl = body.querySelector("#donateCustomError");

    body.querySelector("#donateCustomBtn").addEventListener("click", function () {
      customField.style.display = "";
      customNext.style.display = "";
      customInput.focus();
    });

    customInput.addEventListener("input", function () { state.donate.customInput = customInput.value; });

    customNext.addEventListener("click", function () {
      var raw = (customInput.value || "").replace(",", ".").trim();
      var amount = parseFloat(raw);
      if (!raw || isNaN(amount) || amount < DONATE_MIN_AMOUNT || amount > DONATE_MAX_AMOUNT) {
        state.donate.customError = "Введи сумму от " + DONATE_MIN_AMOUNT + " до " + DONATE_MAX_AMOUNT + " рублей.";
        customErrorEl.textContent = state.donate.customError;
        customErrorEl.style.display = "";
        return;
      }
      state.donate.customError = "";
      state.donate.amount = Math.round(amount * 100) / 100;
      state.donate.variant = "custom";
      state.donate.phase = "confirm";
      state.donate.payError = "";
      renderDonateBody(root, body);
    });
  }

  function render() {
    var root = document.getElementById("screenRoot");
    if (!root) return;
    if (state.screen === "home") renderHome(root);
    else if (state.screen === "today") renderToday(root);
    else if (state.screen === "trackers") renderTrackerShell(root);
    else if (state.screen === "assistant") renderAssistantShell(root);
    else if (state.screen === "history") renderHistory(root);
    else if (state.screen === "profile") renderProfile(root);
    else if (state.screen === "invite") renderInvite(root);
    else if (state.screen === "reset-me") renderResetMe(root);
    else if (state.screen === "reset-me-done") renderResetMeDone(root);
    else if (state.screen === "feedback") renderFeedback(root);
    else if (state.screen === "mom-support") renderMomSupport(root);
    else if (state.screen === "mom-emotions") renderMomEmotions(root);
    else if (state.screen === "breastfeeding") renderBreastfeeding(root);
    else if (state.screen === "recovery") renderRecovery(root);
    else if (state.screen === "pregnancy") renderPregnancy(root);
    else if (state.screen === "benefits") renderBenefits(root);
    else if (state.screen === "mom-support-pending") renderMomSupportPending(root);
    else if (state.screen === "psycho-chat") renderPsychoChat(root);
    else if (state.screen === "ai-question") renderAiQuestion(root);
    else if (state.screen === "school") renderSchool(root);
    else if (state.screen === "tantrum-emotions") renderTantrumEmotions(root);
    else if (state.screen === "kindergarten") renderKindergarten(root);
    else if (state.screen === "child-hub") renderChildHub(root);
    else if (state.screen === "firstdays-hub") renderFirstdaysHub(root);
    else if (state.screen === "emergency") renderEmergency(root);
    else if (state.screen === "photo-analysis") renderPhotoAnalysis(root);
    else if (state.screen === "sleep-tracker") renderSleepTracker(root);
    else if (state.screen === "feeding-tracker") renderFeedingTracker(root);
    else if (state.screen === "symptoms-tracker") renderSymptomsTracker(root);
    else if (state.screen === "growth-tracker") renderGrowthTracker(root);
    else if (state.screen === "diary-tracker") renderDiaryTracker(root);
    else if (state.screen === "vaccines-tracker") renderVaccinesTracker(root);
    else if (state.screen === "complementary-feeding") renderComplementaryFeeding(root);
    else if (state.screen === "pr-form") renderPersonalReviewForm(root);
    else if (state.screen === "pr-pay") renderPersonalReviewPay(root);
    else if (state.screen === "pr-status") renderPersonalReviewStatus(root);
    else if (state.screen === "donate") renderDonate(root);
    else if (state.screen === "stub") renderStub(root);
    else renderHome(root);
    updateBottomNav();
    // Нативная кнопка "Назад" платформы: скрыта на корневых экранах (Home и остальные вкладки
    // нижней навигации), показана на внутренних экранах — как и внутриэкранная "← Назад".
    if (ROOT_SCREENS.indexOf(state.screen) === -1) Platform.showBackButton();
    else Platform.hideBackButton();
    window.scrollTo(0, 0);
  }

  var ROOT_SCREENS = ["home", "assistant", "trackers", "history", "profile"];
  Platform.onBackButton(appBack);

  document.querySelectorAll(".bottomnav__item").forEach(function (btn) {
    btn.addEventListener("click", function () {
      navigate(btn.getAttribute("data-route"));
    });
  });

  var initialScreen = new URLSearchParams(window.location.search).get("screen");
  if (initialScreen) state.screen = initialScreen;
  render();
})();
