FROM nginx:alpine

# Copy static files
COPY index.html /usr/share/nginx/html/index.html

# Copy nginx config template
COPY nginx.conf /etc/nginx/templates/default.conf.template

# Railway sets PORT; nginx template substitution uses envsubst
# BACKEND_HOST and BACKEND_PORT are set via Railway service variables
ENV BACKEND_HOST=diamondclaws-backend.railway.internal
ENV BACKEND_PORT=8000

EXPOSE 80
