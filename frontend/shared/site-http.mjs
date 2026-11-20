export function csrfToken() {
  return document.querySelector('meta[name="csrf-token"]')?.content
    || document.querySelector('input[name="csrf_token"]')?.value || '';
}

export async function legacyAjax(url, options) {
  const response = await fetch(url, options);
  if (response.status === 403) {
    location.reload();
    throw new Error('CSRF token expired');
  }
  return response;
}
