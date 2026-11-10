// Usage: node scripts/hash-ui-password.mjs 'my password'   -> prints UI_BASIC_PASSWORD_SCRYPT value
import { randomBytes, scryptSync } from "node:crypto";
const pw = process.argv[2];
if (!pw) { console.error("usage: node scripts/hash-ui-password.mjs <password>"); process.exit(1); }
const salt = randomBytes(16);
console.log(`${salt.toString("hex")}:${scryptSync(pw, salt, 32).toString("hex")}`);
