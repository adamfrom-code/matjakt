import { request } from "./http.js";

// Varje anrop härifrån går genom request() i http.js: tidsgräns på 15 s och
// ett svenskt felmeddelande. Ropa aldrig fetch direkt här - då tappar just
// det anropet båda delarna (E6, E7). tests/http.test.js vaktar regeln.

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

export function register(email, password, marketing = false) {
  return request("/auth/register", { method: "POST", body: { email, password, marketing: Boolean(marketing) } });
}

// Tacka ja/nej till utskick. Servern äger svaret; UI:t ritar om från `user`.
export function setMarketingConsent(token, consent) {
  return request("/account/marketing", { method: "POST", token, body: { consent: Boolean(consent) } });
}

export function login(email, password) {
  return request("/auth/login", { method: "POST", body: { email, password } });
}

export function logout(token, deviceToken = null) {
  // deviceToken följer med så servern kan glömma just DEN här enheten:
  // annars fortsätter det utloggade kontots hushållsnotiser till en telefon
  // som nu tillhör någon annan.
  return request("/auth/logout", { method: "POST", token, body: deviceToken ? { deviceToken } : {} });
}

export function fetchCurrentUser(token) {
  return request("/auth/me", { token });
}

export function redeemPremium(token, code) {
  return request("/auth/redeem", { method: "POST", token, body: { code } });
}

// withdrawalConsent är kundens uttryckliga godkännande av att Premium
// levereras direkt och att ångerrätten därmed upphör (distansavtalslagen).
// Servern sparar det med tidsstämpel och vägrar skapa en Checkout utan det.
export function startCheckout(token, plan, withdrawalConsent = false) {
  return request("/billing/checkout", { method: "POST", token, body: { plan, withdrawalConsent: Boolean(withdrawalConsent) } });
}

export function openBillingPortal(token) {
  return request("/billing/portal", { method: "POST", token });
}

export function changePassword(token, currentPassword, newPassword) {
  return request("/auth/change-password", { method: "POST", token, body: { currentPassword, newPassword } });
}

export function requestPasswordReset(email) {
  return request("/auth/request-password-reset", { method: "POST", body: { email } });
}

export function resetPassword(token, password) {
  return request("/auth/reset-password", { method: "POST", body: { token, password } });
}

export function verifyEmail(token) {
  return request("/auth/verify-email", { method: "POST", body: { token } });
}

export function resendVerification(token) {
  return request("/auth/resend-verification", { method: "POST", token });
}

export function deleteAccount(token) {
  return request("/auth/delete-account", { method: "POST", token });
}

export function fetchAccountState(token) {
  return request("/account/state", { token });
}

export function saveAccountState(token, stateBlob, { keepalive = false } = {}) {
  // keepalive: anropet får överleva att sidan stängs/lämnas (pagehide), och
  // får därför ingen tidsgräns - se request().
  return request("/account/state", { method: "POST", token, body: stateBlob, keepalive });
}
