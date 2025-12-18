# Примеры правил для AdvancedBlockChecker

Эти примеры показывают как использовать расширенный checker для сложных проверок.

## 1. Проверка Access-портов (все настройки должны быть)

```json
{
    "logic_type": "advanced_block_check",
    "payload": {
        "block": {
            "start": "^interface (GigabitEthernet|FastEthernet)\\S+",
            "filter": {
                "exclude": "Loopback|Vlan"
            }
        },
        "checks": [
            {
                "group": [
                    "switchport mode access",
                    "switchport access vlan \\d+",
                    "spanning-tree portfast",
                    "spanning-tree bpduguard enable"
                ],
                "mode": "all_must_exist",
                "name": "Access port security"
            }
        ]
    }
}
```

## 2. Проверка Trunk-портов с вложенными ACL

```json
{
    "logic_type": "advanced_block_check",
    "payload": {
        "block": {
            "start": "^interface (TenGig|Ethernet)\\S+"
        },
        "checks": [
            {
                "pattern": "switchport mode trunk",
                "mode": "must_exist"
            },
            {
                "pattern": "switchport trunk allowed vlan",
                "mode": "must_exist"
            },
            {
                "pattern": "switchport trunk allowed vlan all",
                "mode": "must_not_exist",
                "comment": "Нельзя разрешать все VLAN"
            },
            {
                "nested_block": {
                    "start": "service-policy",
                    "checks": [
                        {"pattern": "input", "mode": "must_exist"}
                    ]
                }
            }
        ]
    }
}
```

## 3. Условная проверка (IP-helper только для access портов)

```json
{
    "logic_type": "advanced_block_check",
    "payload": {
        "block": {
            "start": "^interface Vlan(\\d+)"
        },
        "checks": [
            {
                "pattern": "ip helper-address \\d+\\.\\d+\\.\\d+\\.\\d+",
                "mode": "must_exist",
                "condition": {
                    "if_match": "ip address \\d"
                }
            },
            {
                "pattern": "no ip proxy-arp",
                "mode": "must_exist"
            }
        ]
    }
}
```

## 4. Cross-block валидация (уникальные IP, одинаковые VLAN)

```json
{
    "logic_type": "advanced_block_check",
    "payload": {
        "block": {
            "start": "^interface \\S+"
        },
        "checks": [
            {"pattern": "ip address", "mode": "must_exist"}
        ],
        "cross_block": {
            "unique": ["ip address (\\d+\\.\\d+\\.\\d+\\.\\d+)"],
            "all_same": ["mtu (\\d+)"]
        }
    }
}
```

## 5. Eltex MES - проверка VLAN на портах

```json
{
    "logic_type": "advanced_block_check",
    "payload": {
        "block": {
            "start": "^interface ethernet \\S+"
        },
        "checks": [
            {
                "group": [
                    "switchport mode",
                    "switchport forbidden default-vlan"
                ],
                "mode": "all_must_exist",
                "name": "Port security config"
            },
            {
                "pattern": "no lldp transmit",
                "mode": "must_exist",
                "condition": {
                    "if_match": "switchport mode access"
                }
            }
        ]
    }
}
```

## 6. Exactly one (ровно один из вариантов)

```json
{
    "logic_type": "advanced_block_check",
    "payload": {
        "block": {
            "start": "^interface \\S+"
        },
        "checks": [
            {
                "group": [
                    "switchport mode access",
                    "switchport mode trunk",
                    "no switchport"
                ],
                "mode": "exactly_one",
                "name": "Port mode must be defined once"
            }
        ]
    }
}
```
