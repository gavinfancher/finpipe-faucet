export function getCurrentUsername(): string | null {
  return localStorage.getItem("tsapp_current_user");
}

export function setCurrentUsername(username: string): void {
  localStorage.setItem("tsapp_current_user", username);
}

export function clearCurrentUsername(): void {
  localStorage.removeItem("tsapp_current_user");
}
