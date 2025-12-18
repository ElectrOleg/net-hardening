"""HCS REST API Blueprints."""
from flask import Blueprint

api_bp = Blueprint("api", __name__)

# Import routes to register them
from app.api import vendors, policies, rules, scans, results, exceptions, test, exports, remediation
