# ---- Build-Stage: Vite/React bundlen ----
FROM node:20-alpine AS build
WORKDIR /app

# Nur was für den Install nötig ist, zuerst kopieren (Cache-freundlich)
COPY package*.json ./
RUN npm ci

# Rest des Codes
COPY . .

# Optional: Wenn du Build-ENV überschreiben willst, setz sie hier
# ENV VITE_RABBIT_WS=ws://rabbitmq:15674/ws
# ENV VITE_RABBIT_MGMT=http://rabbitmq:15672

# Build
RUN npm run build

# ---- Run-Stage: statisch via Nginx serven ----
FROM nginx:alpine
# SPA-Config: 404 -> index.html (damit Vite-Routes funktionieren)
RUN printf 'server {\n\
  listen 80;\n\
  server_name _;\n\
  root /usr/share/nginx/html;\n\
  include /etc/nginx/mime.types;\n\
  location / {\n\
    try_files $uri /index.html;\n\
  }\n\
}\n' > /etc/nginx/conf.d/default.conf

# Build-Output reinkopieren
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
