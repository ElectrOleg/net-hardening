"""Device Groups API endpoints."""
from flask import Blueprint, request, jsonify
from app.extensions import db
from app.models import DeviceGroup, Policy

device_groups_bp = Blueprint("device_groups", __name__)


@device_groups_bp.route("", methods=["GET"])
def list_groups():
    """List all device groups."""
    groups = DeviceGroup.query.filter_by(is_active=True).order_by(DeviceGroup.name).all()
    return jsonify([g.to_dict() for g in groups])


@device_groups_bp.route("", methods=["POST"])
def create_group():
    """Create a new device group."""
    data = request.get_json()
    
    if not data.get("name"):
        return jsonify({"error": "Name is required"}), 400
    
    if DeviceGroup.query.filter_by(name=data["name"]).first():
        return jsonify({"error": "Group with this name already exists"}), 400
    
    group = DeviceGroup(
        name=data["name"],
        description=data.get("description"),
        parent_id=data.get("parent_id"),
        is_active=data.get("is_active", True)
    )
    
    # Assign policies
    if data.get("policy_ids"):
        policies = Policy.query.filter(Policy.id.in_(data["policy_ids"])).all()
        group.policies = policies
    
    db.session.add(group)
    db.session.commit()
    
    return jsonify(group.to_dict()), 201


@device_groups_bp.route("/<uuid:group_id>", methods=["GET"])
def get_group(group_id):
    """Get a single group with its devices."""
    group = DeviceGroup.query.get_or_404(group_id)
    result = group.to_dict()
    result["devices"] = [d.to_dict() for d in group.devices]
    return jsonify(result)


@device_groups_bp.route("/<uuid:group_id>", methods=["PUT"])
def update_group(group_id):
    """Update a device group."""
    group = DeviceGroup.query.get_or_404(group_id)
    data = request.get_json()
    
    if "name" in data:
        existing = DeviceGroup.query.filter_by(name=data["name"]).first()
        if existing and existing.id != group.id:
            return jsonify({"error": "Group with this name already exists"}), 400
        group.name = data["name"]
    if "description" in data:
        group.description = data["description"]
    if "parent_id" in data:
        group.parent_id = data["parent_id"]
    if "is_active" in data:
        group.is_active = data["is_active"]
    if "policy_ids" in data:
        policies = Policy.query.filter(Policy.id.in_(data["policy_ids"])).all()
        group.policies = policies
    
    db.session.commit()
    return jsonify(group.to_dict())


@device_groups_bp.route("/<uuid:group_id>", methods=["DELETE"])
def delete_group(group_id):
    """Delete a device group."""
    group = DeviceGroup.query.get_or_404(group_id)
    
    # Remove group reference from devices
    for device in group.devices:
        device.group_id = None
    
    db.session.delete(group)
    db.session.commit()
    return "", 204
