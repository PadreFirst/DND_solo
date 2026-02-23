/* Telegram Mini App — Character Dashboard */
(function () {
  "use strict";

  const tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
  }

  const $ = (id) => document.getElementById(id);

  const STAT_NAMES = {
    str: { en: "STR", ru: "СИЛ" },
    dex: { en: "DEX", ru: "ЛОВ" },
    con: { en: "CON", ru: "ТЕЛ" },
    int: { en: "INT", ru: "ИНТ" },
    wis: { en: "WIS", ru: "МДР" },
    cha: { en: "CHA", ru: "ХАР" },
  };

  const TYPE_ICONS = {
    weapon: "⚔️",
    armor: "🛡",
    consumable: "🧪",
    ammo: "🏹",
    misc: "📦",
  };

  const RECHARGE_RU = {
    "at will": "без ограничений",
    "short rest": "короткий отдых",
    "long rest": "длинный отдых",
    "per turn": "раз в ход",
    "spell slots": "ячейки заклинаний",
    "per short rest": "короткий отдых",
    "per long rest": "длинный отдых",
  };

  const L = {
    en: {
      abilities: "Ability Scores",
      abilitiesSec: "Abilities",
      inventory: "Inventory",
      quest: "📜 Quest",
      location: "📍 Location",
      ac: "AC",
      speed: "Speed",
      prof: "Prof",
      gold: "Gold",
      all: "All",
      equipped: "Equipped",
      weapons: "Weapons",
      armor: "Armor",
      potions: "Potions",
      misc: "Other",
      empty: "Nothing here",
      noQuest: "No active quest",
      noLoc: "Unknown",
      inCombat: "In Combat",
      exploring: "Exploring",
      active: "Active",
      passive: "Passive",
      loading: "Loading character...",
      noChar: "Create a character first using /start",
      error: "Something went wrong",
    },
    ru: {
      abilities: "Характеристики",
      abilitiesSec: "Способности",
      inventory: "Инвентарь",
      quest: "📜 Задание",
      location: "📍 Локация",
      ac: "КЗ",
      speed: "Скор.",
      prof: "Маст.",
      gold: "Золото",
      all: "Все",
      equipped: "Надето",
      weapons: "Оружие",
      armor: "Броня",
      potions: "Зелья",
      misc: "Прочее",
      empty: "Пусто",
      noQuest: "Нет активного задания",
      noLoc: "Неизвестно",
      inCombat: "В бою",
      exploring: "Исследование",
      active: "Активная",
      passive: "Пассивная",
      loading: "Загрузка персонажа...",
      noChar: "Сначала создайте персонажа через /start",
      error: "Что-то пошло не так",
    },
  };

  let lang = "en";
  let t = L.en;

  function fmtMod(v) {
    return v >= 0 ? "+" + v : String(v);
  }

  function escHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function getMechanicsText(item) {
    let m = item.mechanics;
    if (!m) return "";
    if (typeof m === "string") {
      try { m = JSON.parse(m); } catch { return m; }
    }
    const parts = [];
    if (m.damage) parts.push(m.damage);
    if (m.type) parts.push(m.type);
    if (m.ac) parts.push("AC " + m.ac);
    return parts.join(" · ");
  }

  /* ---- Fetch & Render ---- */

  async function load() {
    const initData = tg ? tg.initData : "";
    if (!initData) {
      showError(t.error + " (no initData)");
      return;
    }

    try {
      const resp = await fetch("/api/character", {
        headers: { "X-Telegram-Init-Data": initData },
      });

      if (resp.status === 401) {
        showError(t.error + " (auth)");
        return;
      }
      if (resp.status === 404) {
        showError(t.noChar);
        return;
      }
      if (!resp.ok) {
        showError(t.error);
        return;
      }

      const data = await resp.json();
      lang = data.lang || "en";
      t = L[lang] || L.en;

      render(data);
    } catch (e) {
      console.error(e);
      showError(t.error);
    }
  }

  function showError(msg) {
    $("loading").classList.add("hidden");
    $("error-text").textContent = msg;
    $("error").classList.remove("hidden");
  }

  function render(d) {
    $("loading").classList.add("hidden");
    $("dashboard").classList.remove("hidden");

    renderHeader(d);
    renderCombat(d);
    renderBars(d);
    renderQuickStats(d);
    renderStats(d);
    renderAbilities(d);
    renderInventory(d);
    renderQuest(d);
    renderLocation(d);
  }

  function renderHeader(d) {
    $("char-name").textContent = d.name;
    $("char-subtitle").textContent = d.race + " · " + d.class;
    $("level-badge").textContent = "Lv. " + d.level;
  }

  function renderCombat(d) {
    const el = $("combat-in");
    if (d.in_combat) {
      el.classList.add("in-combat");
      $("combat-label").textContent = t.inCombat;
      el.querySelector(".combat-icon").textContent = "⚔️";
    } else {
      el.classList.add("exploring");
      $("combat-label").textContent = t.exploring;
      el.querySelector(".combat-icon").textContent = "🌿";
    }
  }

  function renderBars(d) {
    const hpPct = d.max_hp > 0 ? Math.round((d.hp / d.max_hp) * 100) : 0;
    $("hp-value").textContent = d.hp + " / " + d.max_hp;
    const hpFill = $("hp-fill");
    hpFill.style.width = hpPct + "%";
    hpFill.classList.remove("low", "mid", "high");
    if (hpPct <= 25) hpFill.classList.add("low");
    else if (hpPct <= 60) hpFill.classList.add("mid");
    else hpFill.classList.add("high");

    const xpInLevel = d.xp - d.xp_current_level;
    const xpNeeded = d.xp_next > d.xp_current_level ? d.xp_next - d.xp_current_level : 1;
    const xpPct = d.xp_next > 0 ? Math.min(100, Math.round((xpInLevel / xpNeeded) * 100)) : 100;
    $("xp-value").textContent = d.xp + " / " + (d.xp_next || "MAX");
    $("xp-fill").style.width = xpPct + "%";
  }

  function renderQuickStats(d) {
    $("ac-val").textContent = d.ac;
    $("ac-lbl").textContent = t.ac;
    $("speed-val").textContent = d.speed;
    $("speed-lbl").textContent = t.speed;
    $("prof-val").textContent = "+" + d.proficiency_bonus;
    $("prof-lbl").textContent = t.prof;
    $("gold-val").textContent = d.gold;
    $("gold-lbl").textContent = d.currency || t.gold;
  }

  function renderStats(d) {
    $("stats-title").textContent = t.abilities;
    const grid = $("stats-grid");
    grid.innerHTML = "";
    const order = ["str", "dex", "con", "int", "wis", "cha"];
    for (const key of order) {
      const names = STAT_NAMES[key];
      const card = document.createElement("div");
      card.className = "stat-card";
      card.innerHTML =
        '<div class="stat-abbr">' + (names[lang] || names.en) + "</div>" +
        '<div class="stat-score">' + d.stats[key] + "</div>" +
        '<div class="stat-mod">' + fmtMod(d.modifiers[key]) + "</div>";
      grid.appendChild(card);
    }
  }

  function renderAbilities(d) {
    const sec = $("abilities-section");
    $("abilities-title").textContent = t.abilitiesSec;
    const list = $("abilities-list");
    list.innerHTML = "";

    if (!d.abilities || d.abilities.length === 0) {
      sec.classList.add("hidden");
      return;
    }
    sec.classList.remove("hidden");

    for (const ab of d.abilities) {
      const card = document.createElement("div");
      card.className = "ability-card";

      const typeLbl = ab.type === "passive" ? t.passive : t.active;
      const typeCls = ab.type === "passive" ? "badge-passive" : "badge-active";

      let rechargeLbl = ab.recharge || "";
      if (lang === "ru" && RECHARGE_RU[rechargeLbl.toLowerCase()]) {
        rechargeLbl = RECHARGE_RU[rechargeLbl.toLowerCase()];
      }

      let badgesHtml =
        '<span class="ability-badge ' + typeCls + '">' + escHtml(typeLbl) + "</span>";
      if (rechargeLbl) {
        badgesHtml +=
          '<span class="ability-badge badge-recharge">' + escHtml(rechargeLbl) + "</span>";
      }

      card.innerHTML =
        '<div class="ability-header">' +
        '<span class="ability-name">' + escHtml(ab.name) + "</span>" +
        '<div class="ability-badges">' + badgesHtml + "</div>" +
        "</div>" +
        '<div class="ability-desc">' + escHtml(ab.desc || "") + "</div>";

      list.appendChild(card);
    }
  }

  function renderInventory(d) {
    $("inv-title").textContent = t.inventory;
    const items = d.inventory || [];
    const tabsDef = [
      { key: "all", label: t.all },
      { key: "equipped", label: t.equipped },
      { key: "weapon", label: t.weapons },
      { key: "armor", label: t.armor },
      { key: "consumable", label: t.potions },
      { key: "misc", label: t.misc },
    ];

    const tabsEl = $("inv-tabs");
    tabsEl.innerHTML = "";

    let activeTab = "all";

    function filterItems(tab) {
      if (tab === "all") return items;
      if (tab === "equipped") return items.filter((i) => i.equipped);
      return items.filter((i) => (i.type || "misc") === tab);
    }

    function renderItems(tab) {
      activeTab = tab;
      const list = $("inv-list");
      list.innerHTML = "";
      const filtered = filterItems(tab);

      if (filtered.length === 0) {
        list.innerHTML = '<div class="inv-empty">' + t.empty + "</div>";
        return;
      }

      for (const item of filtered) {
        const el = document.createElement("div");
        el.className = "inv-item";
        const icon = TYPE_ICONS[item.type] || "📦";
        const mech = getMechanicsText(item);
        const dotHtml = item.equipped ? '<span class="equipped-dot"></span>' : "";

        el.innerHTML =
          '<div class="inv-icon">' + icon + "</div>" +
          '<div class="inv-info">' +
          '<div class="inv-name">' + dotHtml + escHtml(item.name) + "</div>" +
          (mech ? '<div class="inv-detail">' + escHtml(mech) + "</div>" : "") +
          "</div>" +
          (item.quantity > 1
            ? '<div class="inv-qty">x' + item.quantity + "</div>"
            : "");

        list.appendChild(el);
      }
    }

    for (const td of tabsDef) {
      const btn = document.createElement("div");
      btn.className = "inv-tab" + (td.key === "all" ? " active" : "");
      btn.textContent = td.label;
      btn.addEventListener("click", function () {
        tabsEl.querySelectorAll(".inv-tab").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        renderItems(td.key);
      });
      tabsEl.appendChild(btn);
    }

    renderItems("all");
  }

  function renderQuest(d) {
    const sec = $("quest-section");
    $("quest-title").textContent = t.quest;
    if (!d.quest) {
      sec.classList.add("hidden");
      return;
    }
    sec.classList.remove("hidden");
    $("quest-text").textContent = d.quest;
  }

  function renderLocation(d) {
    const sec = $("location-section");
    $("loc-title").textContent = t.location;
    if (!d.location || d.location === "Unknown") {
      sec.classList.add("hidden");
      return;
    }
    sec.classList.remove("hidden");
    $("loc-name").textContent = d.location;
    $("loc-desc").textContent = d.location_desc || "";
    if (!d.location_desc) $("loc-desc").classList.add("hidden");
    else $("loc-desc").classList.remove("hidden");
  }

  /* ---- Init ---- */
  load();
})();
