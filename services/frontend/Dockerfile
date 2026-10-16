FROM node:24-slim
WORKDIR /app
COPY package.json .
RUN npm install --omit=dev
COPY server.js .
EXPOSE 8080
# Zero-code instrumentation: the register hook starts the SDK before the app loads.
CMD ["node", "--require", "@opentelemetry/auto-instrumentations-node/register", "server.js"]
