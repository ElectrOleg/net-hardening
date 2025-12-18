"""Policies API endpoints."""
from flask import request, jsonify
from app.api import api_bp
from app.extensions import db
from app.models import Policy


@api_bp.route("/policies", methods=["GET"])
def list_policies():
    """List all policies."""
    policies = Policy.query.filter_by(is_active=True).all()
    return jsonify([p.to_dict() for p in policies])


@api_bp.route("/policies/<uuid:policy_id>", methods=["GET"])
def get_policy(policy_id):
    """Get policy by ID."""
    policy = Policy.query.get_or_404(policy_id)
    return jsonify(policy.to_dict())


@api_bp.route("/policies", methods=["POST"])
def create_policy():
    """Create a new policy."""
    data = request.get_json()
    
    if not data.get("name"):
        return jsonify({"error": "name is required"}), 400
    
    policy = Policy(
        name=data["name"],
        description=data.get("description"),
        severity=data.get("severity", "medium"),
        is_active=data.get("is_active", True)
    )
    
    db.session.add(policy)
    db.session.commit()
    
    return jsonify(policy.to_dict()), 201


@api_bp.route("/policies/<uuid:policy_id>", methods=["PUT"])
def update_policy(policy_id):
    """Update policy."""
    policy = Policy.query.get_or_404(policy_id)
    data = request.get_json()
    
    for field in ["name", "description", "severity", "is_active"]:
        if field in data:
            setattr(policy, field, data[field])
    
    db.session.commit()
    return jsonify(policy.to_dict())


@api_bp.route("/policies/<uuid:policy_id>", methods=["DELETE"])
def delete_policy(policy_id):
    """Delete policy (soft delete by deactivating)."""
    policy = Policy.query.get_or_404(policy_id)
    policy.is_active = False
    db.session.commit()
    return "", 204
