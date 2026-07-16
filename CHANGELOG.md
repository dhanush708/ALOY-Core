# Changelog

All notable changes to ALOY will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-06-29

### Added
- **Dynamic Onboarding & Profiles**: Glassmorphic onboarding overlays blocking interface navigation until a user profile is configured.
- **Dynamic Model Configuration**: Centralized model config in `models/config.py` defining chat (`qwen3:14b`), coding (`qwen2.5-coder:14b`), vector embeddings (`nomic-embed-text:latest`), and reasoning (`deepseek-r1:14b`) specifications.
- **Startup Dependency & Hardware Audit**: `/api/system/health` checks database pools, workspace write permissions, Ollama connectivity, required model pull verification, RAM, disk space, and GPU/VRAM acceleration compatibility reports.
- **Profile Import/Export**: Support to export user profile configurations as JSON attachments and import them back for cross-machine migration.
- **Global Error Recovery Page**: Full-screen crash recovery overlay catching connection failures and offering bug reporting and client logs downloads.
- **Bug Reporting Action**: Permanent, immutable bug reporting prefilled templates targeting the creator support inbox (`anbudhanush31@gmail.com`).

### Changed
- **Attribution Lock**: Centralized all software ownership variables into the read-only `identity/metadata.py` module.
- **Resource Stats Telemetry**: Generalized the live telemetry monitors to work across generic GPUs instead of hardcoded laptop models.
- **Privacy Stripping**: Generalised geographic locations, hardware details, and founder memories in tests and documentation.
