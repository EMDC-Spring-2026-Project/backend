# # Use an official Python runtime as a parent image
# FROM python:3.8

# # Set the working directory in the container
# WORKDIR /backend

# Install dependencies
# RUN pip install --upgrade pip
# RUN pip install django
# RUN pip install mysqlclient
# RUN pip install django-autoreload
# RUN pip install python-dotenv
# RUN pip install django-cors-headers
# RUN pip install djangorestframework

# # Copy the backend code into the container at /backend
# COPY /emdcbackend/ /backend/

# # Expose port 7012 to allow external access
# EXPOSE 7004

# # Run the Django application with auto-reload
# CMD ["sh", "-c", "python manage.py migrate && python manage.py runserver 0.0.0.0:7004"]

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps for psycopg
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

# Workdir is where manage.py will be
WORKDIR /backend

#Allows for the use of breakpoints with VS Code
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir debugpy

# Install deps early to leverage layer caching
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy source code
COPY emdcbackend /backend

# Copy admin creation script
COPY scripts/create_admin.sh /create_admin.sh
RUN chmod +x /create_admin.sh

# Create entrypoint script for migrations and optional admin creation
RUN echo '#!/bin/bash' > /entrypoint.sh && \
    echo 'set -e' >> /entrypoint.sh && \
    echo 'echo "Waiting for database..."' >> /entrypoint.sh && \
    echo 'python manage.py migrate --noinput' >> /entrypoint.sh && \
    echo 'python manage.py migrate auth --noinput' >> /entrypoint.sh && \
    echo 'python manage.py migrate emdcbackend --noinput' >> /entrypoint.sh && \
    echo '' >> /entrypoint.sh && \
    echo '# Create admin account if environment variables are set' >> /entrypoint.sh && \
    echo 'if [ -n "$CREATE_ADMIN_USERNAME" ] && [ -n "$CREATE_ADMIN_PASSWORD" ]; then' >> /entrypoint.sh && \
    echo '  echo "Creating admin account from environment variables..."' >> /entrypoint.sh && \
    echo '  python manage.py create_first_admin \' >> /entrypoint.sh && \
    echo '    --username "$CREATE_ADMIN_USERNAME" \' >> /entrypoint.sh && \
    echo '    --password "$CREATE_ADMIN_PASSWORD" \' >> /entrypoint.sh && \
    echo '    --first-name "${CREATE_ADMIN_FIRST_NAME:-Admin}" \' >> /entrypoint.sh && \
    echo '    --last-name "${CREATE_ADMIN_LAST_NAME:-User}" || true' >> /entrypoint.sh && \
    echo 'fi' >> /entrypoint.sh && \
    echo '' >> /entrypoint.sh && \
    echo 'echo "Starting Django server..."' >> /entrypoint.sh && \
    echo 'exec "$@"' >> /entrypoint.sh && \
    chmod +x /entrypoint.sh

EXPOSE 7004

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "manage.py", "runserver", "0.0.0.0:7004"]
