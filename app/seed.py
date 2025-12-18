"""Seed data for initial setup."""
from app.extensions import db
from app.models import Vendor, Policy, Rule


def seed_vendors():
    """Create default vendors."""
    vendors = [
        Vendor(
            code="cisco_ios",
            name="Cisco IOS",
            parser_driver="ciscoconfparse",
            description="Cisco IOS and IOS-XE devices"
        ),
        Vendor(
            code="cisco_nxos",
            name="Cisco NX-OS",
            parser_driver="ciscoconfparse",
            description="Cisco Nexus switches"
        ),
        Vendor(
            code="eltex_esr",
            name="Eltex ESR",
            parser_driver="ciscoconfparse",
            description="Eltex ESR series routers"
        ),
        Vendor(
            code="usergate",
            name="UserGate",
            parser_driver="json",
            description="UserGate NGFW (JSON API)"
        ),
        Vendor(
            code="checkpoint",
            name="Check Point",
            parser_driver="json",
            description="Check Point firewalls (JSON API)"
        ),
        Vendor(
            code="huawei",
            name="Huawei",
            parser_driver="ciscoconfparse",
            description="Huawei VRP devices"
        ),
    ]
    
    for vendor in vendors:
        existing = Vendor.query.get(vendor.code)
        if not existing:
            db.session.add(vendor)
    
    db.session.commit()
    print(f"Seeded {len(vendors)} vendors")


def seed_policies():
    """Create default policies."""
    policies = [
        Policy(
            name="Basic Hardening",
            description="Fundamental security configurations",
            severity="high"
        ),
        Policy(
            name="Authentication",
            description="Authentication and authorization settings",
            severity="critical"
        ),
        Policy(
            name="Network Security",
            description="Network-level security controls",
            severity="high"
        ),
        Policy(
            name="Logging & Monitoring",
            description="Logging and monitoring configuration",
            severity="medium"
        ),
        Policy(
            name="PCI DSS",
            description="PCI DSS compliance requirements",
            severity="critical"
        ),
    ]
    
    for policy in policies:
        existing = Policy.query.filter_by(name=policy.name).first()
        if not existing:
            db.session.add(policy)
    
    db.session.commit()
    print(f"Seeded {len(policies)} policies")


def seed_sample_rules():
    """Create sample rules for Cisco IOS."""
    basic_policy = Policy.query.filter_by(name="Basic Hardening").first()
    auth_policy = Policy.query.filter_by(name="Authentication").first()
    
    if not basic_policy or not auth_policy:
        print("Policies not found, run seed_policies first")
        return
    
    rules = [
        Rule(
            policy_id=basic_policy.id,
            vendor_code="cisco_ios",
            title="Password Encryption",
            description="Ensures passwords are encrypted in config",
            remediation="service password-encryption",
            logic_type="simple_match",
            logic_payload={
                "pattern": "^service password-encryption",
                "match_mode": "must_exist",
                "is_regex": True
            }
        ),
        Rule(
            policy_id=basic_policy.id,
            vendor_code="cisco_ios",
            title="No Telnet",
            description="Telnet is insecure, use SSH instead",
            remediation="transport input ssh",
            logic_type="simple_match",
            logic_payload={
                "pattern": "transport input telnet",
                "match_mode": "must_not_exist",
                "is_regex": False
            }
        ),
        Rule(
            policy_id=auth_policy.id,
            vendor_code="cisco_ios",
            title="Enable Secret Set",
            description="Enable secret must be configured",
            remediation="enable secret <password>",
            logic_type="simple_match",
            logic_payload={
                "pattern": "^enable secret",
                "match_mode": "must_exist",
                "is_regex": True
            }
        ),
        Rule(
            policy_id=basic_policy.id,
            vendor_code="cisco_ios",
            title="No IP Redirects on Interfaces",
            description="ICMP redirects should be disabled on interfaces",
            remediation="no ip redirects",
            logic_type="block_match",
            logic_payload={
                "parent_block_start": "^interface (GigabitEthernet|TenGigabitEthernet|Ethernet)",
                "exclude_filter": "description.*UPLINK",
                "child_rules": [
                    {"pattern": "no ip redirects", "mode": "must_exist"}
                ],
                "logic": "ALL"
            }
        ),
    ]
    
    for rule in rules:
        existing = Rule.query.filter_by(title=rule.title).first()
        if not existing:
            db.session.add(rule)
    
    db.session.commit()
    print(f"Seeded {len(rules)} sample rules")


def seed_all():
    """Run all seed functions."""
    seed_vendors()
    seed_policies()
    seed_sample_rules()
    print("Seeding complete!")


if __name__ == "__main__":
    from app import create_app
    app = create_app()
    with app.app_context():
        seed_all()
