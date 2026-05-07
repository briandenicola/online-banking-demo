FROM nginx:alpine

RUN apk add --no-cache nginx-module-njs

COPY jwt_validate.js /etc/nginx/njs/jwt_validate.js
COPY nginx.conf /etc/nginx/nginx.conf
