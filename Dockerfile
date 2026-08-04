FROM node:24.12.0-alpine

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build
EXPOSE 3000
# `next start` já escuta em 0.0.0.0; --host não é flag do Next (seria -H).
CMD ["npm", "run", "start"]
