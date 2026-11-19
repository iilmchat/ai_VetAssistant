/* eslint-env serviceworker */
/* Service Worker базовой PWA-оболочки VetAssistant (T-176).

Кэшируем только статику приложения. Запросы к API (/api, /v1) и любые
кросс-Origin-запросы не кэшируются: данные пациентов и ответы LLM должны
всегда приходить с сервера. Расширенный офлайн-режим чата — T-185.
*/

const CACHE_NAME = 'vetassistant-shell-v1'

const APP_SHELL = [
  '/',
  '/index.html',
  '/favicon.svg',
  '/manifest.webmanifest',
  '/pwa-192.png',
  '/pwa-512.png',
  '/apple-touch-icon.png',
]

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.method !== 'GET') {
    return
  }

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) {
    return
  }
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/v1/')) {
    return
  }

  // Навигация: всегда пробуем сеть, при отсутствии — показываем оболочку.
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => caches.match('/index.html')))
    return
  }

  // Статика: кэш с догрузкой из сети и сохранением успешных ответов.
  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) {
        return cached
      }
      return fetch(request).then((response) => {
        if (response.ok) {
          const copy = response.clone()
          caches.open(CACHE_NAME).then((cache) => cache.put(request, copy))
        }
        return response
      })
    }),
  )
})
