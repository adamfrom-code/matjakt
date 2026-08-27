from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RecipeIngredient:
    name: str
    measure: str | None = None


@dataclass(frozen=True)
class Recipe:
    id: str
    provider: str
    provider_recipe_id: str
    title: str
    image_url: str | None
    image_source: str | None
    servings: int | None
    prep_minutes: int | None
    ingredients: list[RecipeIngredient]
    instructions: list[str]

    def to_dict(self):
        value = asdict(self)
        return {
            "id": value["id"],
            "provider": value["provider"],
            "providerRecipeId": value["provider_recipe_id"],
            "title": value["title"],
            "imageUrl": value["image_url"],
            "imageSource": value["image_source"],
            "servings": value["servings"],
            "prepMinutes": value["prep_minutes"],
            "ingredients": value["ingredients"],
            "instructions": value["instructions"],
        }
