"""Data Sources API endpoints."""
from flask import Blueprint, request, jsonify
from app.extensions import db
from app.models import DataSource

data_sources_bp = Blueprint("data_sources", __name__)


@data_sources_bp.route("", methods=["GET"])
def list_data_sources():
    """List all data sources."""
    sources = DataSource.query.order_by(DataSource.name).all()
    return jsonify([s.to_dict() for s in sources])


@data_sources_bp.route("", methods=["POST"])
def create_data_source():
    """Create a new data source."""
    data = request.get_json()
    
    if not data.get("name") or not data.get("type"):
        return jsonify({"error": "Name and type are required"}), 400
    
    source = DataSource(
        name=data["name"],
        type=data["type"],
        credentials_ref=data.get("credentials_ref"),
        connection_params=data.get("connection_params", {}),
        is_active=data.get("is_active", True)
    )
    
    db.session.add(source)
    db.session.commit()
    
    return jsonify(source.to_dict()), 201


@data_sources_bp.route("/<uuid:source_id>", methods=["GET"])
def get_data_source(source_id):
    """Get a single data source."""
    source = DataSource.query.get_or_404(source_id)
    return jsonify(source.to_dict())


@data_sources_bp.route("/<uuid:source_id>", methods=["PUT"])
def update_data_source(source_id):
    """Update a data source."""
    source = DataSource.query.get_or_404(source_id)
    data = request.get_json()
    
    if "name" in data:
        source.name = data["name"]
    if "type" in data:
        source.type = data["type"]
    if "credentials_ref" in data:
        source.credentials_ref = data["credentials_ref"]
    if "connection_params" in data:
        source.connection_params = data["connection_params"]
    if "is_active" in data:
        source.is_active = data["is_active"]
    
    db.session.commit()
    return jsonify(source.to_dict())


@data_sources_bp.route("/<uuid:source_id>", methods=["DELETE"])
def delete_data_source(source_id):
    """Delete a data source."""
    source = DataSource.query.get_or_404(source_id)
    db.session.delete(source)
    db.session.commit()
    return "", 204


@data_sources_bp.route("/<uuid:source_id>/test", methods=["POST"])
def test_data_source(source_id):
    """Test connection to a data source."""
    source = DataSource.query.get_or_404(source_id)
    
    try:
        from app.core.registry import get_config_provider
        import os
        
        # Get credentials
        token = os.environ.get(source.credentials_ref, "") if source.credentials_ref else ""
        
        # Prepare config
        config = source.connection_params or {}
        if "token" not in config:
            config["token"] = token
        if "password" not in config and token:
            config["password"] = token
        
        provider = get_config_provider(source.type, config)
        success, message = provider.test_connection()
        provider.close()
        
        return jsonify({"success": success, "message": message})
        
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})
