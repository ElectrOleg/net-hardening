#!/bin/bash
set -e

# ── Wait for PostgreSQL ──────────────────────────────────────────
wait_for_db() {
    echo "Waiting for PostgreSQL at ${DATABASE_URL}..."
    local retries=30
    while [ $retries -gt 0 ]; do
        if python -c "
import sqlalchemy
engine = sqlalchemy.create_engine('${DATABASE_URL}')
engine.connect().close()
" 2>/dev/null; then
            echo "PostgreSQL is ready."
            return 0
        fi
        retries=$((retries - 1))
        echo "  ...waiting (${retries} retries left)"
        sleep 2
    done
    echo "ERROR: PostgreSQL not available after 60 seconds."
    exit 1
}

# ── Run database migrations ──────────────────────────────────────
run_migrations() {
    echo "Running database migrations..."
    flask db upgrade
    echo "Migrations complete."
}

# ── Seed initial data (vendors, admin) ───────────────────────────
seed_if_needed() {
    local count
    count=$(python -c "
from app import create_app
from app.models import Vendor
app = create_app()
with app.app_context():
    print(Vendor.query.count())
" 2>/dev/null || echo "0")
    
    if [ "$count" = "0" ]; then
        echo "Seeding initial data..."
        flask seed
        flask seed-admin
        echo "Seed complete."
    else
        echo "Database already seeded (${count} vendors found)."
    fi
}

# ── Main ─────────────────────────────────────────────────────────
case "${1}" in
    web)
        wait_for_db
        run_migrations
        seed_if_needed
        echo "Starting HCS Web on :8000..."
        exec gunicorn \
            --bind 0.0.0.0:8000 \
            --workers "${GUNICORN_WORKERS:-4}" \
            --timeout "${GUNICORN_TIMEOUT:-120}" \
            --access-logfile - \
            --error-logfile - \
            "app:create_app()"
        ;;

    worker-scan)
        wait_for_db
        echo "Starting Celery scan worker..."
        exec celery -A app.tasks worker \
            -Q scan \
            -c "${CELERY_CONCURRENCY:-4}" \
            --hostname="scan@%h" \
            --loglevel="${CELERY_LOGLEVEL:-info}"
        ;;

    worker-sync)
        wait_for_db
        echo "Starting Celery sync worker..."
        exec celery -A app.tasks worker \
            -Q sync \
            -c "${CELERY_CONCURRENCY:-2}" \
            --hostname="sync@%h" \
            --loglevel="${CELERY_LOGLEVEL:-info}"
        ;;

    worker-maintenance)
        wait_for_db
        echo "Starting Celery maintenance worker..."
        exec celery -A app.tasks worker \
            -Q maintenance,default \
            -c "${CELERY_CONCURRENCY:-2}" \
            --hostname="maintenance@%h" \
            --loglevel="${CELERY_LOGLEVEL:-info}"
        ;;

    worker-all)
        wait_for_db
        echo "Starting Celery worker (all queues)..."
        exec celery -A app.tasks worker \
            -Q scan,sync,maintenance,default \
            -c "${CELERY_CONCURRENCY:-4}" \
            --hostname="worker@%h" \
            --loglevel="${CELERY_LOGLEVEL:-info}"
        ;;

    beat)
        echo "Starting Celery Beat scheduler..."
        exec celery -A app.tasks beat \
            --loglevel="${CELERY_LOGLEVEL:-info}"
        ;;

    migrate)
        wait_for_db
        run_migrations
        ;;

    seed)
        wait_for_db
        run_migrations
        flask seed
        flask seed-admin
        echo "Seed complete."
        ;;

    shell)
        wait_for_db
        exec flask shell
        ;;

    *)
        exec "$@"
        ;;
esac
