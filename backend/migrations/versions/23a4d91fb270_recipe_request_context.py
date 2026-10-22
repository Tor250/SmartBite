"""Сохраняет параметры приготовления и связь между версиями рецепта."""
from alembic import op
import sqlalchemy as sa


revision = "23a4d91fb270"
down_revision = "8e91c4a0d6f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recipes", sa.Column("requested_difficulty", sa.Integer(), nullable=True))
    op.add_column("recipes", sa.Column("request_context", sa.String(length=1000), nullable=True))
    op.add_column("recipes", sa.Column("parent_recipe_id", sa.Integer(), nullable=True))
    op.create_index("ix_recipes_parent_recipe_id", "recipes", ["parent_recipe_id"])
    with op.batch_alter_table("recipes") as batch_op:
        batch_op.create_foreign_key(
            "fk_recipes_parent_recipe_id_recipes",
            "recipes",
            ["parent_recipe_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_table(
        "recipe_equipment",
        sa.Column("recipe_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("recipe_id", "position"),
    )


def downgrade() -> None:
    op.drop_table("recipe_equipment")
    with op.batch_alter_table("recipes") as batch_op:
        batch_op.drop_constraint("fk_recipes_parent_recipe_id_recipes", type_="foreignkey")
    op.drop_index("ix_recipes_parent_recipe_id", table_name="recipes")
    op.drop_column("recipes", "parent_recipe_id")
    op.drop_column("recipes", "request_context")
    op.drop_column("recipes", "requested_difficulty")
