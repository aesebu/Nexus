# NEXUS Core

แกนกลางตาม NEXUS-SAI-MB-001 — Python ล้วน (stdlib) ไม่ผูก framework/DB
เพื่อให้กฎ governance ทดสอบได้ แล้วค่อยครอบด้วย FastAPI + SQLAlchemy ใน repo หลัก

```
nexus_core/
├── kernel.py        Principal, Authority/Autonomy, AuditLog (hash-chain), EventBus
├── governance.py    CORE-09 PolicyEngine (fail-closed), EmergencyStop
├── control.py       CORE-01 CommandBus (lifecycle + approval + rollback), SystemRegistry
├── intelligence.py  CORE-02 AIEngine, CORE-03 ModelRegistry, CORE-04 AgentEngine, CORE-05 Memory
├── automation.py    CORE-07 WorkflowEngine (retry, หยุดรอ approval)
└── __init__.py      Nexus (Level 1) + Core (Level 2)
tests/test_core.py
```

## กฎที่บังคับในโค้ด
- คำสั่งที่ไม่ได้ลงทะเบียน = ปฏิเสธ (fail-closed)
- Risk HIGH → ต้อง approve โดยคนอื่น; CRITICAL / irreversible → ต้องเป็น Human Owner
- Agent ระดับต่ำกว่า L4 รันได้เฉพาะงานที่ approve แล้ว; agent/tool approve ไม่ได้
- Agent ได้สิทธิ์/autonomy ไม่เกินผู้สร้าง, agent สร้าง agent ไม่ได้
- Emergency stop ต่อ tenant; ล้างได้เฉพาะมนุษย์
- Audit log แบบ hash-chain — `verify()` จับการแก้ย้อนหลัง
- ทุก lookup แยก tenant

## รัน
```bash
python -m unittest discover -s tests -v
python demo.py
```
