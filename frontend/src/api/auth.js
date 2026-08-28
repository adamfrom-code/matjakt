import { API_BASE_URL } from "./config.js";

export const AUTH_TOKEN_KEY = "matjakt-auth-token";

export function getStoredToken(storage = localStorage) {
  try {
    return storage.getItem(AUTH_TOKEN_KEY) || null;
  } catch {
    return null;
  }
}

export function storeToken(token, storage = localStorage) {
  try {
    if (token) storage.setItem(AUTH_TOKEN_KEY, token);
    else storage.removeItem(AUTH_TOKEN_KEY);
  } catch { /* localStorage unavailable (private mode, quota) - session stays in-memory only */ }
}

async function parseJsonResponse(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

export function register(email, password) {
  return fetch(`${API_BASE_URL}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  }).then(parseJsonResponse);
}

export function login(email, password) {
  return fetch(`${API_BASE_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  }).then(parseJsonResponse);
}

export function logout(token) {
  return fetch(`${API_BASE_URL}/auth/logout`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  }).then(parseJsonResponse);
}

export function fetchCurrentUser(token) {
  return fetch(`${API_BASE_URL}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  }).then(parseJsonResponse);
}

export function redeemPremium(token, code) {
  return fetch(`${API_BASE_URL}/auth/redeem`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ code }),
  }).then(parseJsonResponse);
}

export function startTrial(token) {
  return fetch(`${API_BASE_URL}/auth/start-trial`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  }).then(parseJsonResponse);
}
