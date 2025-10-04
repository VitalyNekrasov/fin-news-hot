# syntax=docker/dockerfile:1
FROM node:20-alpine AS build
WORKDIR /app
ARG VITE_API_URL=http://backend:8000
ENV VITE_API_URL=$VITE_API_URL
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ARG VITE_API_URL=http://backend:8000
ENV VITE_API_URL=$VITE_API_URL
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package*.json ./
COPY --from=build /app/dist ./dist
EXPOSE 4173
CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0", "--port", "4173"]
