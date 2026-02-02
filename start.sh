#!/bin/bash

# Initialize database (runs once before workers start)
echo "Running database initialization..."
python -c "from database import init_db; init_db()"

# Start the application
echo "Starting application on port ${PORT:-8080}..."
exec gunicorn -w 4 -b 0.0.0.0:${PORT:-8080} app:app
