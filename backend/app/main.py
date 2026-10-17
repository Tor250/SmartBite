from typing import Annotated, Literal
import secrets

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth_service import login_user, register_user, resolve_session, revoke_session
from .application.recipes import (
    GenerateRecipeCommand,
    RecipeRequestError,
    RecipeSafetyCheckError,
    generate_recipe as generate_recipe_use_case,
)
from .database import get_db
from .generator import DemoRecipeGenerator, RecipeGenerationError, RecipeStep, configured_recipe_generator
from .generation_runner import GenerationBusy, GenerationRunner, GenerationTimedOut
from .models import Profile, Recipe, RecipeRating, UsageEvent, User, utc_now
from .observability import RequestLoggingMiddleware, configure_logging
from .safety import check_ingredients


configure_logging()
app = FastAPI(title="SmartBite API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)
app.add_middleware(RequestLoggingMiddleware)


bearer = HTTPBearer(auto_error=False)
generator = configured_recipe_generator()
generation_runner = GenerationRunner()
USER_WARNING = (
    "Проверка учитывает только названия из ограниченного словаря. "
    "Она не выявляет скрытые компоненты и следы перекрёстного загрязнения "
    "и не является медицинской гарантией."
)


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class AuthResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user_id: int
    email: str


class ProfileUpdate(BaseModel):
    preferences: list[str] = Field(default_factory=list, max_length=30)
    exclusions: list[str] = Field(default_factory=list, max_length=30)


class ProfileResponse(ProfileUpdate):
    email: str


class GenerateRequest(BaseModel):
    mode: Literal["from_products", "preferences"]
    products: list[str] = Field(default_factory=list, max_length=40)
    description: str | None = Field(default=None, max_length=1000)
    preferences: list[str] = Field(default_factory=list, max_length=30)


class MvpGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["from_products", "preferences"] = "from_products"
    products: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(default_factory=list, max_length=40)
    exclusions: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(default_factory=list, max_length=30)
    preferences: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(default_factory=list, max_length=30)
    description: str | None = Field(default=None, max_length=1000)


class IngredientResponse(BaseModel):
    name: str
    quantity: str | None


class StepResponse(BaseModel):
    instruction: str
    duration_minutes: int | None = None


class MvpRecipeResponse(BaseModel):
    mode: Literal["from_products", "preferences"]
    title: str
    ingredients: list[IngredientResponse]
    preparation_time_minutes: int | None = None
    steps: list[StepResponse]
    missing_products: list[str] = Field(default_factory=list)
    warning: str
    generator: Literal["demo", "ai"]


class RatingRequest(BaseModel):
    suitable: bool | None = None
    liked: bool | None = None
    review: str | None = Field(default=None, max_length=1000)


class ShareResponse(BaseModel):
    share_url: str


class SharedRecipeResponse(BaseModel):
    title: str
    ingredients: list[IngredientResponse]
    preparation_time_minutes: int | None
    steps: list[StepResponse]
    missing_products: list[str]
    warning: str


class RecipeResponse(BaseModel):
    id: int
    mode: Literal["from_products", "preferences"]
    is_saved: bool
    title: str
    ingredients: list[IngredientResponse]
    preparation_time_minutes: int | None
    steps: list[StepResponse]
    missing_products: list[str]
    warning: str
    generator: Literal["demo", "ai"]
    suitable: bool | None = None
    liked: bool | None = None
    review: str | None = None


def recipe_response(recipe: Recipe, rating: RecipeRating | None = None) -> RecipeResponse:
    return RecipeResponse(
        id=recipe.id,
        mode=recipe.mode,
        is_saved=recipe.is_saved,
        title=recipe.title,
        ingredients=[
            IngredientResponse(**item) if isinstance(item, dict) else IngredientResponse(name=str(item), quantity=None)
            for item in recipe.ingredients
        ],
        preparation_time_minutes=recipe.preparation_time_minutes,
        steps=[_step_response(item) for item in recipe.steps],
        missing_products=recipe.missing_products,
        warning=USER_WARNING,
        generator="demo" if isinstance(generator, DemoRecipeGenerator) else "ai",
        suitable=rating.suitable if rating else None,
        liked=rating.liked if rating else None,
        review=rating.review if rating else None,
    )


def _step_response(value: str | dict | RecipeStep) -> StepResponse:
    if isinstance(value, RecipeStep):
        return StepResponse(instruction=value.instruction, duration_minutes=value.duration_minutes)
    if isinstance(value, str):
        return StepResponse(instruction=value)
    return StepResponse(**value)


async def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Войдите в аккаунт.")
    user = resolve_session(db, credentials.credentials)
    if user is None:
        raise HTTPException(status_code=401, detail="Сессия завершилась. Войдите снова.")
    return user


def _auth_response(result) -> AuthResponse:
    return AuthResponse(
        access_token=result.access_token,
        user_id=result.user.id,
        email=result.user.email,
    )


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/recipes/generate", response_model=MvpRecipeResponse)
async def generate_mvp_recipe(request: MvpGenerateRequest, http_request: Request) -> JSONResponse:
    try:
        command = GenerateRecipeCommand(
            mode=request.mode,
            products=[item.strip() for item in request.products if item.strip()],
            description=request.description.strip() if request.description else None,
            preferences=[item.strip() for item in request.preferences if item.strip()],
            exclusions=[item.strip() for item in request.exclusions if item.strip()],
        )
        candidate = await generation_runner.run(generate_recipe_use_case, command, generator)
    except GenerationBusy:
        return JSONResponse(
            status_code=503,
            content={
                "code": "GENERATOR_BUSY",
                "message": "Сервис генерации занят. Попробуйте ещё раз чуть позже.",
                "request_id": http_request.state.request_id,
            },
        )
    except GenerationTimedOut:
        return JSONResponse(
            status_code=503,
            content={
                "code": "GENERATOR_TIMEOUT",
                "message": "Генератор не ответил вовремя. Попробуйте ещё раз.",
                "request_id": http_request.state.request_id,
            },
        )
    except RecipeSafetyCheckError:
        return JSONResponse(
            status_code=503,
            content={
                "code": "SAFETY_CHECK_UNAVAILABLE",
                "message": "Не удалось проверить ингредиенты. Рецепт не показан; попробуйте ещё раз.",
                "request_id": http_request.state.request_id,
            },
        )
    except RecipeRequestError as error:
        return JSONResponse(
            status_code=422,
            content={
                "code": "RECIPE_REJECTED",
                "message": str(error),
                "request_id": http_request.state.request_id,
            },
        )
    except RecipeGenerationError:
        return JSONResponse(
            status_code=503,
            content={
                "code": "GENERATOR_UNAVAILABLE",
                "message": "Не удалось получить рецепт. Проверьте запрос и попробуйте ещё раз.",
                "request_id": http_request.state.request_id,
            },
        )
    response = MvpRecipeResponse(
        mode=request.mode,
        title=candidate.title,
        ingredients=[IngredientResponse(name=item.name, quantity=item.quantity) for item in candidate.ingredients],
        preparation_time_minutes=candidate.preparation_time_minutes,
        steps=[_step_response(item) for item in candidate.steps],
        missing_products=candidate.missing_products,
        warning=USER_WARNING,
        generator="demo" if isinstance(generator, DemoRecipeGenerator) else "ai",
    )
    return JSONResponse(content=response.model_dump(mode="json"))


@app.post("/api/auth/register", response_model=AuthResponse, status_code=201)
async def register(credentials: Credentials, db: Session = Depends(get_db)) -> AuthResponse:
    try:
        return _auth_response(register_user(db, credentials.email, credentials.password))
    except ValueError as error:
        status = 409 if "уже существует" in str(error) else 422
        raise HTTPException(status_code=status, detail=str(error)) from error


@app.post("/api/auth/login", response_model=AuthResponse)
async def login(credentials: Credentials, db: Session = Depends(get_db)) -> AuthResponse:
    try:
        return _auth_response(login_user(db, credentials.email, credentials.password))
    except ValueError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error


@app.post("/api/auth/logout", status_code=204)
async def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> None:
    if credentials is not None:
        revoke_session(db, credentials.credentials)


@app.get("/api/profile", response_model=ProfileResponse)
async def get_profile(user: User = Depends(current_user)) -> ProfileResponse:
    profile = user.profile or Profile(user_id=user.id, preferences=[], exclusions=[])
    return ProfileResponse(email=user.email, preferences=profile.preferences, exclusions=profile.exclusions)


@app.put("/api/profile", response_model=ProfileResponse)
async def update_profile(
    values: ProfileUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProfileResponse:
    preferences = [item.strip() for item in values.preferences if item.strip()]
    exclusions = [item.strip() for item in values.exclusions if item.strip()]
    if any(len(item) > 100 for item in preferences + exclusions):
        raise HTTPException(status_code=422, detail="Каждое значение должно быть короче 100 символов.")
    profile = user.profile
    if profile is None:
        profile = Profile(user_id=user.id)
        db.add(profile)
    profile.preferences = preferences
    profile.exclusions = exclusions
    db.commit()
    return ProfileResponse(email=user.email, preferences=preferences, exclusions=exclusions)


@app.delete("/api/account", status_code=204)
async def delete_account(user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    db.delete(user)
    db.commit()


@app.post("/api/recipes/generate", response_model=RecipeResponse)
async def generate_recipe(
    request: GenerateRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> RecipeResponse:
    products = [item.strip() for item in request.products if item.strip()]
    description = request.description.strip() if request.description else None
    preferences = user.profile.preferences if user.profile else []
    exclusions = user.profile.exclusions if user.profile else []
    try:
        candidate = await generation_runner.run(
            generate_recipe_use_case,
            GenerateRecipeCommand(
                mode=request.mode,
                products=products,
                description=description,
                preferences=preferences + [item.strip() for item in request.preferences if item.strip()],
                exclusions=exclusions,
            ),
            generator,
        )
    except RecipeSafetyCheckError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except RecipeRequestError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RecipeGenerationError as error:
        raise HTTPException(status_code=503, detail="Не удалось получить рецепт. Попробуйте ещё раз.") from error
    except GenerationBusy as error:
        raise HTTPException(
            status_code=503,
            detail="Сервис генерации занят. Попробуйте ещё раз чуть позже.",
        ) from error
    except GenerationTimedOut as error:
        raise HTTPException(
            status_code=503,
            detail="Генератор не ответил вовремя. Попробуйте ещё раз.",
        ) from error

    recipe = Recipe(
        user_id=user.id,
        mode=request.mode,
        input_products=products,
        description=description,
        title=candidate.title,
        ingredients=[{"name": item.name, "quantity": item.quantity} for item in candidate.ingredients],
        preparation_time_minutes=candidate.preparation_time_minutes,
        steps=[{"instruction": item.instruction, "duration_minutes": item.duration_minutes} for item in candidate.steps],
        missing_products=candidate.missing_products,
    )
    has_previous_request = db.scalar(select(UsageEvent.id).where(UsageEvent.user_id == user.id).limit(1))
    db.add(recipe)
    db.flush()
    db.add(
        UsageEvent(
            user_id=user.id,
            event_type="recipe_shown_repeat" if has_previous_request else "recipe_shown_first",
            occurred_at=utc_now(),
        )
    )
    db.commit()
    db.refresh(recipe)
    return recipe_response(recipe)


@app.get("/api/recipes", response_model=list[RecipeResponse])
async def list_recipes(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[RecipeResponse]:
    records = db.scalars(
        select(Recipe).where(Recipe.user_id == user.id, Recipe.is_saved.is_(True)).order_by(Recipe.created_at.desc())
    ).all()
    return [recipe_response(record, record.rating) for record in records]


@app.get("/api/recipes/history", response_model=list[RecipeResponse])
async def recipe_history(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[RecipeResponse]:
    records = db.scalars(
        select(Recipe).where(Recipe.user_id == user.id).order_by(Recipe.created_at.desc())
    ).all()
    return [recipe_response(record, record.rating) for record in records]


@app.post("/api/recipes/{recipe_id}/share", response_model=ShareResponse)
async def share_recipe(
    recipe_id: int,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ShareResponse:
    record = db.scalar(select(Recipe).where(Recipe.id == recipe_id, Recipe.user_id == user.id))
    if record is None:
        raise HTTPException(status_code=404, detail="Рецепт не найден.")
    exclusions = user.profile.exclusions if user.profile else []
    check = check_ingredients([item["name"] for item in record.ingredients], exclusions)
    if not check.allowed:
        raise HTTPException(status_code=422, detail="Рецепт не прошёл повторную проверку и не опубликован.")
    if record.share_token is None:
        record.share_token = secrets.token_urlsafe(24)
        db.commit()
    return ShareResponse(
        share_url=f"{str(request.base_url).rstrip('/')}/api/shared/recipes/{record.share_token}"
    )


@app.delete("/api/recipes/{recipe_id}/share", status_code=204)
async def revoke_recipe_share(
    recipe_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> None:
    record = db.scalar(select(Recipe).where(Recipe.id == recipe_id, Recipe.user_id == user.id))
    if record is None:
        raise HTTPException(status_code=404, detail="Рецепт не найден.")
    record.share_token = None
    db.commit()


@app.get("/api/shared/recipes/{share_token}", response_model=SharedRecipeResponse)
async def read_shared_recipe(share_token: str, db: Session = Depends(get_db)) -> SharedRecipeResponse:
    record = db.scalar(select(Recipe).where(Recipe.share_token == share_token))
    if record is None:
        raise HTTPException(status_code=404, detail="Ссылка недействительна или отозвана.")
    exclusions = record.user.profile.exclusions if record.user and record.user.profile else []
    check = check_ingredients([item["name"] for item in record.ingredients], exclusions)
    if not check.allowed:
        raise HTTPException(status_code=404, detail="Рецепт больше недоступен по этой ссылке.")
    return SharedRecipeResponse(
        title=record.title,
        ingredients=[IngredientResponse(**item) for item in record.ingredients],
        preparation_time_minutes=record.preparation_time_minutes,
        steps=[_step_response(item) for item in record.steps],
        missing_products=record.missing_products,
        warning=USER_WARNING,
    )


@app.put("/api/recipes/{recipe_id}/save", response_model=RecipeResponse)
async def save_recipe(
    recipe_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> RecipeResponse:
    record = db.scalar(select(Recipe).where(Recipe.id == recipe_id, Recipe.user_id == user.id))
    if record is None:
        raise HTTPException(status_code=404, detail="Рецепт не найден.")
    exclusions = user.profile.exclusions if user.profile else []
    check = check_ingredients([item["name"] if isinstance(item, dict) else item for item in record.ingredients], exclusions)
    if not check.allowed:
        raise HTTPException(status_code=422, detail="Рецепт не прошёл повторную проверку и не сохранён.")
    record.is_saved = True
    db.commit()
    db.refresh(record)
    return recipe_response(record, record.rating)


@app.get("/api/recipes/{recipe_id}", response_model=RecipeResponse)
async def get_recipe(
    recipe_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> RecipeResponse:
    record = db.scalar(select(Recipe).where(Recipe.id == recipe_id, Recipe.user_id == user.id))
    if record is None:
        raise HTTPException(status_code=404, detail="Рецепт не найден.")
    exclusions = user.profile.exclusions if user.profile else []
    check = check_ingredients([item["name"] if isinstance(item, dict) else item for item in record.ingredients], exclusions)
    if not check.allowed:
        raise HTTPException(status_code=422, detail="Сохранённый рецепт не прошёл повторную проверку.")
    return recipe_response(record, record.rating)


@app.delete("/api/recipes/{recipe_id}", status_code=204)
async def delete_recipe(
    recipe_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> None:
    record = db.scalar(select(Recipe).where(Recipe.id == recipe_id, Recipe.user_id == user.id))
    if record is None:
        raise HTTPException(status_code=404, detail="Рецепт не найден.")
    db.delete(record)
    db.commit()


@app.put("/api/recipes/{recipe_id}/rating", response_model=RecipeResponse)
async def rate_recipe(
    recipe_id: int,
    rating: RatingRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> RecipeResponse:
    record = db.scalar(select(Recipe).where(Recipe.id == recipe_id, Recipe.user_id == user.id))
    if record is None:
        raise HTTPException(status_code=404, detail="Рецепт не найден.")
    provided_feedback = rating.model_dump(exclude_unset=True)
    if not provided_feedback or all(
        value is None or (key == "review" and not value.strip())
        for key, value in provided_feedback.items()
    ):
        raise HTTPException(status_code=422, detail="Укажите оценку, соответствие рецепта или отзыв.")
    if record.rating is None:
        db.add(RecipeRating(
            user_id=user.id,
            recipe_id=record.id,
            suitable=rating.suitable,
            liked=rating.liked,
            review=rating.review.strip() if rating.review else None,
        ))
    else:
        if "suitable" in provided_feedback:
            record.rating.suitable = rating.suitable
        if "liked" in provided_feedback:
            record.rating.liked = rating.liked
        if "review" in provided_feedback:
            record.rating.review = rating.review.strip() if rating.review else None
        record.rating.created_at = utc_now()
    db.commit()
    db.refresh(record)
    return recipe_response(record, record.rating)
