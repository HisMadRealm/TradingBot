# Contributing to TradingBot

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing.

## 🚀 Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/TradingBot.git
   cd TradingBot
   ```
3. **Create a virtual environment**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
4. **Copy environment template**:
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

## 📝 Development Workflow

1. **Create a feature branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** and test thoroughly

3. **Commit with clear messages**:
   ```bash
   git commit -m "feat: add new signal aggregation method"
   ```

4. **Push and create a Pull Request**:
   ```bash
   git push origin feature/your-feature-name
   ```

## 📋 Commit Message Format

Use conventional commits:
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `refactor:` - Code refactoring
- `test:` - Adding tests
- `chore:` - Maintenance tasks

## ⚠️ Important Guidelines

- **Never commit secrets** - Keep `.env` and API keys out of commits
- **Test with `--dry-run`** before submitting trading-related changes
- **Document new features** - Update README.md for significant changes
- **Keep it simple** - Prefer clarity over cleverness

## 🐛 Reporting Issues

When reporting bugs, please include:
- Python version
- Operating system
- Steps to reproduce
- Expected vs actual behavior
- Relevant log output (sanitize any secrets!)

## 💡 Feature Requests

We welcome feature ideas! Please:
- Check existing issues first
- Describe the use case clearly
- Explain why it would benefit others

## 📜 Code of Conduct

- Be respectful and inclusive
- Focus on constructive feedback
- Help others learn and grow

Thank you for contributing! 🎉
