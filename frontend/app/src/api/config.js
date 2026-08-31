const configuredUrl = document.querySelector('meta[name="matjakt-api-url"]')?.content?.trim();
export const API_BASE_URL = (configuredUrl || "/api").replace(/\/$/, "");

export function productApiUrl(store, query, postcode, storeKey) {
  const params = new URLSearchParams({ butik: store, q: query, zip: postcode });
  if (storeKey) params.set("butiksnyckel", storeKey);
  return `${API_BASE_URL}/products?${params}`;
}

export function productsBatchApiUrl() {
  return `${API_BASE_URL}/products/batch`;
}

export function pricingWeekApiUrl() {
  return `${API_BASE_URL}/pricing/week`;
}

export function pricingListApiUrl() {
  return `${API_BASE_URL}/pricing/list`;
}

export function groceryStatusApiUrl() {
  return `${API_BASE_URL}/grocery/status`;
}

export function geocodeApiUrl(zip) {
  return `${API_BASE_URL}/geocode?${new URLSearchParams({ zip })}`;
}

export function campaignsApiUrl(chain, zip) {
  return `${API_BASE_URL}/campaigns?${new URLSearchParams({ butik: chain, zip })}`;
}

export function storesApiUrl(zip) {
  return `${API_BASE_URL}/stores?${new URLSearchParams({ zip })}`;
}

export function recipesByPantryApiUrl(items) {
  return `${API_BASE_URL}/v1/recipes/by-pantry?${new URLSearchParams({ items: items.join(",") })}`;
}

export function recipeSearchApiUrl(query) {
  return `${API_BASE_URL}/v1/recipes/search?${new URLSearchParams({ q: query })}`;
}

export function recipeDetailApiUrl(recipeId) {
  return `${API_BASE_URL}/v1/recipes/${encodeURIComponent(recipeId)}`;
}
