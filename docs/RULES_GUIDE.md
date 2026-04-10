# HCS — Руководство по созданию правил проверок

## Типы проверок (logic_type)

HCS поддерживает несколько типов проверок. Каждый тип определяет **как** анализируется конфигурация.

---

## 1. `simple_match` — Поиск строки/паттерна

Самый частый тип. Проверяет наличие или отсутствие строки (regex) в тексте конфигурации.

### Один паттерн (must_exist)

**Пример**: проверить что включено шифрование паролей

```json
{
  "logic_type": "simple_match",
  "logic_payload": {
    "pattern": "^service password-encryption\\s*$",
    "mode": "must_exist",
    "multiline": true
  }
}
```

**В UI (Rule Builder)**:  
- Logic Type: `simple_match`  
- Pattern: `^service password-encryption\s*$`  
- Mode: `must_exist`  
- ☑ Multiline  

### Несколько паттернов (all_must_exist)

**Пример**: проверить что включены ALL: `aaa authentication`, `aaa authorization`, `aaa accounting`

```json
{
  "logic_type": "simple_match",
  "logic_payload": {
    "patterns": [
      "^aaa authentication.*$",
      "^aaa authorization.*$",
      "^aaa accounting.*$"
    ],
    "mode": "all_must_exist",
    "multiline": true
  }
}
```

### Запрет строки (must_not_exist)

**Пример**: проверить что HTTP-сервер отключен

```json
{
  "logic_type": "simple_match",
  "logic_payload": {
    "pattern": "^ip http server\\s*$",
    "mode": "must_not_exist",
    "multiline": true
  }
}
```

> **Совет**: `must_not_exist` полезен когда нужно проверить отсутствие опасной конфигурации (например, `ip http server` без `no`).

---

## 2. `block_match` — Проверка блока конфигурации

Находит блок по стартовому паттерну (например `line vty 0 4`) и проверяет что внутри есть нужные строки.

### Пример: VTY line hardening

**Задача**: убедиться что в блоке `line vty 0 4` есть `access-class SSH-IN in` и `transport input ssh`.

```json
{
  "logic_type": "block_match",
  "logic_payload": {
    "block_start": "^line vty 0 4\\s*$",
    "must_contain": [
      "access-class SSH-IN in",
      "transport input ssh"
    ]
  }
}
```

**Как это работает**:
1. Ищет строку, матчащую `block_start`
2. Собирает все строки с отступом после неё до следующего блока
3. Проверяет что каждая строка из `must_contain` найдена внутри блока

**В UI (Rule Builder)**:  
- Logic Type: `block_match`  
- Block Start: `^line vty 0 4\s*$`  
- Must Contain: по одной строке на запись

### С must_not_contain

```json
{
  "logic_type": "block_match",
  "logic_payload": {
    "block_start": "^interface GigabitEthernet0/0",
    "must_contain": ["shutdown"],
    "must_not_contain": ["no shutdown"]
  }
}
```

---

## 3. `advanced_block` — Вложенные блоки

Для проверки вложенных контекстов (например, `router bgp > address-family > neighbor`).

```json
{
  "logic_type": "advanced_block",
  "logic_payload": {
    "sections": [
      {
        "match": "^router ospf \\d+",
        "must_contain": ["log-adjacency-changes"],
        "children": [
          {
            "match": "^\\s*area \\d+",
            "must_contain": ["authentication message-digest"]
          }
        ]
      }
    ]
  }
}
```

---

## 4. `composite_check` — Несколько секций

Объединяет несколько независимых проверок в одно правило. PASS только если **все** секции проходят.

```json
{
  "logic_type": "composite_check",
  "logic_payload": {
    "operator": "AND",
    "checks": [
      {
        "logic_type": "simple_match",
        "logic_payload": {
          "pattern": "^ip ssh version 2",
          "mode": "must_exist",
          "multiline": true
        }
      },
      {
        "logic_type": "simple_match",
        "logic_payload": {
          "pattern": "^ip ssh time-out 60",
          "mode": "must_exist",
          "multiline": true
        }
      }
    ]
  }
}
```

---

## Импорт правил через JSON

### Формат файла

```json
{
  "rules": [
    {
      "title": "Название проверки",
      "description": "Описание уязвимости",
      "vendor_code": "cisco_ios",
      "logic_type": "simple_match",
      "severity": "high",
      "logic_payload": { ... },
      "remediation": "Команды для исправления"
    }
  ]
}
```

### Процедура импорта

1. Перейдите в **Rules** → кнопка **Импорт**
2. Выберите **целевую политику** (в которую добавить правила)
3. Выберите **режим**:
   - `Merge` — добавить новые, пропустить дубликаты по title
   - `Replace` — удалить все правила политики и загрузить новые
4. Загрузите JSON файл
5. Нажмите **Dry Run** для проверки без изменений
6. Нажмите **Импортировать** для загрузки

### Готовые файлы

- `checks_import_ios.json` — 16 проверок Cisco IOS (switch/router)
- `checks_import_nxos.json` — 10 проверок Cisco NXOS

---

## Severity Guide

| Уровень | Когда использовать | Примеры |
|---------|-------------------|---------|
| `critical` | Прямая угроза — удалённый доступ без SSH | VTY без ACL, HTTP-сервер открыт, Smart Install |
| `high` | Важная защита | Password encryption, SNMP ACL, Syslog |
| `medium` | Best practice | Timestamps, SSH timeout, Exec timeout |
| `low` | Рекомендация | Banner login, NTP ACL |
| `info` | Информационная | Версия ПО, инвентаризация |
