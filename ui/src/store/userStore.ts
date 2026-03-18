export function getCurrentUsername(): string | null {
  return localStorage.getItem("tsapp_current_user");
}

export function setCurrentUsername(username: string): void {
  localStorage.setItem("tsapp_current_user", username);
}

export function clearCurrentUsername(): void {
  localStorage.removeItem("tsapp_current_user");
}

export function getToken(): string | null {
  return localStorage.getItem("tsapp_token");
}

export function setToken(token: string): void {
  localStorage.setItem("tsapp_token", token);
}

export function clearToken(): void {
  localStorage.removeItem("tsapp_token");
}
