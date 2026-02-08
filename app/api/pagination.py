"""Pagination helper for API endpoints."""
from flask import request, jsonify


def paginate_query(query, max_per_page=100):
    """
    Apply pagination to a SQLAlchemy query.
    
    Reads ?page= and ?per_page= from query string.
    Returns (paginated_response_dict, status_code).
    
    Response format:
    {
        "items": [...],
        "total": 123,
        "page": 1,
        "per_page": 20,
        "pages": 7
    }
    """
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    
    # Clamp values
    page = max(1, page)
    per_page = max(1, min(per_page, max_per_page))
    
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    return {
        "items": pagination.items,
        "total": pagination.total,
        "page": pagination.page,
        "per_page": pagination.per_page,
        "pages": pagination.pages,
    }
