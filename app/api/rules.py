"""Rules API endpoints."""
from flask import request, jsonify
from app.api import api_bp
from app.extensions import db
from app.models import Rule, Policy, Vendor


@api_bp.route("/rules", methods=["GET"])
def list_rules():
    """List rules with optional filters."""
    query = Rule.query.filter_by(is_active=True)
    
    # Optional filters
    policy_id = request.args.get("policy_id")
    vendor_code = request.args.get("vendor_code")
    logic_type = request.args.get("logic_type")
    
    if policy_id:
        query = query.filter_by(policy_id=policy_id)
    if vendor_code:
        query = query.filter_by(vendor_code=vendor_code)
    if logic_type:
        query = query.filter_by(logic_type=logic_type)
    
    rules = query.all()
    return jsonify([r.to_dict() for r in rules])


@api_bp.route("/rules/<uuid:rule_id>", methods=["GET"])
def get_rule(rule_id):
    """Get rule by ID."""
    rule = Rule.query.get_or_404(rule_id)
    return jsonify(rule.to_dict())


@api_bp.route("/rules", methods=["POST"])
def create_rule():
    """Create a new rule."""
    data = request.get_json()
    
    # Validate required fields
    required = ["policy_id", "vendor_code", "title", "logic_type", "logic_payload"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400
    
    # Validate foreign keys
    if not Policy.query.get(data["policy_id"]):
        return jsonify({"error": "Policy not found"}), 404
    if not Vendor.query.get(data["vendor_code"]):
        return jsonify({"error": "Vendor not found"}), 404
    
    # Validate logic_payload
    from app.engine import RuleEvaluator
    evaluator = RuleEvaluator()
    try:
        checker = evaluator._get_checker(data["logic_type"])
        errors = checker.validate_payload(data["logic_payload"])
        if errors:
            return jsonify({"error": f"Invalid payload: {errors}"}), 400
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    
    rule = Rule(
        policy_id=data["policy_id"],
        vendor_code=data["vendor_code"],
        title=data["title"],
        description=data.get("description"),
        remediation=data.get("remediation"),
        logic_type=data["logic_type"],
        logic_payload=data["logic_payload"],
        is_active=data.get("is_active", True)
    )
    
    db.session.add(rule)
    db.session.commit()
    
    return jsonify(rule.to_dict()), 201


@api_bp.route("/rules/<uuid:rule_id>", methods=["PUT"])
def update_rule(rule_id):
    """Update rule."""
    rule = Rule.query.get_or_404(rule_id)
    data = request.get_json()
    
    # Update simple fields
    for field in ["title", "description", "remediation", "is_active"]:
        if field in data:
            setattr(rule, field, data[field])
    
    # Update logic (validate first)
    if "logic_type" in data or "logic_payload" in data:
        logic_type = data.get("logic_type", rule.logic_type)
        logic_payload = data.get("logic_payload", rule.logic_payload)
        
        from app.engine import RuleEvaluator
        evaluator = RuleEvaluator()
        try:
            checker = evaluator._get_checker(logic_type)
            errors = checker.validate_payload(logic_payload)
            if errors:
                return jsonify({"error": f"Invalid payload: {errors}"}), 400
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        
        rule.logic_type = logic_type
        rule.logic_payload = logic_payload
    
    db.session.commit()
    return jsonify(rule.to_dict())


@api_bp.route("/rules/<uuid:rule_id>", methods=["DELETE"])
def delete_rule(rule_id):
    """Delete rule (soft delete)."""
    rule = Rule.query.get_or_404(rule_id)
    rule.is_active = False
    db.session.commit()
    return "", 204
