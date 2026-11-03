# syntax=docker/dockerfile:1
# Сборка React-приложения и раздача статики через Nginx.

FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# В Docker браузер обращается к тому же origin, а Nginx проксирует /api.
ARG VITE_API_BASE_URL=/api
ARG VITE_MODEL_ID=qwen3-8b-vet
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_MODEL_ID=$VITE_MODEL_ID

RUN npm run build

FROM nginx:stable-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q --spider http://127.0.0.1/healthz || exit 1

CMD ["nginx", "-g", "daemon off;"]
