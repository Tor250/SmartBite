"use client";

import { FormEvent, useState } from "react";

type Ingredient = {
  name: string;
  quantity: string | null;
};

type RecipeStep = {
  instruction: string;
  duration_minutes: number | null;
};

type Recipe = {
  title: string;
  ingredients: Ingredient[];
  preparation_time_minutes: number | null;
  steps: RecipeStep[];
  warning: string;
  generator: "demo" | "ai";
};

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function splitLines(value: string): string[] {
  return value.split(/[\n,;]/).map((item) => item.trim()).filter(Boolean);
}

async function responseError(response: Response): Promise<string> {
  try {
    const payload = await response.json();
    if (typeof payload.message === "string") return payload.message;
    if (typeof payload.detail === "string") return payload.detail;
  } catch {
    // Use the same simple message for invalid or empty error responses.
  }
  return "Не удалось связаться с сервисом. Попробуйте ещё раз.";
}

export default function Home() {
  const [products, setProducts] = useState("");
  const [exclusions, setExclusions] = useState("");
  const [recipe, setRecipe] = useState<Recipe | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setRecipe(null);
    setError("");
    setLoading(true);
    const controller = new AbortController();
    // Leave a short margin after the backend's 30-second timeout so its
    // actionable JSON error can reach the form before the browser aborts.
    const timeout = window.setTimeout(() => controller.abort(), 35_000);
    try {
      const response = await fetch(API_URL + "/api/v1/recipes/generate", {
        method: "POST",
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          "X-Request-ID": crypto.randomUUID(),
        },
        body: JSON.stringify({
          products: splitLines(products),
          exclusions: splitLines(exclusions),
        }),
      });
      if (!response.ok) throw new Error(await responseError(response));
      setRecipe((await response.json()) as Recipe);
    } catch (caught) {
      if (caught instanceof Error && caught.name === "AbortError") {
        setError("Сервис не ответил за 35 секунд. Запрос остался в форме; попробуйте ещё раз.");
      } else {
        setError(caught instanceof Error ? caught.message : "Не удалось связаться с сервисом. Попробуйте ещё раз.");
      }
    } finally {
      window.clearTimeout(timeout);
      setLoading(false);
    }
  }

  return (
    <main className="shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="SmartBite — на главную">
          <span className="brand-mark">S</span> SmartBite
        </a>
        <span className="top-note">Рецепт из продуктов дома</span>
      </header>

      <section className="hero" id="top">
        <div className="hero-copy">
          <p className="eyebrow">ГОТОВИМ ИЗ ТОГО, ЧТО ЕСТЬ</p>
          <h1>Что приготовить<br />сегодня?</h1>
          <p className="intro">Перечислите продукты, которые есть дома. SmartBite предложит рецепт и проверит его по указанным исключениям.</p>
        </div>
        <div className="hero-art" aria-hidden="true">
          <div className="plate"><span className="leaf leaf-one" /><span className="leaf leaf-two" /><span className="tomato" /><span className="grain grain-one" /><span className="grain grain-two" /></div>
        </div>
      </section>

      <div className="demo-banner"><strong>Без регистрации.</strong> Введите продукты и исключения для одного запроса.</div>

      <div className="workspace">
        <section className="request-card">
          <div className="card-heading"><div><p className="eyebrow">ВАШ ЗАПРОС</p><h2>Что есть на кухне?</h2></div><span className="step-number">01</span></div>
          <form onSubmit={submit}>
            <label className="field">
              <span>Продукты</span>
              <textarea value={products} onChange={(event) => setProducts(event.target.value)} placeholder="Например: рис, томаты, куриное филе" rows={4} required />
              <small>Разделяйте продукты запятыми или переносами строк.</small>
            </label>
            <label className="field">
              <span>Исключения <em>если есть</em></span>
              <textarea value={exclusions} onChange={(event) => setExclusions(event.target.value)} placeholder="Например: молоко, арахис" rows={2} />
              <small>Укажите ограничения, которые нужно учесть в этом запросе.</small>
            </label>
            <p className="warning preflight-warning" role="note">
              Проверка использует ограниченный словарь названий. Она не выявляет скрытые ингредиенты и следы перекрёстного загрязнения и не является медицинской гарантией.
            </p>
            {error && <div className="form-error" role="alert">{error}<p className="retained">Запрос оставлен в форме. Исправьте его или попробуйте ещё раз.</p></div>}
            <button className="submit" type="submit" disabled={loading}>
              {loading ? "Генерируем и проверяем…" : "Подобрать рецепт"}<span aria-hidden="true">→</span>
            </button>
            <p className="privacy-note">Рецепт появится только после проверки ингредиентов.</p>
          </form>
        </section>

        <section className="result-card" aria-live="polite">
          {recipe ? (
            <article className="recipe">
              <p className="eyebrow">{recipe.generator === "ai" ? "ПРОВЕРКА ПРОЙДЕНА · РЕЦЕПТ ОТ ИИ" : "ДЕМОНСТРАЦИОННЫЙ РЕЖИМ"}</p>
              <h2>{recipe.title}</h2>
              {recipe.preparation_time_minutes && <p className="recipe-time">Примерное время: {recipe.preparation_time_minutes} мин</p>}
              <div className="recipe-section">
                <h3>Ингредиенты</h3>
                <ul>{recipe.ingredients.map((item, index) => <li key={item.name + index}>{item.name}{item.quantity ? ` — ${item.quantity}` : ""}</li>)}</ul>
              </div>
              <div className="recipe-section">
                <h3>Приготовление</h3>
                <ol>{recipe.steps.map((step, index) => <li key={String(index) + step.instruction}>
                  {step.instruction}{step.duration_minutes && <small className="step-time">{step.duration_minutes} мин</small>}
                </li>)}</ol>
              </div>
              {recipe.generator === "demo" && <p className="warning">Это демонстрационный шаблон: он проверяет работу формы и фильтра, но не заменяет полноценную генерацию рецепта.</p>}
              <p className="warning">{recipe.warning}</p>
            </article>
          ) : (
            <div className="empty-state">
              <div className="result-icon" aria-hidden="true">✳</div>
              <p className="eyebrow">РЕЗУЛЬТАТ</p>
              <h2>{error ? "Рецепт не показан" : "Здесь появится рецепт"}</h2>
              <p>{error ? "Сервис не показал непроверенный результат. Поправьте запрос и попробуйте ещё раз." : "Сначала укажите продукты, которые есть дома."}</p>
            </div>
          )}
        </section>
      </div>

    </main>
  );
}
