from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_salt: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    profile: Mapped["Profile"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    sessions: Mapped[list["LoginSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    recipes: Mapped[list["Recipe"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    usage_events: Mapped[list["UsageEvent"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Profile(Base):
    __tablename__ = "profiles"
    __table_args__ = (UniqueConstraint("user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    user: Mapped[User] = relationship(back_populates="profile")
    settings: Mapped[list["ProfileSetting"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="(ProfileSetting.kind, ProfileSetting.position)",
    )

    @property
    def preferences(self) -> list[str]:
        return self._settings_for("preference")

    @preferences.setter
    def preferences(self, values: list[str]) -> None:
        self._replace_settings("preference", values)

    @property
    def exclusions(self) -> list[str]:
        return self._settings_for("exclusion")

    @exclusions.setter
    def exclusions(self, values: list[str]) -> None:
        self._replace_settings("exclusion", values)

    def _settings_for(self, kind: str) -> list[str]:
        return [item.value for item in self.settings if item.kind == kind]

    def _replace_settings(self, kind: str, values: list[str]) -> None:
        retained = [item for item in self.settings if item.kind != kind]
        replacements = [
            ProfileSetting(kind=kind, position=position, value=value)
            for position, value in enumerate(values)
        ]
        self.settings = retained + replacements


class ProfileSetting(Base):
    __tablename__ = "profile_settings"
    __table_args__ = (
        CheckConstraint("kind IN ('preference', 'exclusion')", name="ck_profile_setting_kind"),
    )

    profile_id: Mapped[int] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(20), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[str] = mapped_column(String(100))

    profile: Mapped[Profile] = relationship(back_populates="settings")


class LoginSession(Base):
    __tablename__ = "login_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    user: Mapped[User] = relationship(back_populates="sessions")


class Recipe(Base):
    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(30))
    is_saved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    preparation_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    user: Mapped[User] = relationship(back_populates="recipes")
    rating: Mapped["RecipeRating"] = relationship(
        back_populates="recipe", cascade="all, delete-orphan", uselist=False
    )
    input_product_rows: Mapped[list["RecipeInputProduct"]] = relationship(
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="RecipeInputProduct.position",
    )
    ingredient_rows: Mapped[list["RecipeIngredientRow"]] = relationship(
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="RecipeIngredientRow.position",
    )
    step_rows: Mapped[list["RecipeStepRow"]] = relationship(
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="RecipeStepRow.position",
    )
    missing_product_rows: Mapped[list["RecipeMissingProduct"]] = relationship(
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="RecipeMissingProduct.position",
    )

    @property
    def input_products(self) -> list[str]:
        return [item.name for item in self.input_product_rows]

    @input_products.setter
    def input_products(self, values: list[str]) -> None:
        self.input_product_rows = [
            RecipeInputProduct(position=position, name=value)
            for position, value in enumerate(values)
        ]

    @property
    def ingredients(self) -> list[dict[str, str | None]]:
        return [
            {"name": item.name, "quantity": item.quantity}
            for item in self.ingredient_rows
        ]

    @ingredients.setter
    def ingredients(self, values: list[dict | str]) -> None:
        rows = []
        for position, item in enumerate(values):
            if isinstance(item, dict):
                name, quantity = item.get("name", ""), item.get("quantity")
            else:
                name, quantity = str(item), None
            rows.append(RecipeIngredientRow(position=position, name=name, quantity=quantity))
        self.ingredient_rows = rows

    @property
    def steps(self) -> list[dict[str, str | int | None]]:
        return [
            {"instruction": item.instruction, "duration_minutes": item.duration_minutes}
            for item in self.step_rows
        ]

    @steps.setter
    def steps(self, values: list[dict | str]) -> None:
        rows = []
        for position, item in enumerate(values):
            if isinstance(item, dict):
                instruction = item.get("instruction", "")
                duration = item.get("duration_minutes")
            else:
                instruction, duration = str(item), None
            rows.append(
                RecipeStepRow(
                    position=position,
                    instruction=instruction,
                    duration_minutes=duration,
                )
            )
        self.step_rows = rows

    @property
    def missing_products(self) -> list[str]:
        return [item.name for item in self.missing_product_rows]

    @missing_products.setter
    def missing_products(self, values: list[str]) -> None:
        self.missing_product_rows = [
            RecipeMissingProduct(position=position, name=value)
            for position, value in enumerate(values)
        ]


class RecipeInputProduct(Base):
    __tablename__ = "recipe_input_products"

    recipe_id: Mapped[int] = mapped_column(
        ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))

    recipe: Mapped[Recipe] = relationship(back_populates="input_product_rows")


class RecipeIngredientRow(Base):
    __tablename__ = "recipe_ingredients"

    recipe_id: Mapped[int] = mapped_column(
        ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[str | None] = mapped_column(String(40), nullable=True)

    recipe: Mapped[Recipe] = relationship(back_populates="ingredient_rows")


class RecipeStepRow(Base):
    __tablename__ = "recipe_steps"

    recipe_id: Mapped[int] = mapped_column(
        ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    instruction: Mapped[str] = mapped_column(String(500))
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    recipe: Mapped[Recipe] = relationship(back_populates="step_rows")


class RecipeMissingProduct(Base):
    __tablename__ = "recipe_missing_products"

    recipe_id: Mapped[int] = mapped_column(
        ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))

    recipe: Mapped[Recipe] = relationship(back_populates="missing_product_rows")


class RecipeRating(Base):
    __tablename__ = "recipe_ratings"
    __table_args__ = (UniqueConstraint("user_id", "recipe_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"), index=True)
    suitable: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    recipe: Mapped[Recipe] = relationship(back_populates="rating")


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(30), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    user: Mapped[User] = relationship(back_populates="usage_events")
