# Security Policy

## 🔐 Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do NOT** open a public GitHub issue
2. Email the maintainer directly with details
3. Allow up to 48 hours for an initial response

## 🛡️ Security Best Practices

When using this trading bot:

### API Keys & Secrets
- **Never commit `.env` files** to version control
- Use `.env.example` as a template only
- Rotate API keys periodically
- Use separate keys for testing vs production

### Wallet Security
- Use a **dedicated trading wallet** - not your main wallet
- Start with small amounts for testing
- Enable allowance limits in the Polymarket API
- Consider using a hardware wallet for signing

### Server Deployment
- Use environment variables, not config files for secrets
- Restrict SSH access with key-based authentication
- Keep the server updated with security patches
- Monitor logs for unusual activity

## ⚠️ Disclaimer

This software trades with real money. The authors are not responsible for:
- Financial losses from trading
- API key exposure
- Bugs or unexpected behavior

**Always start with `--dry-run` mode and small positions.**

## 📋 Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| main    | ✅ Yes             |
| < main  | ❌ No              |

We only support the latest version on the `main` branch.
