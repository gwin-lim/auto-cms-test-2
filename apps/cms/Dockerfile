FROM node:20.18-bookworm

WORKDIR /opt/app

# Copy package files and install dependencies
COPY package.json ./
RUN npm install

# Copy source
COPY . .

# Build the Strapi admin panel
RUN npm run build

ENV PATH /opt/app/node_modules/.bin:$PATH
ENV NODE_ENV=development

EXPOSE $PORT

CMD ["npm", "run", "develop"]
