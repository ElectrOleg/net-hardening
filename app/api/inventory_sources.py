"""Inventory Sources API endpoints."""
from flask import Blueprint, request, jsonify
from app.extensions import db
from app.models import InventorySource

inventory_sources_bp = Blueprint("inventory_sources", __name__)


@inventory_sources_bp.route("", methods=["GET"])
def list_inventory_sources():
    """List all inventory sources."""
    sources = InventorySource.query.order_by(InventorySource.name).all()
    return jsonify([s.to_dict() for s in sources])


@inventory_sources_bp.route("", methods=["POST"])
def create_inventory_source():
    """Create a new inventory source."""
    data = request.get_json()
    
    if not data.get("name") or not data.get("type"):
        return jsonify({"error": "Name and type are required"}), 400
    
    source = InventorySource(
        name=data["name"],
        type=data["type"],
        description=data.get("description"),
        credentials_ref=data.get("credentials_ref"),
        connection_params=data.get("connection_params", {}),
        sync_enabled=data.get("sync_enabled", True),
        sync_interval_minutes=data.get("sync_interval_minutes", 60),
        is_active=data.get("is_active", True)
    )
    
    db.session.add(source)
    db.session.commit()
    
    return jsonify(source.to_dict()), 201


@inventory_sources_bp.route("/<uuid:source_id>", methods=["GET"])
def get_inventory_source(source_id):
    """Get a single inventory source."""
    source = InventorySource.query.get_or_404(source_id)
    return jsonify(source.to_dict())


@inventory_sources_bp.route("/<uuid:source_id>", methods=["PUT"])
def update_inventory_source(source_id):
    """Update an inventory source."""
    source = InventorySource.query.get_or_404(source_id)
    data = request.get_json()
    
    if "name" in data:
        source.name = data["name"]
    if "type" in data:
        source.type = data["type"]
    if "description" in data:
        source.description = data["description"]
    if "credentials_ref" in data:
        source.credentials_ref = data["credentials_ref"]
    if "connection_params" in data:
        source.connection_params = data["connection_params"]
    if "sync_enabled" in data:
        source.sync_enabled = data["sync_enabled"]
    if "sync_interval_minutes" in data:
        source.sync_interval_minutes = data["sync_interval_minutes"]
    if "is_active" in data:
        source.is_active = data["is_active"]
    
    db.session.commit()
    return jsonify(source.to_dict())


@inventory_sources_bp.route("/<uuid:source_id>", methods=["DELETE"])
def delete_inventory_source(source_id):
    """Delete an inventory source."""
    source = InventorySource.query.get_or_404(source_id)
    db.session.delete(source)
    db.session.commit()
    return "", 204


@inventory_sources_bp.route("/<uuid:source_id>/test", methods=["POST"])
def test_inventory_source(source_id):
    """Test connection to an inventory source."""
    source = InventorySource.query.get_or_404(source_id)
    
    try:
        from app.core.registry import get_inventory_provider
        import os
        
        # Get credentials
        password = os.environ.get(source.credentials_ref, "") if source.credentials_ref else ""
        
        # Prepare config
        config = source.connection_params or {}
        if "password" not in config and password:
            config["password"] = password
        
        provider = get_inventory_provider(source.type, config)
        success, message = provider.test_connection()
        provider.close()
        
        return jsonify({"success": success, "message": message})
        
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@inventory_sources_bp.route("/<uuid:source_id>/sync", methods=["POST"])
def sync_inventory_source(source_id):
    """Manually trigger sync from an inventory source."""
    source = InventorySource.query.get_or_404(source_id)
    
    try:
        from app.core.registry import get_inventory_provider
        from datetime import datetime
        import os
        
        password = os.environ.get(source.credentials_ref, "") if source.credentials_ref else ""
        config = source.connection_params or {}
        if "password" not in config and password:
            config["password"] = password
        
        provider = get_inventory_provider(source.type, config)
        devices = provider.list_devices()
        provider.close()
        
        # Update last sync time
        source.last_sync_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            "success": True, 
            "devices_count": len(devices),
            "message": f"Synced {len(devices)} devices"
        })
        
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})
