server:
  title: VHS-Sat
  host: 0.0.0.0
  port: 8300
  debug: false

security:
  auth_enabled: true
  users: []

database:
  path: data/vhs-sat.db

logging:
  events_file: logs/events.jsonl
  level: INFO

adapters: []
ci_slots: []