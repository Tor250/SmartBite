"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

type Ingredient = { name: string; quantity: string | null };
type RecipeStep = { instruction: string; duration_minutes: number | null };
type Recipe = {
  id?: number;
  mode: "from_products" | "preferences";
  title: string;
  ingredients: Ingredient[];
  preparation_time_minutes: number | null;
  steps: RecipeStep[];
  missing_products: string[];
  warning: string;
  generator: "demo" | "ai";
  is_saved?: boolean;
  difficulty?: number | null;
  equipment?: string[];
  suitable?: boolean | null;
  liked?: boolean | null;
  review?: string | null;
};
type HistoryItem = Recipe & { id: number; is_saved: boolean; request_context?: string | null };
type Mode = Recipe["mode"];
type Refinement = "clarify" | "adjust" | "replace";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const EQUIPMENT = ["Плита", "Микроволновка", "Чайник", "Мультиварка", "Блендер", "Духовка"];
const DIFFICULTY = ["Сложно", "Скорее сложно", "Средне", "Скорее легко", "Легко"];

function splitItems(value: string): string[] {
  if (/[\n,;]/.test(value)) {
    return value.split(/[\n,;]/).map((item) => item.trim()).filter(Boolean);
  }
  return (value.match(/"[^"]+"|'[^']+'|\S+/g) ?? [])
    .map((item) => item.replace(/^("|')|("|')$/g, "").trim())
    .filter(Boolean);
}

async function api<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Request-ID": crypto.randomUUID(),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    let message = "Не удалось связаться с сервисом. Проверьте соединение и повторите попытку.";
    try {
      const payload = await response.json();
      if (typeof payload.message === "string") message = payload.message;
      else if (typeof payload.detail === "string") message = payload.detail;
    } catch { /* Ответ сервера может быть пустым. */ }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export default function Home() {
  const [mode, setMode] = useState<Mode>("from_products");
  const [products, setProducts] = useState("");
  const [preferences, setPreferences] = useState("");
  const [exclusions, setExclusions] = useState("");
  const [description, setDescription] = useState("");
  const [context, setContext] = useState("");
  const [difficulty, setDifficulty] = useState(3);
  const [equipment, setEquipment] = useState<string[]>([]);
  const [recipe, setRecipe] = useState<Recipe | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [token, setToken] = useState("");
  const [email, setEmail] = useState("");
  const [accountOpen, setAccountOpen] = useState(false);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [password, setPassword] = useState("");
  const [review, setReview] = useState("");
  const [liked, setLiked] = useState<boolean | null>(null);
  const [suitable, setSuitable] = useState<boolean | null>(null);
  const [ratingSaved, setRatingSaved] = useState(false);
  const [refinement, setRefinement] = useState<Refinement>("adjust");
  const [instruction, setInstruction] = useState("");
  const [shareMessage, setShareMessage] = useState("");
  const [shareLink, setShareLink] = useState("");
  const [notice, setNotice] = useState("");

  const activeDifficulty = useMemo(() => DIFFICULTY[difficulty - 1], [difficulty]);

  useEffect(() => {
    const savedToken = window.sessionStorage.getItem("smartbite-token") ?? "";
    const savedEmail = window.sessionStorage.getItem("smartbite-email") ?? "";
    setToken(savedToken);
    setEmail(savedEmail);
  }, []);

  useEffect(() => {
    if (!token) return;
    Promise.all([
      api<{ preferences: string[]; exclusions: string[] }>("/api/profile", {}, token),
      api<HistoryItem[]>("/api/recipes/history", {}, token),
    ])
      .then(([profile, items]) => {
        setPreferences(profile.preferences.join(", "));
        setExclusions(profile.exclusions.join(", "));
        setHistory(items);
      })
      .catch(() => setToken(""));
  }, [token]);

  function toggleEquipment(item: string) {
    setEquipment((current) => current.includes(item) ? current.filter((value) => value !== item) : [...current, item]);
  }

  function requestPayload(): Record<string, unknown> {
    return {
      mode,
      products: splitItems(products),
      description: description.trim() || null,
      preferences: splitItems(preferences),
      exclusions: splitItems(exclusions),
      difficulty,
      equipment,
      request_context: context.trim() || null,
    };
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setNotice("");
    setRecipe(null);
    setLoading(true);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 35_000);
    try {
      if (token) {
        await api("/api/profile", {
          method: "PUT",
          body: JSON.stringify({ preferences: splitItems(preferences), exclusions: splitItems(exclusions) }),
        }, token);
      }
      const endpoint = token ? "/api/recipes/generate" : "/api/v1/recipes/generate";
      const result = await api<Recipe>(endpoint, {
        method: "POST",
        signal: controller.signal,
        body: JSON.stringify(requestPayload()),
      }, token || undefined);
      setRecipe(result);
      setReview("");
      setLiked(null);
      setSuitable(null);
      setRatingSaved(false);
      if (token && result.id) setHistory((items) => [{ ...result, id: result.id!, is_saved: false }, ...items]);
    } catch (caught) {
      setError(caught instanceof Error && caught.name === "AbortError"
        ? "Генератор не ответил вовремя. Все поля запроса сохранены; попробуйте ещё раз."
        : caught instanceof Error ? caught.message : "Не удалось получить рецепт.");
    } finally {
      window.clearTimeout(timeout);
      setLoading(false);
    }
  }

  async function authenticate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      const result = await api<{ access_token: string; email: string }>(`/api/auth/${authMode === "register" ? "register" : "login"}`, {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      window.sessionStorage.setItem("smartbite-token", result.access_token);
      window.sessionStorage.setItem("smartbite-email", result.email);
      setToken(result.access_token);
      setEmail(result.email);
      setPassword("");
      setAccountOpen(false);
      setNotice("Вы вошли. История рецептов теперь сохраняется в аккаунте.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось войти.");
    } finally {
      setLoading(false);
    }
  }

  async function logout() {
    try { await api<void>("/api/auth/logout", { method: "POST" }, token); } catch { /* Локальная сессия всё равно удаляется. */ }
    window.sessionStorage.removeItem("smartbite-token");
    window.sessionStorage.removeItem("smartbite-email");
    setToken("");
    setHistory([]);
    setNotice("Вы вышли из аккаунта.");
  }

  async function saveRating() {
    if (!recipe?.id || !token) return;
    setError("");
    try {
      await api(`/api/recipes/${recipe.id}/rating`, {
        method: "PUT",
        body: JSON.stringify({ liked, suitable, review: review.trim() || null }),
      }, token);
      setRatingSaved(true);
      setNotice("Оценка сохранена.");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось сохранить оценку."); }
  }

  async function refineRecipe() {
    if (!recipe || !instruction.trim()) return;
    setError("");
    setLoading(true);
    try {
      const updated = recipe.id && token
        ? await api<Recipe>(`/api/recipes/${recipe.id}/refine`, {
          method: "POST",
          body: JSON.stringify({ scope: refinement, instruction, difficulty, equipment, request_context: context || null }),
        }, token)
        : await api<Recipe>("/api/v1/recipes/generate", {
          method: "POST",
          body: JSON.stringify({
            mode: "preferences",
            products: splitItems(products),
            preferences: splitItems(preferences),
            exclusions: splitItems(exclusions),
            description: `${refinement === "replace" ? "Предложи совершенно другой рецепт." : refinement === "clarify" ? "Подробно объясни указанный момент, сохранив рецепт." : "Сохрани рецепт и внеси только небольшие изменения."} ${instruction}`,
            difficulty,
            equipment,
            request_context: context || null,
          }),
        });
      setRecipe(updated);
      setInstruction("");
      setRatingSaved(false);
      if (updated.id && token) setHistory((items) => [updated as HistoryItem, ...items]);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось обработать уточнение."); }
    finally { setLoading(false); }
  }

  async function shareRecipe() {
    if (!recipe?.id || !token) return;
    setShareMessage("");
    try {
      const result = await api<{ share_url: string }>(`/api/recipes/${recipe.id}/share`, { method: "POST" }, token);
      const shareToken = new URL(result.share_url).pathname.split("/").pop();
      if (!shareToken) throw new Error("Сервис не вернул ссылку на рецепт.");
      const publicUrl = `${window.location.origin}/shared/${encodeURIComponent(shareToken)}`;
      setShareLink(publicUrl);
      try {
        await navigator.clipboard.writeText(publicUrl);
        setShareMessage("Ссылка скопирована. Откройте её после размещения сервиса в интернете.");
      } catch {
        setShareMessage("Ссылку можно скопировать вручную:");
      }
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось создать ссылку."); }
  }

  async function saveRecipe() {
    if (!recipe?.id || !token) return;
    setError("");
    try {
      const saved = await api<HistoryItem>(`/api/recipes/${recipe.id}/save`, { method: "PUT" }, token);
      setRecipe(saved);
      setHistory((items) => items.map((item) => item.id === saved.id ? saved : item));
      setNotice("Рецепт добавлен в книгу.");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось сохранить рецепт."); }
  }

  async function openHistory(item: HistoryItem) {
    setRecipe(item);
    setMode(item.mode);
    setDifficulty(item.difficulty ?? 3);
    setEquipment(item.equipment ?? []);
    setContext(item.request_context ?? "");
    setLiked(item.liked ?? null);
    setSuitable(item.suitable ?? null);
    setReview(item.review ?? "");
    setRatingSaved(false);
  }

  return (
    <main className="page-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="SmartBite — главная"><span className="brand-symbol">sb</span><span>smartbite</span></a>
        <div className="top-actions">
          <span className="top-caption">Кухня — ваша. Идеи — наши.</span>
          {token ? <button className="account-chip" onClick={() => setAccountOpen(true)}>{email}</button> : <button className="button button-outline" onClick={() => { setError(""); setAccountOpen(true); }}>Войти</button>}
        </div>
      </header>

      <section className="hero" id="top">
        <div className="hero-text">
          <p className="kicker"><span className="kicker-dot" /> РЕЦЕПТЫ ПОД ВАШУ КУХНЮ</p>
          <h1>Ужин начинается<br /><span>с того, что есть.</span></h1>
          <p className="hero-subtitle">Скажите, чего хочется и чем располагаете. Учтём технику, сложность и ваши пожелания.</p>
          <a className="hero-link" href="#recipe-form">Собрать рецепт <span aria-hidden="true">↓</span></a>
        </div>
        <div className="hero-visual" aria-hidden="true">
          <div className="orb orb-one" /><div className="orb orb-two" />
          <div className="food-card"><span className="food-spark">✳</span><span className="food-label">ИДЕЯ НА СЕГОДНЯ</span><span className="food-title">Необычное<br />из обычного</span><span className="food-line" /><span className="food-meta">по вашему вкусу&nbsp; · &nbsp;без суеты</span></div>
          <span className="visual-note note-top">готовим по-своему</span><span className="visual-note note-bottom">каждый день — новый вкус</span>
        </div>
      </section>

      <div className="content-grid" id="recipe-form">
        <section className="form-panel">
          <div className="section-heading"><div><p className="section-overline">ВАШ ЗАПРОС</p><h2>С чего начнём?</h2></div><span className="heading-index">01 / 02</span></div>
          <div className="mode-switch" role="tablist" aria-label="Способ подбора рецепта">
            <button role="tab" aria-selected={mode === "from_products"} className={mode === "from_products" ? "mode-tab active" : "mode-tab"} onClick={() => setMode("from_products")} type="button"><span className="tab-icon">▤</span><span><strong>Из того, что есть</strong><small>Подберём рецепт из продуктов дома</small></span></button>
            <button role="tab" aria-selected={mode === "preferences"} className={mode === "preferences" ? "mode-tab active" : "mode-tab"} onClick={() => setMode("preferences")} type="button"><span className="tab-icon">✳</span><span><strong>По настроению</strong><small>Идея, даже если нужно докупить</small></span></button>
          </div>

          <form onSubmit={submit}>
            {mode === "from_products" ? <label className="field"><span>Что есть дома?</span><textarea value={products} onChange={(event) => setProducts(event.target.value)} placeholder="Картофель, яйца, зелень…" rows={3} required /><small>Разделяйте запятыми, строками или пробелами. Названия из нескольких слов берите в кавычки.</small></label> : <>
              <label className="field"><span>Чего хочется?</span><input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Например: сытный ужин без жарки" /></label>
              <label className="field"><span>Что уже есть <em>необязательно</em></span><textarea value={products} onChange={(event) => setProducts(event.target.value)} placeholder="Можно оставить пустым" rows={2} /><small>Разделяйте запятыми, строками или пробелами.</small></label>
            </>}

            <label className="field"><span>Исключить продукты <em>если нужно</em></span><input value={exclusions} onChange={(event) => setExclusions(event.target.value)} placeholder="Например: арахис, молоко" /></label>
            <label className="field"><span>Любимые предпочтения <em>необязательно</em></span><input value={preferences} onChange={(event) => setPreferences(event.target.value)} placeholder="Например: острое, без жарки" /></label>

            <div className="field range-field"><div className="field-title"><span>Сложность</span><strong>{activeDifficulty}</strong></div><input aria-label="Сложность приготовления: слева сложнее, справа проще" type="range" min="1" max="5" step="1" value={difficulty} onChange={(event) => setDifficulty(Number(event.target.value))} /><div className="range-ends"><span>Сложно</span><span>Легко</span></div></div>

            <fieldset className="equipment-field"><legend>Чем можно готовить?</legend><p>Отметьте доступную технику — подстроим рецепт.</p><div className="equipment-list">{EQUIPMENT.map((item) => <label className={equipment.includes(item) ? "equipment-choice selected" : "equipment-choice"} key={item}><input type="checkbox" checked={equipment.includes(item)} onChange={() => toggleEquipment(item)} /><span className="checkmark" aria-hidden="true">✓</span>{item}</label>)}</div></fieldset>

            <label className="field context-field"><span>Пожелания к рецепту <em>необязательно</em></span><textarea value={context} onChange={(event) => setContext(event.target.value)} placeholder="Например: готовлю в общежитии, духовки нет; хочу уложиться в полчаса" rows={2} /></label>
            <div className="safety-note"><span aria-hidden="true">i</span><p>Проверка ищет совпадения по названиям продуктов. Это не медицинская рекомендация и не гарантия от скрытых ингредиентов.</p></div>
            {error && <div className="error-box" role="alert">{error}<small>Ваш запрос остался в форме.</small></div>}
            <button className="button button-primary submit-button" type="submit" disabled={loading}>{loading ? <><span className="spinner" /> Готовим идею…</> : <>Подобрать рецепт <span aria-hidden="true">↗</span></>}</button>
            <p className="account-hint">{token ? `История сохранится в аккаунте ${email}` : <>Можно попробовать без входа. <button type="button" onClick={() => { setAuthMode("register"); setAccountOpen(true); }}>Войдите</button>, чтобы сохранять историю и отзывы.</>}</p>
          </form>
        </section>

        <section className="result-panel" aria-live="polite">
          {recipe ? <article className="recipe-result">
            <div className="result-topline"><span className="result-label"><i /> {recipe.generator === "ai" ? "РЕЦЕПТ ГОТОВ" : "ДЕМО-РЕЖИМ"}</span>{recipe.preparation_time_minutes && <span className="time-badge">◷ {recipe.preparation_time_minutes} мин</span>}</div>
            <h2>{recipe.title}</h2>
            <div className="recipe-tags">{recipe.difficulty && <span>Сложность: {DIFFICULTY[recipe.difficulty - 1]}</span>}{recipe.mode === "preferences" && <span>По пожеланиям</span>}</div>
            {recipe.missing_products.length > 0 && <div className="missing-box"><strong>Можно докупить</strong><span>{recipe.missing_products.join(" · ")}</span></div>}
            <div className="result-columns"><div className="recipe-section"><h3><span>01</span> Ингредиенты</h3><ul>{recipe.ingredients.map((item, index) => <li key={`${item.name}-${index}`}><span>{item.name}</span>{item.quantity && <small>{item.quantity}</small>}</li>)}</ul></div>
              <div className="recipe-section steps-section"><h3><span>02</span> Приготовление</h3><ol>{recipe.steps.map((step, index) => <li key={`${index}-${step.instruction}`}><i>{String(index + 1).padStart(2, "0")}</i><div>{step.instruction}{step.duration_minutes && <small>{step.duration_minutes} мин</small>}</div></li>)}</ol></div></div>
            {recipe.equipment && recipe.equipment.length > 0 && <p className="recipe-footnote">Учитываем технику: {recipe.equipment.join(", ")}</p>}
            <p className="recipe-warning">{recipe.warning}</p>
            {token && recipe.id && <div className="recipe-actions"><button className="button button-secondary" type="button" onClick={saveRecipe} disabled={recipe.is_saved}>{recipe.is_saved ? "В книге рецептов ✓" : "Сохранить в книгу"}</button><button className="text-button" type="button" onClick={shareRecipe}>↗ Поделиться</button></div>}

            <div className="feedback-box"><div className="feedback-heading"><div><p className="section-overline">ВАШЕ МНЕНИЕ</p><h3>Как вам результат?</h3></div><span>помогает улучшать подбор</span></div>
              <div className="rating-row"><div><span>Понравился</span><div className="choice-buttons"><button className={liked === true ? "choice active" : "choice"} onClick={() => setLiked(true)} type="button">Да</button><button className={liked === false ? "choice active" : "choice"} onClick={() => setLiked(false)} type="button">Нет</button></div></div>
                <div><span>Подходит мне</span><div className="choice-buttons"><button className={suitable === true ? "choice active" : "choice"} onClick={() => setSuitable(true)} type="button">Да</button><button className={suitable === false ? "choice active" : "choice"} onClick={() => setSuitable(false)} type="button">Нет</button></div></div></div>
              <label className="field review-field"><span>Комментарий <em>необязательно</em></span><textarea rows={2} value={review} onChange={(event) => setReview(event.target.value)} placeholder="Что понравилось или что изменить?" /></label>
              {token && recipe.id ? <button className="button button-secondary" type="button" onClick={saveRating}>{ratingSaved ? "Оценка сохранена ✓" : "Сохранить отзыв"}</button> : <p className="login-prompt">Войдите, чтобы сохранить оценку и отзыв.</p>}
            </div>

            <div className="refine-box"><div className="feedback-heading"><div><p className="section-overline">ЕЩЁ ОДИН ШАГ</p><h3>Хотите уточнить?</h3></div></div>
              <div className="refine-options"><button className={refinement === "clarify" ? "refine-option active" : "refine-option"} onClick={() => setRefinement("clarify")} type="button">Спросить</button><button className={refinement === "adjust" ? "refine-option active" : "refine-option"} onClick={() => setRefinement("adjust")} type="button">Немного изменить</button><button className={refinement === "replace" ? "refine-option active" : "refine-option"} onClick={() => setRefinement("replace")} type="button">Другой рецепт</button></div>
              <div className="refine-input"><input value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder={refinement === "clarify" ? "Что объяснить подробнее?" : "Например: без лука, но с грибами"} /><button className="button button-dark" onClick={refineRecipe} disabled={loading || !instruction.trim()} type="button">Отправить <span>→</span></button></div>
            </div>
            {token && recipe.id && shareMessage && <div className="share-row"><small>{shareMessage}</small>{shareLink && <a className="share-link" href={shareLink}>{shareLink}</a>}</div>}
          </article> : <div className="result-empty"><div className="empty-art"><span className="empty-ring ring-a"/><span className="empty-ring ring-b"/><span className="empty-center">✳</span><span className="empty-spark spark-a">✦</span><span className="empty-spark spark-b">·</span></div><p className="section-overline">ВАША СЛЕДУЮЩАЯ ИДЕЯ</p><h2>{error ? "Запрос не сработал" : "Здесь будет вкусно."}</h2><p>{error ? "Поправьте запрос и отправьте его ещё раз." : "Выберите продукты или расскажите, чего хочется — соберём рецепт под вашу кухню."}</p><div className="empty-rule"/><span className="empty-caption">ОТ ПРОДУКТОВ ДО ГОТОВОГО БЛЮДА</span></div>}
        </section>
      </div>

      {token && <section className="history-section"><div className="history-heading"><div><p className="section-overline">ВАШИ ИДЕИ</p><h2>Недавние рецепты</h2></div><span>{history.length} {history.length === 1 ? "рецепт" : "рецептов"}</span></div>{history.length ? <div className="history-list">{history.slice(0, 6).map((item) => <button className="history-item" key={item.id} onClick={() => openHistory(item)}><span className="history-bullet">✳</span><span><strong>{item.title}</strong><small>{item.mode === "from_products" ? "Из продуктов дома" : "По пожеланиям"}</small></span><span className="history-arrow">↗</span></button>)}</div> : <p className="history-empty">Сгенерируйте первый рецепт — он появится здесь.</p>}</section>}

      <footer className="footer"><a className="brand footer-brand" href="#top"><span className="brand-symbol">sb</span><span>smartbite</span></a><span>Идеи для кухни, которая у вас есть.</span><span>Рецепты требуют проверки перед приготовлением.</span></footer>

      {notice && <div className="toast" role="status">{notice}<button onClick={() => setNotice("")} aria-label="Закрыть уведомление">×</button></div>}
      {error && accountOpen && <div className="toast toast-error" role="alert">{error}<button onClick={() => setError("")} aria-label="Закрыть уведомление">×</button></div>}
      {accountOpen && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setAccountOpen(false); }}><section className="account-modal" role="dialog" aria-modal="true" aria-labelledby="account-title"><button className="modal-close" onClick={() => setAccountOpen(false)} aria-label="Закрыть">×</button>{token ? <><p className="section-overline">АККАУНТ</p><h2 id="account-title">Вы вошли как</h2><p className="modal-email">{email}</p><p className="modal-copy">История генераций и отзывы сохраняются в этом аккаунте.</p><button className="button button-dark modal-submit" onClick={logout}>Выйти</button></> : <><p className="section-overline">ВАШИ РЕЦЕПТЫ</p><h2 id="account-title">{authMode === "login" ? "С возвращением." : "Создать аккаунт."}</h2><p className="modal-copy">Сохраняйте историю и возвращайтесь к любимым идеям.</p><div className="auth-switch"><button className={authMode === "login" ? "active" : ""} onClick={() => setAuthMode("login")}>Войти</button><button className={authMode === "register" ? "active" : ""} onClick={() => setAuthMode("register")}>Регистрация</button></div><form onSubmit={authenticate}><label className="field"><span>Электронная почта</span><input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@example.com" required /></label><label className="field"><span>Пароль</span><input type="password" autoComplete={authMode === "login" ? "current-password" : "new-password"} value={password} onChange={(event) => setPassword(event.target.value)} minLength={authMode === "register" ? 8 : 1} required /></label><button className="button button-primary modal-submit" disabled={loading}>{loading ? "Подождите…" : authMode === "login" ? "Войти в аккаунт" : "Создать аккаунт"}</button></form><p className="modal-footnote">Вход по почте и паролю позволяет сохранять историю рецептов и отзывы.</p></>}</section></div>}
    </main>
  );
}
