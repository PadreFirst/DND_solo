import { useEffect, useMemo, useState } from "react";
import { loadCharacter } from "./api";
import type { CharacterRoot } from "./types";

type Tab = "overview" | "inventory" | "quests" | "skills" | "world";

function pct(current: number, max: number): number {
  if (max <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((current / max) * 100)));
}

function Progress({ value, color = "#6c8cff" }: { value: number; color?: string }) {
  return (
    <div className="bar">
      <div className="bar-fill" style={{ width: `${value}%`, background: color }} />
    </div>
  );
}

function section(title: string, children: JSX.Element) {
  return (
    <section className="card">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

export default function App() {
  const [tab, setTab] = useState<Tab>("overview");
  const [data, setData] = useState<CharacterRoot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const tg = (window as any).Telegram?.WebApp;
    if (tg?.ready) tg.ready();
    if (tg?.expand) tg.expand();
  }, []);

  useEffect(() => {
    let active = true;
    loadCharacter().then((res) => {
      if (!active) return;
      setData(res.data);
      setError(res.error);
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, []);

  const hpPct = useMemo(() => (data ? pct(data.character.hp_current, data.character.hp_max) : 0), [data]);
  const xpPct = useMemo(() => (data ? pct(data.character.xp_current, data.character.xp_to_next_level) : 0), [data]);

  if (loading) {
    return <div className="page">Загрузка...</div>;
  }
  if (error || !data) {
    return <div className="page error">{error || "Нет данных персонажа"}</div>;
  }

  const c = data.character;
  const activeQuests = data.quests?.active || [];
  const completedQuests = data.quests?.completed || [];
  const inventory = data.inventory || [];
  const conditions = data.conditions || [];

  return (
    <div className="page">
      <header className="header card">
        <div className="name">{c.name}</div>
        <div className="meta">
          {c.class} • {c.race} • Ур. {c.level}
        </div>
        <div className="meta">{c.universe}</div>
      </header>

      {tab === "overview" && (
        <>
          {section(
            "♥ HP",
            <>
              <div className="row">
                <span>
                  {c.hp_current} / {c.hp_max}
                </span>
                <span>{hpPct}%</span>
              </div>
              <Progress value={hpPct} color={hpPct < 25 ? "#ff5b6e" : "#53d27d"} />
              <div className="small">Временные HP: {c.temp_hp || 0}</div>
            </>
          )}
          {section(
            "⭐ XP",
            <>
              <div className="row">
                <span>
                  {c.xp_current} / {c.xp_to_next_level}
                </span>
                <span>{xpPct}%</span>
              </div>
              <Progress value={xpPct} color="#9f7aff" />
            </>
          )}
          {section(
            "Быстрые статы",
            <div className="grid4">
              <div>💰 {c.gold}</div>
              <div>🛡 КД {c.ac}</div>
              <div>🏃 {c.speed}м</div>
              <div>🎲 +{c.proficiency_bonus}</div>
            </div>
          )}
          {section(
            "Состояния",
            <div className="chips">
              {conditions.length === 0 ? (
                <span className="chip">Нет активных</span>
              ) : (
                conditions.map((s, i) => (
                  <span key={i} className="chip" title={s.description || s.name || ""}>
                    {s.emoji || "⚠"} {s.display || s.name || "Состояние"}
                  </span>
                ))
              )}
            </div>
          )}
        </>
      )}

      {tab === "inventory" && (
        <>
          {section(
            "Экипировка",
            <div className="list">
              {Object.entries(data.equipment || {}).map(([slot, item]) => (
                <div key={slot} className="item">
                  <b>{slot}</b>: {item ? `${item.emoji || ""} ${item.name}` : "—"}
                </div>
              ))}
            </div>
          )}
          {section(
            "Инвентарь",
            <div className="list">
              {inventory.length === 0 ? (
                <div className="item">Пусто</div>
              ) : (
                inventory.map((it, i) => (
                  <div key={i} className="item">
                    {(it.emoji || "🎒") + " " + it.name} [{it.quantity || 1}] {it.is_equipped ? "• экип." : ""}
                  </div>
                ))
              )}
            </div>
          )}
          {section(
            "Рецепты",
            <div className="list">
              {(data.known_recipes || []).map((r, i) => (
                <div key={i} className="item">
                  {(r.emoji || "📜") + " " + r.name} {r.can_craft ? "✅" : "❌"}
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {tab === "quests" && (
        <>
          {section(
            "Активные квесты",
            <div className="list">
              {activeQuests.length === 0 ? (
                <div className="item">Нет активных квестов</div>
              ) : (
                activeQuests.map((q) => (
                  <div key={q.quest_id} className="quest">
                    <div className="quest-title">{q.is_main ? "⭐ " : ""}{q.title}</div>
                    <div className="small">{q.description || ""}</div>
                    {(q.steps || []).map((s, i) => (
                      <div key={i} className="small">
                        {s.completed ? "✅" : "⬜"} {s.text}
                      </div>
                    ))}
                  </div>
                ))
              )}
            </div>
          )}
          {section(
            `Выполнено (${completedQuests.length})`,
            <div className="list">
              {completedQuests.map((q) => (
                <div key={q.quest_id} className="item">
                  ✅ {q.title}
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {tab === "skills" && (
        <>
          {section(
            "Характеристики",
            <div className="grid2">
              {Object.entries(data.abilities || {}).map(([k, v]) => (
                <div key={k} className="stat">
                  <div>{k}</div>
                  <div>{v}</div>
                </div>
              ))}
            </div>
          )}
          {section(
            "Навыки",
            <div className="list">
              {(data.skills || []).map((s, i) => (
                <div key={i} className="item">
                  {s.proficient ? "●" : "○"} {s.name}
                </div>
              ))}
            </div>
          )}
          {section(
            "Классовые фичи",
            <div className="list">
              {(data.class_features || []).map((f, i) => (
                <div key={i} className="item">
                  {(f.emoji || "✨") + " " + f.name}
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {tab === "world" && (
        <>
          {section(
            "Локация",
            <div>
              <div className="item">📍 {data.location?.name || "Неизвестно"}</div>
              <div className="small">{data.location?.description || ""}</div>
              <div className="small">
                {data.location?.time_of_day || "day"} • {data.location?.weather || "clear"}
              </div>
            </div>
          )}
          {section(
            "NPC",
            <div className="list">
              {(data.location?.npcs || []).map((n, i) => (
                <div key={i} className="item">
                  {n.name} • {n.attitude || "neutral"} {n.is_merchant ? "• 🛒" : ""}
                </div>
              ))}
            </div>
          )}
          {section(
            "Фракции",
            <div className="list">
              {(data.factions || []).map((f, i) => (
                <div key={i} className="item">
                  {f.name}: {f.score}
                </div>
              ))}
            </div>
          )}
          {section(
            "История",
            <div className="small">{data.adventure_summary || "Пока пусто"}</div>
          )}
        </>
      )}

      <nav className="tabs">
        <button className={tab === "overview" ? "active" : ""} onClick={() => setTab("overview")}>👤</button>
        <button className={tab === "inventory" ? "active" : ""} onClick={() => setTab("inventory")}>🎒</button>
        <button className={tab === "quests" ? "active" : ""} onClick={() => setTab("quests")}>📋</button>
        <button className={tab === "skills" ? "active" : ""} onClick={() => setTab("skills")}>📊</button>
        <button className={tab === "world" ? "active" : ""} onClick={() => setTab("world")}>🗺</button>
      </nav>
    </div>
  );
}
