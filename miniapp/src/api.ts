import type { CharacterRoot } from "./types";

function resolveUserId(): number | null {
  const qp = new URLSearchParams(window.location.search);
  const fromQuery = qp.get("user_id");
  if (fromQuery) {
    const n = Number(fromQuery);
    if (Number.isFinite(n) && n > 0) return n;
  }

  const tg = (window as any).Telegram?.WebApp;
  const fromUnsafe = tg?.initDataUnsafe?.user?.id;
  if (typeof fromUnsafe === "number" && fromUnsafe > 0) return fromUnsafe;

  // Fallback: parse signed initData (url-encoded) manually. Occasionally the
  // Mini App is opened before the Telegram JS finishes populating
  // initDataUnsafe — but initData itself is already filled by the launcher.
  const rawInit: string | undefined = tg?.initData;
  if (rawInit && typeof rawInit === "string") {
    try {
      const params = new URLSearchParams(rawInit);
      const userBlob = params.get("user");
      if (userBlob) {
        const parsed = JSON.parse(userBlob);
        if (parsed && typeof parsed.id === "number" && parsed.id > 0) {
          return parsed.id;
        }
      }
    } catch {
      // ignore — will fall through to null and surface a user-visible error
    }
  }
  return null;
}

export async function loadCharacter(): Promise<{ userId: number | null; data: CharacterRoot | null; error: string | null }> {
  const userId = resolveUserId();
  if (!userId) {
    return { userId: null, data: null, error: "Не удалось определить Telegram user_id." };
  }
  try {
    const res = await fetch(`/dnd_bot/api/character/${userId}`, { credentials: "same-origin" });
    if (!res.ok) {
      return { userId, data: null, error: `API ошибка: ${res.status}` };
    }
    const data = (await res.json()) as CharacterRoot;
    return { userId, data, error: null };
  } catch (e) {
    return { userId, data: null, error: `Сеть недоступна: ${String(e)}` };
  }
}
