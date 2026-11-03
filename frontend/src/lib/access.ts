/** URL-параметр, который открывает форму заявки на доступ. */
export function isAccessRequestMode(search: string): boolean {
  return new URLSearchParams(search).get('mode') === 'request'
}
