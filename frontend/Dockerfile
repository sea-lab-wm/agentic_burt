FROM node:22-alpine AS frontend-build

WORKDIR /frontend

COPY package.json package-lock.json ./
RUN npm ci

COPY . ./
RUN npm run build

#NOTE: the final container image ran as a container is the final stage below 
FROM nginx:1.27-alpine

COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-build /frontend/dist /usr/share/nginx/html
