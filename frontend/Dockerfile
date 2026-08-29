# Research Agent frontend — React + TypeScript + Vite (dev server)
FROM node:22-alpine

WORKDIR /app

# Install dependencies first for better layer caching.
COPY package.json package-lock.json ./
RUN npm ci

# Copy the rest of the source.
COPY . .

EXPOSE 5173

# Expose the dev server to the container network so it's reachable from
# the host at http://localhost:5173.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
