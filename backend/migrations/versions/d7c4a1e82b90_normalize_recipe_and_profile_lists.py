"""Normalize profile settings and recipe lists into relational tables.

Revision ID: d7c4a1e82b90
Revises: c4b92e6f78ad
"""
import json

from alembic import op
import sqlalchemy as sa


revision = "d7c4a1e82b90"
down_revision = "c4b92e6f78ad"
branch_labels = None
depends_on = None


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, list) else []


def _named_value(value):
    if isinstance(value, dict):
        return str(value.get("name", "")), value.get("quantity")
    return str(value), None


def _step_value(value):
    if isinstance(value, dict):
        return str(value.get("instruction", "")), value.get("duration_minutes")
    return str(value), None


def upgrade() -> None:
    op.create_table(
        "profile_settings",
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("value", sa.String(length=100), nullable=False),
        sa.CheckConstraint("kind IN ('preference', 'exclusion')", name="ck_profile_setting_kind"),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("profile_id", "kind", "position"),
    )
    op.create_table(
        "recipe_input_products",
        sa.Column("recipe_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("recipe_id", "position"),
    )
    op.create_table(
        "recipe_ingredients",
        sa.Column("recipe_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("quantity", sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("recipe_id", "position"),
    )
    op.create_table(
        "recipe_steps",
        sa.Column("recipe_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("instruction", sa.String(length=500), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("recipe_id", "position"),
    )
    op.create_table(
        "recipe_missing_products",
        sa.Column("recipe_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("recipe_id", "position"),
    )

    connection = op.get_bind()
    profiles = sa.table(
        "profiles",
        sa.column("id", sa.Integer()),
        sa.column("preferences", sa.JSON()),
        sa.column("exclusions", sa.JSON()),
    )
    settings = sa.table(
        "profile_settings",
        sa.column("profile_id", sa.Integer()),
        sa.column("kind", sa.String()),
        sa.column("position", sa.Integer()),
        sa.column("value", sa.String()),
    )
    for profile in connection.execute(sa.select(profiles)).mappings():
        rows = []
        for kind, column in (("preference", "preferences"), ("exclusion", "exclusions")):
            rows.extend(
                {"profile_id": profile["id"], "kind": kind, "position": position, "value": str(value)}
                for position, value in enumerate(_as_list(profile[column]))
            )
        if rows:
            connection.execute(settings.insert(), rows)

    recipes = sa.table(
        "recipes",
        sa.column("id", sa.Integer()),
        sa.column("input_products", sa.JSON()),
        sa.column("ingredients", sa.JSON()),
        sa.column("steps", sa.JSON()),
        sa.column("missing_products", sa.JSON()),
    )
    inputs = sa.table("recipe_input_products", sa.column("recipe_id", sa.Integer()), sa.column("position", sa.Integer()), sa.column("name", sa.String()))
    ingredients = sa.table("recipe_ingredients", sa.column("recipe_id", sa.Integer()), sa.column("position", sa.Integer()), sa.column("name", sa.String()), sa.column("quantity", sa.String()))
    steps = sa.table("recipe_steps", sa.column("recipe_id", sa.Integer()), sa.column("position", sa.Integer()), sa.column("instruction", sa.String()), sa.column("duration_minutes", sa.Integer()))
    missing = sa.table("recipe_missing_products", sa.column("recipe_id", sa.Integer()), sa.column("position", sa.Integer()), sa.column("name", sa.String()))

    for recipe in connection.execute(sa.select(recipes)).mappings():
        recipe_id = recipe["id"]
        input_rows = [{"recipe_id": recipe_id, "position": i, "name": str(value)} for i, value in enumerate(_as_list(recipe["input_products"]))]
        ingredient_rows = []
        for i, value in enumerate(_as_list(recipe["ingredients"])):
            name, quantity = _named_value(value)
            ingredient_rows.append({"recipe_id": recipe_id, "position": i, "name": name, "quantity": quantity})
        step_rows = []
        for i, value in enumerate(_as_list(recipe["steps"])):
            instruction, duration = _step_value(value)
            step_rows.append({"recipe_id": recipe_id, "position": i, "instruction": instruction, "duration_minutes": duration})
        missing_rows = [{"recipe_id": recipe_id, "position": i, "name": str(value)} for i, value in enumerate(_as_list(recipe["missing_products"]))]
        for table, rows in ((inputs, input_rows), (ingredients, ingredient_rows), (steps, step_rows), (missing, missing_rows)):
            if rows:
                connection.execute(table.insert(), rows)

    with op.batch_alter_table("profiles") as batch:
        batch.drop_column("preferences")
        batch.drop_column("exclusions")
    with op.batch_alter_table("recipes") as batch:
        batch.drop_column("input_products")
        batch.drop_column("ingredients")
        batch.drop_column("steps")
        batch.drop_column("missing_products")


def downgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.add_column(sa.Column("preferences", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column("exclusions", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    with op.batch_alter_table("recipes") as batch:
        batch.add_column(sa.Column("input_products", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column("ingredients", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column("steps", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column("missing_products", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))

    connection = op.get_bind()
    profiles = sa.table(
        "profiles",
        sa.column("id", sa.Integer()),
        sa.column("preferences", sa.JSON()),
        sa.column("exclusions", sa.JSON()),
    )
    for kind in ("preference", "exclusion"):
        rows = connection.execute(sa.text("SELECT profile_id, kind, position, value FROM profile_settings WHERE kind = :kind ORDER BY profile_id, position"), {"kind": kind})
        grouped = {}
        for row in rows:
            grouped.setdefault(row.profile_id, []).append(row.value)
        for profile_id, values in grouped.items():
            column = "preferences" if kind == "preference" else "exclusions"
            connection.execute(profiles.update().where(profiles.c.id == profile_id).values({column: values}))

    for table_name, field, serialize in (
        ("recipe_input_products", "input_products", lambda row: row.name),
        ("recipe_ingredients", "ingredients", lambda row: {"name": row.name, "quantity": row.quantity}),
        ("recipe_steps", "steps", lambda row: {"instruction": row.instruction, "duration_minutes": row.duration_minutes}),
        ("recipe_missing_products", "missing_products", lambda row: row.name),
    ):
        rows = connection.execute(sa.text(f"SELECT * FROM {table_name} ORDER BY recipe_id, position"))
        grouped = {}
        for row in rows:
            grouped.setdefault(row.recipe_id, []).append(serialize(row))
        recipes = sa.table("recipes", sa.column("id", sa.Integer()), sa.column(field, sa.JSON()))
        for recipe_id, values in grouped.items():
            connection.execute(recipes.update().where(recipes.c.id == recipe_id).values({field: values}))

    for table in ("recipe_missing_products", "recipe_steps", "recipe_ingredients", "recipe_input_products", "profile_settings"):
        op.drop_table(table)
