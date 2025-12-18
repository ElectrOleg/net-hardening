"""Vendors API endpoints."""
from flask import request, jsonify
from app.api import api_bp
from app.extensions import db
from app.models import Vendor


@api_bp.route("/vendors", methods=["GET"])
def list_vendors():
    """List all vendors."""
    vendors = Vendor.query.all()
    return jsonify([v.to_dict() for v in vendors])


@api_bp.route("/vendors/<code>", methods=["GET"])
def get_vendor(code):
    """Get vendor by code."""
    vendor = Vendor.query.get_or_404(code)
    return jsonify(vendor.to_dict())


@api_bp.route("/vendors", methods=["POST"])
def create_vendor():
    """Create a new vendor."""
    data = request.get_json()
    
    if not data.get("code") or not data.get("name"):
        return jsonify({"error": "code and name are required"}), 400
    
    if Vendor.query.get(data["code"]):
        return jsonify({"error": "Vendor already exists"}), 409
    
    vendor = Vendor(
        code=data["code"],
        name=data["name"],
        parser_driver=data.get("parser_driver"),
        description=data.get("description")
    )
    
    db.session.add(vendor)
    db.session.commit()
    
    return jsonify(vendor.to_dict()), 201


@api_bp.route("/vendors/<code>", methods=["PUT"])
def update_vendor(code):
    """Update vendor."""
    vendor = Vendor.query.get_or_404(code)
    data = request.get_json()
    
    if "name" in data:
        vendor.name = data["name"]
    if "parser_driver" in data:
        vendor.parser_driver = data["parser_driver"]
    if "description" in data:
        vendor.description = data["description"]
    
    db.session.commit()
    return jsonify(vendor.to_dict())


@api_bp.route("/vendors/<code>", methods=["DELETE"])
def delete_vendor(code):
    """Delete vendor."""
    vendor = Vendor.query.get_or_404(code)
    db.session.delete(vendor)
    db.session.commit()
    return "", 204
