FROM node:24-slim AS build
WORKDIR /repo/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
COPY assets/brand /repo/assets/brand
ARG DGIS_API_KEY=""
RUN printf 'DGIS_API_KEY=%s\n' "$DGIS_API_KEY" > /repo/.env && npx vite build

FROM nginx:1.27-alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /repo/frontend/dist /usr/share/nginx/html
