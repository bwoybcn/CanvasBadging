# SPDX-License-Identifier: AGPL-3.0-or-later
# Build context: repo root.
FROM node:25-alpine AS build
WORKDIR /src
COPY signer/package.json signer/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY signer/ ./
RUN npm run build && npm prune --omit=dev

FROM node:25-alpine
ENV NODE_ENV=production
WORKDIR /app
COPY --from=build /src/node_modules ./node_modules
COPY --from=build /src/dist ./dist
COPY signer/package.json ./
USER node
EXPOSE 8790
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD wget -qO- http://127.0.0.1:8790/healthz >/dev/null || exit 1
CMD ["node", "dist/server.js"]
