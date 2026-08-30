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

export function startCheckout(token, plan) {
  return fetch(`${API_BASE_URL}/billing/checkout`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ plan }),
  }).then(parseJsonResponse);
}

export function openBillingPortal(token) {
  return fetch(`${API_BASE_URL}/billing/portal`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  }).then(parseJsonResponse);
}

export function requestPasswordReset(email) {
  return fetch(`${API_BASE_URL}/auth/request-password-reset`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  }).then(parseJsonResponse);
}

export function resetPassword(token, password) {
  return fetch(`${API_BASE_URL}/auth/reset-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, password }),
  }).then(parseJsonResponse);
}

export function verifyEmail(token) {
  return fetch(`${API_BASE_URL}/auth/verify-email`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  }).then(parseJsonResponse);
}

export function resendVerification(token) {
  return fetch(`${API_BASE_URL}/auth/resend-verification`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  }).then(parseJsonResponse);
}

export function deleteAccount(token) {
  return fetch(`${API_BASE_URL}/auth/delete-account`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  }).then(parseJsonResponse);
}

export function fetchAccountState(token) {
  return fetch(`${API_BASE_URL}/account/state`, {
    headers: { Authorization: `Bearer ${token}` },
  }).then(parseJsonResponse);
}

export function saveAccountState(token, stateBlob) {
  return fetch(`${API_BASE_URL}/account/state`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(stateBlob),
  }).then(parseJsonResponse);
}
