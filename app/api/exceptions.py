"""Exceptions (Waivers) API endpoints."""
from datetime import date
from flask import request, jsonify
from app.api import api_bp
from app.api.pagination import paginate_query
from app.extensions import db
from app.models import RuleException, Rule


@api_bp.route("/exceptions", methods=["GET"])
def list_exceptions():
    """List active exceptions."""
    include_expired = request.args.get("include_expired", "false").lower() == "true"
    
    query = RuleException.query.filter_by(is_active=True)
    
    if not include_expired:
        query = query.filter(
            (RuleException.expiry_date == None) | (RuleException.expiry_date >= date.today())
        )
    
    result = paginate_query(query)
    result["items"] = [e.to_dict(include_rule=True) for e in result["items"]]
    return jsonify(result)


@api_bp.route("/exceptions/<uuid:exception_id>", methods=["GET"])
def get_exception(exception_id):
    """Get exception details."""
    exc = RuleException.query.get_or_404(exception_id)
    return jsonify(exc.to_dict(include_rule=True))


@api_bp.route("/exceptions", methods=["POST"])
def create_exception():
    """Create a new exception (accept risk)."""
    data = request.get_json()
    
    # Validate required fields
    if not data.get("rule_id"):
        return jsonify({"error": "rule_id is required"}), 400
    if not data.get("reason"):
        return jsonify({"error": "reason is required"}), 400
    if not data.get("approved_by"):
        return jsonify({"error": "approved_by is required"}), 400
    
    # Validate rule exists
    if not Rule.query.get(data["rule_id"]):
        return jsonify({"error": "Rule not found"}), 404
    
    # Parse expiry date
    expiry_date = None
    if data.get("expiry_date"):
        try:
            expiry_date = date.fromisoformat(data["expiry_date"])
        except ValueError:
            return jsonify({"error": "Invalid expiry_date format (use YYYY-MM-DD)"}), 400
    
    exc = RuleException(
        device_id=data.get("device_id"),  # None = applies to all devices
        rule_id=data["rule_id"],
        reason=data["reason"],
        approved_by=data["approved_by"],
        expiry_date=expiry_date,
        is_active=True
    )
    
    db.session.add(exc)
    db.session.commit()
    
    return jsonify(exc.to_dict()), 201


@api_bp.route("/exceptions/<uuid:exception_id>", methods=["PUT"])
def update_exception(exception_id):
    """Update exception."""
    exc = RuleException.query.get_or_404(exception_id)
    data = request.get_json()
    
    if "reason" in data:
        exc.reason = data["reason"]
    if "is_active" in data:
        exc.is_active = data["is_active"]
    if "expiry_date" in data:
        if data["expiry_date"]:
            exc.expiry_date = date.fromisoformat(data["expiry_date"])
        else:
            exc.expiry_date = None
    
    db.session.commit()
    return jsonify(exc.to_dict())


@api_bp.route("/exceptions/<uuid:exception_id>", methods=["DELETE"])
def delete_exception(exception_id):
    """Delete (deactivate) exception."""
    exc = RuleException.query.get_or_404(exception_id)
    exc.is_active = False
    db.session.commit()
    return "", 204


@api_bp.route("/exceptions/check", methods=["POST"])
def check_exception():
    """Check if an exception exists for device + rule."""
    data = request.get_json()
    device_id = data.get("device_id")
    rule_id = data.get("rule_id")
    
    if not rule_id:
        return jsonify({"error": "rule_id is required"}), 400
    
    # Check for device-specific or global exception
    exc = RuleException.query.filter(
        RuleException.rule_id == rule_id,
        RuleException.is_active == True,
        (RuleException.expiry_date == None) | (RuleException.expiry_date >= date.today()),
        (RuleException.device_id == device_id) | (RuleException.device_id == None)
    ).first()
    
    if exc:
        return jsonify({
            "has_exception": True,
            "exception": exc.to_dict()
        })
    
    return jsonify({"has_exception": False})
