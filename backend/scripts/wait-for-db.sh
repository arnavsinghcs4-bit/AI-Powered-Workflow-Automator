#!/bin/bash
# Wait for Supabase and Redis to be reachable before starting services.
# Do NOT run migrations automatically.

DB_URL="${SUPABASE_POOLED_URL}"
REDIS_URL="${REDIS_URL}"

# Extract host and port from SUPABASE_POOLED_URL (assumes postgresql://user:pass@host:port/db)
DB_HOST=$(echo "$DB_URL" | sed -n 's/.*@\([^:]*\).*/\1/p')
DB_PORT=$(echo "$DB_URL" | sed -n 's/.*:\([0-9]*\)\/.*$/\1/p')
if [ -z "$DB_PORT" ]; then DB_PORT=6543; fi

REDIS_HOST=$(echo "$REDIS_URL" | sed -n 's/.*:\/\/\([^:]*\).*/\1/p')
REDIS_PORT=$(echo "$REDIS_URL" | sed -n 's/.*:\([0-9]*\)$/\1/p')
if [ -z "$REDIS_PORT" ]; then REDIS_PORT=6379; fi

echo "Waiting for DB at $DB_HOST:$DB_PORT..."
until nc -z "$DB_HOST" "$DB_PORT" 2>/dev/null; do
  sleep 1
done
echo "DB is reachable."

echo "Waiting for Redis at $REDIS_HOST:$REDIS_PORT..."
until nc -z "$REDIS_HOST" "$REDIS_PORT" 2>/dev/null; do
  sleep 1
done
echo "Redis is reachable."

echo "All services ready."
