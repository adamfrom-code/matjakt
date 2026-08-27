const configuredUrl = document.querySelector('meta[name="matjakt-api-url"]')?.content?.trim();
export const API_BASE_URL = (configuredUrl || "/api").replace(/\/$/, "");

export function productApiUrl(store, query, postcode) {
  const params = new URLSearchParams({ butik: store, q: query, zip: postcode });
  return `${API_BASE_URL}/products?${params}`;
}

export function recipeSearchApiUrl(query) {
  return `${API_BASE_URL}/v1/recipes/search?${new URLSearchParams({ q: query })}`;
}

export function recipeDetailApiUrl(recipeId) {
  return `${API_BASE_URL}/v1/recipes/${encodeURIComponent(recipeId)}`;
}
