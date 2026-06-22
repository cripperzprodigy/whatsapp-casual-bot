const fs = require('fs');
let content = fs.readFileSync('app/main.py', 'utf8');

const importAdd = `from app.whatsapp_gateway import check_gateway_health`;

if (!content.includes('check_gateway_health')) {
    content = content.replace('from app.permissions import bootstrap_owner', 'from app.permissions import bootstrap_owner\nfrom app.whatsapp_gateway import check_gateway_health');
}

const checkLogic = `
    try:
        health_status = await check_gateway_health()
        if health_status.get("requires_qr", False) or not health_status.get("isConnected", True):
            logger.warning("WhatsApp Gateway reports it is not connected or requires a QR scan. Please check http://localhost:8000/whatsapp/qr")
    except Exception as exc:
        logger.warning(f"Could not reach WhatsApp gateway during startup: {exc}")
`;

if (!content.includes('check_gateway_health()')) {
    content = content.replace(
        /try:\n        with SessionLocal\(\) as db:\n            await bootstrap_owner\(db\)\n    except Exception as exc:\n        logger\.error\("Error bootstrapping owner: %s", exc\)\n        raise/,
        `try:\n        with SessionLocal() as db:\n            await bootstrap_owner(db)\n    except Exception as exc:\n        logger.error("Error bootstrapping owner: %s", exc)\n        raise\n${checkLogic}`
    );
}

fs.writeFileSync('app/main.py', content);
