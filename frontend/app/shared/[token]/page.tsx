"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

type SharedRecipe = {
  title: string;
  ingredients: { name: string; quantity: string | null }[];
  preparation_time_minutes: number | null;
  steps: { instruction: string; duration_minutes: number | null }[];
  missing_products: string[];
  warning: string;
};

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function SharedRecipePage() {
  const params = useParams<{ token: string }>();
  const [recipe, setRecipe] = useState<SharedRecipe | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    fetch(`${API_URL}/api/shared/recipes/${encodeURIComponent(params.token)}`)
      .then(async (response) => {
        if (!response.ok) throw new Error("Эта ссылка больше не работает или рецепт недоступен.");
        return response.json() as Promise<SharedRecipe>;
      })
      .then((value) => { if (active) setRecipe(value); })
      .catch((caught: unknown) => { if (active) setError(caught instanceof Error ? caught.message : "Не удалось открыть рецепт."); });
    return () => { active = false; };
  }, [params.token]);

  return <main className="shared-page">
    <header className="shared-header"><a className="brand" href="/"><span className="brand-symbol">sb</span><span>smartbite</span></a><span>ИДЕЯ ДЛЯ ВАШЕГО СТОЛА</span></header>
    {recipe ? <article className="shared-recipe">
      <p className="section-overline">РЕЦЕПТ, КОТОРЫМ ПОДЕЛИЛИСЬ</p>
      <h1>{recipe.title}</h1>
      {recipe.preparation_time_minutes && <p className="shared-time">◷ Примерно {recipe.preparation_time_minutes} минут</p>}
      <div className="shared-columns"><section className="recipe-section"><h2><span>01</span> Ингредиенты</h2><ul>{recipe.ingredients.map((item, index) => <li key={`${item.name}-${index}`}><span>{item.name}</span>{item.quantity && <small>{item.quantity}</small>}</li>)}</ul>{recipe.missing_products.length > 0 && <p className="shared-missing">Можно докупить: {recipe.missing_products.join(", ")}</p>}</section>
        <section className="recipe-section"><h2><span>02</span> Приготовление</h2><ol>{recipe.steps.map((step, index) => <li key={`${index}-${step.instruction}`}><i>{String(index + 1).padStart(2, "0")}</i><div>{step.instruction}{step.duration_minutes && <small>{step.duration_minutes} мин</small>}</div></li>)}</ol></section></div>
      <p className="recipe-warning">{recipe.warning}</p><a className="button button-dark shared-cta" href="/">Собрать свой рецепт <span>↗</span></a>
    </article> : <section className="shared-empty"><span className="empty-center">✳</span><p className="section-overline">SMARTBITE</p><h1>{error ? "Рецепт недоступен" : "Открываем рецепт…"}</h1><p>{error || "Загружаем то, чем с вами поделились."}</p><a href="/">На главную</a></section>}
    <footer className="shared-footer">SmartBite — идеи для кухни, которая у вас есть.</footer>
  </main>;
}
