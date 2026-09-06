# Build context is the repository root so this image could pick up shared
# assets later; only services/ingestion is copied today.
FROM node:22-alpine AS build

WORKDIR /app
COPY services/ingestion/package.json services/ingestion/package-lock.json ./
# `ci`, not `install`: it installs exactly the lockfile and fails if the two
# have drifted, so an image is reproducible rather than "whatever resolved
# today".
RUN npm ci

COPY services/ingestion/tsconfig.json services/ingestion/tsconfig.build.json ./
COPY services/ingestion/src ./src
RUN npm run build

FROM node:22-alpine AS runtime

ENV NODE_ENV=production
WORKDIR /app

COPY services/ingestion/package.json services/ingestion/package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

COPY --from=build /app/dist ./dist

USER node
EXPOSE 3000
CMD ["node", "dist/server.js"]
