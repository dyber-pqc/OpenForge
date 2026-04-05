FROM node:20-alpine AS build

WORKDIR /app
COPY packages/web/package.json packages/web/package-lock.json* ./
RUN npm ci

COPY packages/web/ .
RUN npm run build

FROM node:20-alpine AS runtime

LABEL maintainer="Dyber Inc. <engineering@dyber.io>"
LABEL description="OpenForge EDA web frontend"

WORKDIR /app

RUN npm install -g serve

COPY --from=build /app/build ./build

EXPOSE 3000

CMD ["serve", "-s", "build", "-l", "3000"]
