"""HCS REST API Blueprints."""
from flask import Blueprint

api_bp = Blueprint("api", __name__)

# Import routes to register them
from app.api import vendors, policies, rules, scans, results, exceptions, test, exports, remediation

# Register nested blueprints
from app.api.data_sources import data_sources_bp
api_bp.register_blueprint(data_sources_bp, url_prefix="/data-sources")

from app.api.inventory_sources import inventory_sources_bp
api_bp.register_blueprint(inventory_sources_bp, url_prefix="/inventory-sources")

from app.api.devices import devices_bp
api_bp.register_blueprint(devices_bp, url_prefix="/devices")

from app.api.device_groups import device_groups_bp
api_bp.register_blueprint(device_groups_bp, url_prefix="/device-groups")
